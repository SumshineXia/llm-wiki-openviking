from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Set, Tuple

from openai import OpenAI

from ovfs import OVFSClient, OVFSConfig, OVFSError, OVFSHTTPError
from common import build_kb_root, load_config


DEFAULT_LLM_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "llm-wiki-config.json"
)

LEGACY_LLM_CONFIG_PATHS = [
    Path(__file__).resolve().parent.parent / "config" / "wiki_query.conf.json",
]

INDEX_TITLE = "# 索引"
OVERVIEW_TITLE = "# 概览"
LOG_TITLE = "# 操作日志\n"

INDEX_SECTIONS = {
    "sources": "## 资料来源",
    "entities": "## 实体",
    "concepts": "## 概念",
    "syntheses": "## 综合结论",
}

LEGACY_INDEX_SECTIONS = {
    "sources": ["## Sources"],
    "entities": ["## Entities"],
    "concepts": ["## Concepts"],
    "syntheses": ["## Syntheses"],
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this",
    "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "for", "from", "with", "by", "at", "as", "into",
    "what", "how", "why", "when", "where", "who", "which",
    "do", "does", "did", "can", "could", "should", "would", "may", "might",
    "about", "please", "use", "using", "tell", "me", "explain",
}

ZH_STOPWORDS = {
    "这个", "那个", "这些", "那些", "我们", "你们", "他们", "它们",
    "一个", "一种", "一些", "以及", "并且", "或者", "但是", "如果",
    "什么", "怎么", "如何", "吗", "呢", "吧", "啊", "呀",
}

QUESTION_ENDINGS = {
    "什么",
    "吗",
    "呢",
    "么",
    "嘛",
    "如何",
    "怎么样",
    "怎样",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str) -> str:
    normalized = text.strip().lower()
    tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", normalized)
    if not tokens:
        return "untitled"
    return "-".join(tokens)


def condense_question_for_slug(question: str) -> str:
    normalized = question.strip().rstrip("？?！!。；;，,")

    for ending in sorted(QUESTION_ENDINGS, key=len, reverse=True):
        if normalized.endswith(ending):
            normalized = normalized[: -len(ending)].rstrip("？?！!。；;，,")
            break

    return normalized or question.strip()


def build_synthesis_target(slug: str | None, question: str) -> str:
    if slug and slug.strip():
        return f"wiki/syntheses/{slugify(slug)}.md"

    condensed_question = condense_question_for_slug(question)
    condensed = slugify(condensed_question)
    if condensed:
        condensed = condensed[:48].strip("-")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if condensed:
        return f"wiki/syntheses/{condensed}-{timestamp}.md"

    return f"wiki/syntheses/query-{timestamp}.md"


def read_local_schema() -> str:
    schema_path = Path(__file__).resolve().parents[1] / "references" / "wiki_schema.md"
    return schema_path.read_text(encoding="utf-8")


def load_llm_config(config_path: str) -> Dict[str, Any]:
    path = Path(config_path)
    if path != DEFAULT_LLM_CONFIG_PATH:
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return {}
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"LLM config must be a JSON object: {path}")
        return data

    merged: Dict[str, Any] = {}
    candidates = [*LEGACY_LLM_CONFIG_PATHS, DEFAULT_LLM_CONFIG_PATH]
    for candidate in candidates:
        if not candidate.exists():
            continue
        text = candidate.read_text(encoding="utf-8").strip()
        if not text:
            continue
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"LLM config must be a JSON object: {candidate}")
        for key, value in data.items():
            if isinstance(value, str) and not value.strip():
                continue
            if value is None:
                continue
            merged[key] = value

    return merged


def pick_first_non_empty(*values: Optional[str]) -> Optional[str]:
    for value in values:
        if isinstance(value, str):
            normalized_value = value.strip()
            if normalized_value:
                return normalized_value
    return None


def resolve_openai_settings(args: argparse.Namespace) -> Dict[str, Optional[str]]:
    llm_config = load_llm_config(args.llm_config)
    runtime_config = load_config(config_path=args.config, profile=args.profile)

    config_api_key = llm_config.get("openai_api_key")
    config_base_url = llm_config.get("openai_base_url")
    config_model = llm_config.get("openai_model")

    runtime_api_key = runtime_config.get("openai_api_key")
    runtime_base_url = runtime_config.get("openai_base_url")
    runtime_model = runtime_config.get("openai_model")

    env_api_key = os.getenv("OPENAI_API_KEY")
    env_base_url = os.getenv("OPENAI_BASE_URL")
    env_model = os.getenv("OPENAI_MODEL")

    api_key = pick_first_non_empty(
        args.openai_api_key, env_api_key, runtime_api_key, config_api_key
    )
    base_url = pick_first_non_empty(
        args.openai_base_url, env_base_url, runtime_base_url, config_base_url
    )
    model = pick_first_non_empty(
        args.model, env_model, runtime_model, config_model
    ) or "gpt-4o-mini"

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }


def find_direct_content_child(client: OVFSClient, uri: str, extensions: tuple[str, ...] = (".md",)) -> str | None:
    if not uri.endswith("/"):
        uri = uri.rstrip("/") + "/"
    try:
        children = client.ls(uri, recursive=False)
    except Exception:
        return None

    candidates: list[str] = []

    for child in children:
        child_uri: str | None = None
        child_is_dir: bool | None = None

        if isinstance(child, str):
            child_uri = child
        elif isinstance(child, dict):
            child_uri = child.get("uri") or child.get("path")
            if isinstance(child.get("isDir"), bool):
                child_is_dir = child["isDir"]

        if not child_uri or not isinstance(child_uri, str):
            continue

        name = PurePosixPath(child_uri).name

        if name == "abstract.md":
            continue

        if not name.endswith(extensions):
            continue

        if child_is_dir is None:
            child_stat = get_uri_stat(client, child_uri)
            child_is_dir = bool(child_stat and child_stat.get("isDir", False))

        if child_is_dir:
            continue

        candidates.append(child_uri)

    for candidate in candidates:
        if PurePosixPath(candidate).name.startswith("tmp"):
            return candidate

    return candidates[0] if candidates else None


def get_uri_stat(client: OVFSClient, uri: str) -> Dict[str, Any] | None:
    try:
        return client.stat(uri)
    except OVFSHTTPError as exc:
        message = str(exc).lower()
        if "404" in message or "not found" in message:
            return None
        raise


def resolve_canonical_markdown_uri(client: OVFSClient, uri: str) -> str | None:
    stat = get_uri_stat(client, uri)
    if not stat:
        return None

    if not stat.get("isDir", False):
        return uri

    direct_child = find_direct_content_child(client, uri, extensions=(".md",))
    if direct_child:
        return direct_child

    basename = PurePosixPath(uri.rstrip("/")).name
    if not basename:
        return None

    nested_uri = uri.rstrip("/") + f"/{basename}"
    nested_stat = get_uri_stat(client, nested_uri)
    if nested_stat and not nested_stat.get("isDir", False):
        return nested_uri

    try:
        children = client.ls(uri.rstrip("/") + "/", recursive=False)
    except Exception:
        children = []

    for child in children:
        child_uri: str | None = None
        child_is_dir: bool | None = None

        if isinstance(child, str):
            child_uri = child
        elif isinstance(child, dict):
            child_uri = child.get("uri") or child.get("path")
            if isinstance(child.get("isDir"), bool):
                child_is_dir = child["isDir"]

        if not child_uri or not isinstance(child_uri, str):
            continue
        if not child_uri.endswith(".md"):
            continue
        name = PurePosixPath(child_uri).name
        if name == "abstract.md":
            continue

        if child_is_dir is None:
            child_stat = get_uri_stat(client, child_uri)
            child_is_dir = bool(child_stat and child_stat.get("isDir", False))

        if not child_is_dir:
            return child_uri

    return None


def read_if_exists(client: OVFSClient, uri: str, default: str = "") -> str:
    read_uri = resolve_canonical_markdown_uri(client, uri)
    if not read_uri:
        return default
    return client.read_text(read_uri)


def extract_uri_from_ls_item(item: Any) -> str | None:
    if isinstance(item, str):
        return item

    if not isinstance(item, dict):
        return None

    for key in ("uri", "path", "name"):
        value = item.get(key)
        if isinstance(value, str) and value:
            if key == "name" and not value.startswith("viking://"):
                continue
            return value

    return None


def list_markdown_pages(client: OVFSClient, root_uri: str) -> List[str]:
    try:
        items = client.ls(root_uri, recursive=True)
    except Exception:
        return []

    uris: List[str] = []
    for item in items:
        uri = extract_uri_from_ls_item(item)
        if not uri:
            continue
        if not uri.startswith("viking://"):
            continue

        if isinstance(item, dict) and isinstance(item.get("isDir"), bool):
            is_dir = item["isDir"]
        else:
            stat = get_uri_stat(client, uri)
            is_dir = bool(stat and stat.get("isDir", False))

        if is_dir:
            continue
        if uri.endswith(".md"):
            uris.append(uri)

    seen: Set[str] = set()
    deduped: List[str] = []
    for uri in uris:
        if uri not in seen:
            seen.add(uri)
            deduped.append(uri)

    return deduped


def normalize_relative_wiki_target(target: str) -> str | None:
    target = target.strip()
    if not target:
        return None

    lowered = target.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return None
    if target.startswith("#"):
        return None

    target = target.split("#", 1)[0].split("?", 1)[0].strip()
    if not target:
        return None

    if target.startswith("wiki/"):
        target = target[len("wiki/"):]

    if target.endswith("/"):
        return None

    raw_parts = [p for p in target.split("/") if p and p != "."]
    parts = []
    for part in raw_parts:
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)

    if not parts:
        return None

    normalized = "/".join(parts)
    if not normalized.endswith(".md"):
        normalized = f"{normalized}.md"

    return normalized


def extract_index_links(index_text: str) -> Set[str]:
    results: Set[str] = set()

    wikilink_pattern = re.compile(r"\[\[([^\]]+)\]\]")
    markdown_link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

    for raw in wikilink_pattern.findall(index_text):
        normalized = normalize_relative_wiki_target(raw)
        if normalized:
            results.add(normalized)

    for raw in markdown_link_pattern.findall(index_text):
        normalized = normalize_relative_wiki_target(raw)
        if normalized:
            results.add(normalized)

    return results


def tokenize(text: str) -> Set[str]:
    lowered_text = text.lower()

    english_tokens = set(re.findall(r"[a-z0-9_]+", lowered_text))
    english_tokens = {t for t in english_tokens if len(t) >= 2 and t not in STOPWORDS}

    chinese_chunks = re.findall(r"[\u4e00-\u9fff]+", text)
    chinese_tokens: Set[str] = set()
    for chunk in chinese_chunks:
        normalized_chunk = chunk.strip()
        if len(normalized_chunk) >= 2 and normalized_chunk not in ZH_STOPWORDS:
            chinese_tokens.add(normalized_chunk)

        for i in range(len(normalized_chunk) - 1):
            bigram = normalized_chunk[i : i + 2]
            if bigram not in ZH_STOPWORDS:
                chinese_tokens.add(bigram)

    return english_tokens | chinese_tokens


def score_page(question_terms: Set[str], uri: str, text: str) -> int:
    haystack = f"{uri}\n{text}".lower()
    score = 0
    for term in question_terms:
        if term in haystack:
            score += 1

    if "/wiki/sources/" in uri:
        score += 2

    return score


def build_candidate_pages(client: OVFSClient, kb_root: str) -> List[str]:
    index_text = read_if_exists(client, kb_root + "wiki/index.md", INDEX_TITLE + "\n")
    linked_targets = sorted(extract_index_links(index_text))

    candidates: List[str] = []
    for rel in linked_targets:
        uri = kb_root + "wiki/" + rel
        canonical = resolve_canonical_markdown_uri(client, uri)
        if canonical:
            candidates.append(canonical)

    all_pages = list_markdown_pages(client, kb_root + "wiki/")
    if candidates:
        candidates.extend(all_pages)
    else:
        candidates = all_pages

    seen: Set[str] = set()
    deduped: List[str] = []
    for uri in candidates:
        if uri not in seen:
            seen.add(uri)
            deduped.append(uri)
    return deduped


def select_relevant_pages(
    client: OVFSClient,
    kb_root: str,
    question: str,
    top_k: int,
) -> List[Dict[str, str]]:
    question_terms = tokenize(question)
    candidate_uris = build_candidate_pages(client, kb_root)

    scored: List[Tuple[int, str, str]] = []
    for uri in candidate_uris:
        try:
            text = client.read_text(uri)
        except Exception:
            continue
        score = score_page(question_terms, uri, text)
        scored.append((score, uri, text))

    scored.sort(key=lambda x: (-x[0], x[1]))

    selected: List[Dict[str, str]] = []
    for score, uri, text in scored[:top_k]:
        selected.append(
            {
                "uri": uri,
                "score": str(score),
                "content": text,
            }
        )

    return selected


def build_llm_prompt(
    schema_text: str,
    question: str,
    overview_text: str,
    selected_pages: List[Dict[str, str]],
) -> str:
    page_blocks = []
    for i, page in enumerate(selected_pages, start=1):
        page_blocks.append(
            f"""
--- PAGE {i} START ---
URI: {page["uri"]}
CONTENT:
{page["content"]}
--- PAGE {i} END ---
""".strip()
        )

    joined_pages = "\n\n".join(page_blocks)

    return f"""
你将基于远端 OpenViking 支持的 llm-wiki 知识库回答用户问题。

请参考以下 schema 上下文：

--- SCHEMA START ---
{schema_text}
--- SCHEMA END ---

用户问题：
{question}

当前 wiki/overview.md：
--- OVERVIEW START ---
{overview_text}
--- OVERVIEW END ---

相关 wiki 页面：
{joined_pages}

仅返回合法 JSON，且严格使用以下结构（JSON key 必须保持英文）：

{{
  "answer_markdown": "full markdown answer grounded in the wiki",
  "used_pages": ["uri1", "uri2"],
  "synthesis_title": "short title for optional saved synthesis"
}}

规则（硬约束）：
- 默认用简体中文回答。
- 只能基于提供的 wiki 上下文作答。
- 上下文不足，用中文说明缺失了什么。
- 回答尽量简洁但要有信息量。
- 在回答中自然提及关键页面或概念。
- 不要输出代码块围栏。
- 不要在 JSON 之外输出任何额外说明。
""".strip()


def extract_json_block(text: str) -> str:
    stripped = text.strip()

    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output")

    return stripped[start : end + 1]


def call_llm(
    prompt: str,
    *,
    api_key: Optional[str],
    base_url: Optional[str],
    model: Optional[str],
) -> Dict[str, Any]:
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    final_model = model or "gpt-4o-mini"

    client = OpenAI(
        api_key=api_key,
        base_url=base_url if base_url else None,
    )

    response = client.chat.completions.create(
        model=final_model,
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": "你是严谨的知识库问答助手。默认使用简体中文作答，若上下文不足要明确说明缺失信息。只输出合法 JSON，JSON key 保持英文。",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    content = response.choices[0].message.content or ""
    json_text = extract_json_block(content)
    parsed = json.loads(json_text)

    if not isinstance(parsed, dict):
        raise ValueError("Model output JSON is not an object")

    return parsed


def ensure_section(index_text: str, heading: str) -> str:
    if heading in index_text:
        return index_text

    text = index_text.rstrip()
    if text:
        text += "\n\n"
    text += f"{heading}\n"
    return text + "\n"


def get_section_heading_by_key(index_text: str, section_key: str) -> tuple[str, str]:
    canonical_heading = INDEX_SECTIONS[section_key]
    if canonical_heading in index_text:
        return canonical_heading, canonical_heading

    for legacy_heading in LEGACY_INDEX_SECTIONS.get(section_key, []):
        if legacy_heading in index_text:
            return legacy_heading, canonical_heading

    return canonical_heading, canonical_heading


def append_unique_bullet(index_text: str, section_key: str, bullet: str) -> str:
    heading, _ = get_section_heading_by_key(index_text, section_key)
    index_text = ensure_section(index_text, heading)

    if bullet in index_text:
        return index_text

    pattern = re.compile(rf"(^{re.escape(heading)}\s*$)", re.MULTILINE)
    match = pattern.search(index_text)
    if not match:
        return index_text.rstrip() + f"\n\n{heading}\n{bullet}\n"

    insert_pos = match.end()
    return index_text[:insert_pos] + "\n" + bullet + index_text[insert_pos:]


def append_log_entry(log_text: str, entry: str) -> str:
    entry = entry.strip()
    if not entry:
        return log_text

    stamp = now_iso()
    line = f"- {stamp} - {entry}"
    if line in log_text:
        return log_text
    return log_text.rstrip() + "\n" + line + "\n"


def resolve_write_target_uri(client: OVFSClient, uri: str) -> tuple[str, bool]:
    stat = get_uri_stat(client, uri)
    if not stat:
        return uri, True

    if not stat.get("isDir", False):
        return uri, False

    content_child = find_direct_content_child(client, uri, extensions=(".md",))
    if content_child:
        return content_child, False

    return uri, True


def write_page(client: OVFSClient, uri: str, markdown: str) -> None:
    target_uri, should_create = resolve_write_target_uri(client, uri)

    if should_create:
        if hasattr(client, "add_local_resource"):
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fp:
                fp.write(markdown)
                local_file_path = fp.name
            try:
                client.add_local_resource(
                    file_path=local_file_path,
                    to=target_uri,
                    reason="wiki query create synthesis",
                    wait=False,
                )
            finally:
                try:
                    os.unlink(local_file_path)
                except OSError:
                    pass
            return

        client.write_text(target_uri, markdown, create=True, wait=False)
        return

    client.write_text(target_uri, markdown, create=False, wait=False)


def render_synthesis_markdown(
    title: str,
    question: str,
    answer_markdown: str,
    used_pages: List[str],
) -> str:
    used_section = "\n".join(f"- {uri}" for uri in used_pages) if used_pages else "- 无"

    return f"""# {title}

## 问题

{question}

## 回答

{answer_markdown}

## 使用的页面

{used_section}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query a remote OpenViking-backed wiki knowledge base.")
    parser.add_argument("--kb-name", required=True, help="Knowledge base name under viking://resources/")
    parser.add_argument("--question", required=True, help="Natural-language question")
    parser.add_argument("--top-k", type=int, default=6, help="Number of candidate pages to pass to the LLM")
    parser.add_argument("--save", action="store_true", help="Save answer to wiki/syntheses/")
    parser.add_argument("--slug", default=None, help="Optional synthesis slug when --save is used")
    parser.add_argument("--model", default=None, help="Override model name")
    parser.add_argument("--openai-api-key", default=None, help="Override OpenAI API key")
    parser.add_argument("--openai-base-url", default=None, help="Override OpenAI base URL")
    parser.add_argument(
        "--llm-config",
        default=str(DEFAULT_LLM_CONFIG_PATH),
        help="Path to LLM config JSON (default: project config/llm-wiki-config.json)",
    )
    parser.add_argument("--config", default=None, help="Path to config JSON")
    parser.add_argument("--profile", default=None, help="Profile name")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print result JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kb_root = build_kb_root(args.kb_name)
    schema_text = read_local_schema()
    config = OVFSConfig.load(config_path=args.config, profile=args.profile)
    openai_settings = resolve_openai_settings(args)

    try:
        with OVFSClient(config) as client:
            overview_text = read_if_exists(client, kb_root + "wiki/overview.md", OVERVIEW_TITLE + "\n")
            index_text = read_if_exists(client, kb_root + "wiki/index.md", INDEX_TITLE + "\n")
            log_text = read_if_exists(client, kb_root + "wiki/log.md", LOG_TITLE + "\n")

            selected_pages = select_relevant_pages(
                client=client,
                kb_root=kb_root,
                question=args.question,
                top_k=args.top_k,
            )

            prompt = build_llm_prompt(
                schema_text=schema_text,
                question=args.question,
                overview_text=overview_text,
                selected_pages=selected_pages,
            )

            llm_result = call_llm(
                prompt,
                api_key=openai_settings["api_key"],
                base_url=openai_settings["base_url"],
                model=openai_settings["model"],
            )

            answer_markdown = str(llm_result.get("answer_markdown", "")).strip()
            used_pages = llm_result.get("used_pages", [])
            synthesis_title = str(llm_result.get("synthesis_title", "")).strip() or args.question

            if not answer_markdown:
                raise RuntimeError("LLM did not return answer_markdown")

            normalized_used_pages: List[str] = []
            if isinstance(used_pages, list):
                for item in used_pages:
                    if isinstance(item, str) and item.strip():
                        normalized_used_pages.append(item.strip())

            result: Dict[str, Any] = {
                "status": "ok",
                "kb_root": kb_root,
                "question": args.question,
                "selected_pages": [p["uri"] for p in selected_pages],
                "used_pages": normalized_used_pages,
                "answer_markdown": answer_markdown,
                "saved": False,
            }

            if args.save:
                synthesis_target = build_synthesis_target(args.slug, args.question)
                synthesis_slug = PurePosixPath(synthesis_target).stem
                synthesis_uri = kb_root + synthesis_target
                synthesis_markdown = render_synthesis_markdown(
                    title=synthesis_title,
                    question=args.question,
                    answer_markdown=answer_markdown,
                    used_pages=normalized_used_pages,
                )

                write_page(client, synthesis_uri, synthesis_markdown)

                bullet = f"- [[syntheses/{synthesis_slug}.md]] - {synthesis_title}"
                new_index_text = append_unique_bullet(index_text, "syntheses", bullet)
                new_log_text = append_log_entry(
                    log_text,
                    f"已保存综合结论 {synthesis_slug} 到 wiki/syntheses/{synthesis_slug}.md",
                )

                write_page(client, kb_root + "wiki/index.md", new_index_text)
                write_page(client, kb_root + "wiki/log.md", new_log_text)

                result["saved"] = True
                result["synthesis_uri"] = synthesis_uri
                result["synthesis_slug"] = synthesis_slug

            if args.pretty:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(json.dumps(result, ensure_ascii=False))

            return 0

    except Exception as exc:
        error_result = {
            "status": "error",
            "kb_root": kb_root,
            "question": args.question,
            "error": str(exc),
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
