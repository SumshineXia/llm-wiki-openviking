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
from common import build_error_result, build_kb_root, load_config, print_json
from wiki_index import rebuild_index_text


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

INDEX_SECTION_HEADINGS = {
    *INDEX_SECTIONS.values(),
    *[heading for headings in LEGACY_INDEX_SECTIONS.values() for heading in headings],
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

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_json_text(data: dict[str, Any], *, pretty: bool) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2 if pretty else None) + "\n"


def write_temp_json_file(data: dict[str, Any], *, pretty: bool) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    with tempfile.NamedTemporaryFile(
        "w",
        prefix=f"wiki-query-save-{stamp}-",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    ) as fp:
        fp.write(format_json_text(data, pretty=pretty))
        return Path(fp.name)


def write_json_file(path: Path, data: dict[str, Any], *, pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_json_text(data, pretty=pretty), encoding="utf-8")


def slugify(text: str) -> str:
    normalized = text.strip().lower()
    tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", normalized)
    if not tokens:
        return "untitled"
    return "-".join(tokens)


BANNED_TITLE_PREFIXES = re.compile(
    r"^(?:"
    r"关于(?:的|之)?|"
    r"这份文档(?:的|是)?|"
    r"这个文档(?:的|是)?|"
    r"该文档(?:的|是)?|"
    r"本文档(?:的|是)?|"
    r"此文档(?:的|是)?|"
    r"这个问题(?:的|是)?"
    r")\s*"
)
BANNED_FULL_TITLES = {
    "相关内容",
    "相关文档",
    "相关信息",
    "综合结论",
    "回答内容",
    "问答内容",
    "问题回答",
}


def normalize_synthesis_title(title: str, fallback: str = "综合结论", max_chars: int = 15) -> str:
    text = title.strip()
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"[*_~`]", "", text)
    text = BANNED_TITLE_PREFIXES.sub("", text)
    text = re.sub(r"^[的是]\s*", "", text)
    text = text.strip("。，、；：？！,. ;:!?\n")
    if text.strip().lower() in BANNED_FULL_TITLES or not text.strip():
        return fallback
    if len(text) > max_chars:
        text = text[:max_chars].rstrip("，,。；、:： ")
    return text.strip() or fallback


def expected_content_child_uri(uri: str) -> str:
    normalized = uri.rstrip("/")
    basename = PurePosixPath(normalized).name
    return f"{normalized}/{basename}"


def build_synthesis_target(slug: str | None, synthesis_title: str) -> str:
    if slug and slug.strip():
        return f"wiki/syntheses/{slugify(slug)}.md"

    normalized_title = normalize_synthesis_title(synthesis_title)
    stem = slugify(normalized_title)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if stem:
        stem = stem[:48].strip("-")
        return f"wiki/syntheses/{stem}-{timestamp}.md"

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

    parent_name = PurePosixPath(uri.rstrip("/")).name

    for candidate in candidates:
        if PurePosixPath(candidate).name == parent_name:
            return candidate

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


def extract_index_entries(index_text: str) -> Set[str]:
    results: Set[str] = set()
    current_heading: str | None = None

    wikilink_pattern = re.compile(r"\[\[([^\]]+)\]\]")
    markdown_link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

    for line in index_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current_heading = stripped
            continue

        if current_heading not in INDEX_SECTION_HEADINGS:
            continue

        for raw in wikilink_pattern.findall(line):
            target = raw.split("|", 1)[0].strip()
            normalized = normalize_relative_wiki_target(target)
            if normalized:
                results.add(normalized)

        for raw in markdown_link_pattern.findall(line):
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
) -> tuple[List[Dict[str, str]], Dict[str, Any]]:
    question_terms = tokenize(question)

    index_text = read_if_exists(client, kb_root + "wiki/index.md", INDEX_TITLE + "\n")
    index_entries = sorted(extract_index_entries(index_text))

    page_char_limit = int(getattr(select_relevant_pages, "max_page_chars", 20000))
    candidate_multiplier = int(getattr(select_relevant_pages, "candidate_multiplier", 3))
    retrieval_mode = str(getattr(select_relevant_pages, "retrieval_mode", "auto"))

    indexed_candidates: List[str] = []
    for rel in index_entries:
        uri = kb_root + "wiki/" + rel
        canonical = resolve_canonical_markdown_uri(client, uri)
        if canonical:
            indexed_candidates.append(canonical)

    seen_candidates: Set[str] = set()
    deduped_indexed_candidates: List[str] = []
    for uri in indexed_candidates:
        if uri not in seen_candidates:
            seen_candidates.add(uri)
            deduped_indexed_candidates.append(uri)

    candidate_count = max(top_k * candidate_multiplier, top_k)
    scan_fallback_used = False

    if retrieval_mode == "scan":
        candidate_uris = list_markdown_pages(client, kb_root + "wiki/")[:candidate_count]
    else:
        candidate_uris = deduped_indexed_candidates[:candidate_count]
        if retrieval_mode == "auto" and (not index_entries or len(candidate_uris) < min(top_k, 2)):
            scan_fallback_used = True
            candidate_uris = list_markdown_pages(client, kb_root + "wiki/")[:candidate_count]

    scored: List[Tuple[int, str, str]] = []
    content_limit_hit_count = 0
    for uri in candidate_uris:
        try:
            text = client.read_text(uri)
        except Exception:
            continue
        if len(text) > page_char_limit:
            text = text[:page_char_limit]
            content_limit_hit_count += 1
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

    debug = {
        "retrieval_mode": retrieval_mode,
        "index_entry_count": len(index_entries),
        "candidate_count": len(candidate_uris),
        "read_page_count": len(scored),
        "content_limit_hit_count": content_limit_hit_count,
        "fallback_scan_used": scan_fallback_used,
        "max_page_chars": page_char_limit,
    }
    return selected, debug


def build_llm_prompt(
    schema_text: str,
    question: str,
    overview_text: str,
    selected_pages: List[Dict[str, str]],
) -> str:
    overview_limit = int(getattr(build_llm_prompt, "max_overview_chars", 12000))
    overview_note = ""
    clipped_overview = overview_text
    if len(overview_text) > overview_limit:
        clipped_overview = overview_text[:overview_limit]
        overview_note = f"\n[overview truncated to {overview_limit} chars]"

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
{clipped_overview}{overview_note}
--- OVERVIEW END ---

相关 wiki 页面：
{joined_pages}

仅返回合法 JSON，且严格使用以下结构（JSON key 必须保持英文）：

{{
  "answer_markdown": "full markdown answer grounded in the wiki",
  "used_pages": ["uri1", "uri2"],
   "synthesis_title": "15字以内中文标题，必须根据 answer_markdown 的核心内容总结，不要复述用户问题。不要把疑问句改成陈述句。不要使用'这份文档''这个问题''关于'等空泛标题。适合作为文件名和 wiki 标题。"
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


def upsert_index_link_bullet(index_text: str, section_key: str, link_path: str, title: str) -> str:
    heading, _ = get_section_heading_by_key(index_text, section_key)
    text = ensure_section(index_text, heading)
    bullet = f"- [[{link_path}]] - {title}"
    pattern = re.compile(rf"^-\s*\[\[{re.escape(link_path)}\]\]\s*-\s*.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(bullet, text, count=1)
    return append_unique_bullet(text, section_key, bullet)


def build_overview_note(link_path: str, title: str) -> str:
    return f"- [[{link_path}]] - {title}"


def upsert_overview_synthesis_block(overview_text: str, link_path: str, note: str) -> str:
    start_tag = f"<!-- synthesis:{link_path}:start -->"
    end_tag = f"<!-- synthesis:{link_path}:end -->"
    block = f"{start_tag}\n{note}\n{end_tag}"
    pattern = re.compile(
        rf"{re.escape(start_tag)}\\n.*?\\n{re.escape(end_tag)}",
        re.DOTALL,
    )
    if pattern.search(overview_text):
        return pattern.sub(block, overview_text, count=1)
    return overview_text.rstrip() + "\n\n" + block + "\n"


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

    same_name_child = expected_content_child_uri(uri)
    same_name_stat = get_uri_stat(client, same_name_child)
    if same_name_stat and not same_name_stat.get("isDir", False):
        return same_name_child, False

    content_child = find_direct_content_child(client, uri, extensions=(".md",))
    if content_child:
        return content_child, False

    return same_name_child, True


def write_page(client: OVFSClient, uri: str, markdown: str) -> None:
    target_uri, should_create = resolve_write_target_uri(client, uri)
    client.write_text(target_uri, markdown, create=should_create, wait=True)


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


def build_save_payload(
    *,
    kb_name: str,
    kb_root: str,
    question: str,
    answer_markdown: str,
    synthesis_title: str,
    used_pages: list[str],
    selected_pages: list[str],
    created_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "wiki-query",
        "kb_name": kb_name,
        "kb_root": kb_root,
        "question": question,
        "answer_markdown": answer_markdown,
        "synthesis_title": synthesis_title,
        "used_pages": used_pages,
        "selected_pages": selected_pages,
        "created_at": created_at,
    }


def parse_args() -> argparse.Namespace:
    def positive_int(value: str) -> int:
        parsed = int(value)
        if parsed <= 0:
            raise argparse.ArgumentTypeError("must be a positive integer")
        return parsed

    parser = argparse.ArgumentParser(description="Query a remote OpenViking-backed wiki knowledge base.")
    parser.add_argument("--kb-name", required=True, help="Knowledge base name under viking://resources/")
    parser.add_argument("--question", required=True, help="Natural-language question")
    parser.add_argument("--top-k", type=positive_int, default=6, help="Number of candidate pages to pass to the LLM")
    parser.add_argument("--retrieval-mode", choices=["index", "scan", "auto"], default="auto", help="Page retrieval mode")
    parser.add_argument("--candidate-multiplier", type=positive_int, default=3, help="Candidate page multiplier for second-stage rerank")
    parser.add_argument("--max-page-chars", type=positive_int, default=20000, help="Max chars read per candidate page")
    parser.add_argument("--max-overview-chars", type=positive_int, default=12000, help="Max chars used from overview prompt context")
    parser.add_argument("--save", action="store_true", help="Legacy mode: re-query and save answer to wiki/syntheses/")
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
    payload_group = parser.add_mutually_exclusive_group()
    payload_group.add_argument("--save-payload-file", default=None, help="Write wiki-save payload JSON to this path")
    payload_group.add_argument("--no-save-payload-file", action="store_true", help="Do not write automatic save payload file")
    parser.add_argument("--output-file", default=None, help="Write full query result JSON to this path")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print result JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kb_root = ""

    try:
        kb_root = build_kb_root(args.kb_name)
        schema_text = read_local_schema()
        config = OVFSConfig.load(config_path=args.config, profile=args.profile)
        openai_settings = resolve_openai_settings(args)

        with OVFSClient(config) as client:
            overview_text = read_if_exists(client, kb_root + "wiki/overview.md", OVERVIEW_TITLE + "\n")
            index_text = read_if_exists(client, kb_root + "wiki/index.md", INDEX_TITLE + "\n")
            log_text = read_if_exists(client, kb_root + "wiki/log.md", LOG_TITLE + "\n")

            select_relevant_pages.retrieval_mode = args.retrieval_mode
            select_relevant_pages.candidate_multiplier = args.candidate_multiplier
            select_relevant_pages.max_page_chars = args.max_page_chars
            build_llm_prompt.max_overview_chars = args.max_overview_chars

            selection_result = select_relevant_pages(
                client=client,
                kb_root=kb_root,
                question=args.question,
                top_k=args.top_k,
            )
            if isinstance(selection_result, tuple):
                selected_pages, retrieval_debug = selection_result
            else:
                selected_pages = selection_result
                retrieval_debug = {
                    "retrieval_mode": args.retrieval_mode,
                    "index_entry_count": 0,
                    "candidate_count": len(selected_pages),
                    "read_page_count": len(selected_pages),
                    "content_limit_hit_count": 0,
                    "fallback_scan_used": False,
                    "max_page_chars": args.max_page_chars,
                }

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
            raw_synthesis_title = str(llm_result.get("synthesis_title", "")).strip()
            synthesis_title = normalize_synthesis_title(raw_synthesis_title, fallback="综合结论")

            if not answer_markdown:
                raise RuntimeError("LLM did not return answer_markdown")

            normalized_used_pages: List[str] = []
            if isinstance(used_pages, list):
                for item in used_pages:
                    if isinstance(item, str) and item.strip():
                        normalized_used_pages.append(item.strip())

            result: Dict[str, Any] = {
                "status": "ok",
                "kb_name": args.kb_name,
                "kb_root": kb_root,
                "question": args.question,
                "selected_pages": [p["uri"] for p in selected_pages],
                "used_pages": normalized_used_pages,
                "answer_markdown": answer_markdown,
                "synthesis_title": synthesis_title,
                "recommended_save_skill": "wiki-save",
                "save_payload": {},
                "save_payload_path": None,
                "saved": False,
                "retrieval_mode": retrieval_debug["retrieval_mode"],
                "index_entry_count": retrieval_debug["index_entry_count"],
                "candidate_count": retrieval_debug["candidate_count"],
                "read_page_count": retrieval_debug["read_page_count"],
                "content_limit_hit_count": retrieval_debug["content_limit_hit_count"],
                "fallback_scan_used": retrieval_debug["fallback_scan_used"],
                "max_page_chars": retrieval_debug["max_page_chars"],
                "max_overview_chars": args.max_overview_chars,
            }

            created_at = now_iso()
            selected_page_uris = [p["uri"] for p in selected_pages]
            save_payload = build_save_payload(
                kb_name=args.kb_name,
                kb_root=kb_root,
                question=args.question,
                answer_markdown=answer_markdown,
                synthesis_title=synthesis_title,
                used_pages=normalized_used_pages,
                selected_pages=selected_page_uris,
                created_at=created_at,
            )
            result["save_payload"] = save_payload

            if not args.no_save_payload_file:
                if args.save_payload_file:
                    explicit_payload_path = Path(args.save_payload_file).expanduser()
                    write_json_file(explicit_payload_path, save_payload, pretty=True)
                    result["save_payload_path"] = str(explicit_payload_path)
                else:
                    try:
                        auto_payload_path = write_temp_json_file(save_payload, pretty=True)
                        result["save_payload_path"] = str(auto_payload_path)
                    except Exception as exc:
                        result["save_payload_write_error"] = str(exc)

            if args.save:
                synthesis_target = build_synthesis_target(args.slug, synthesis_title)
                synthesis_slug = PurePosixPath(synthesis_target).stem
                synthesis_uri = kb_root + synthesis_target
                synthesis_markdown = render_synthesis_markdown(
                    title=synthesis_title,
                    question=args.question,
                    answer_markdown=answer_markdown,
                    used_pages=normalized_used_pages,
                )

                resolved_synthesis_uri, should_create = resolve_write_target_uri(client, synthesis_uri)
                client.write_text(resolved_synthesis_uri, synthesis_markdown, create=should_create, wait=True)

                link_path = f"syntheses/{synthesis_slug}.md"
                overview_note = build_overview_note(link_path, synthesis_title)
                touched_entries = {
                    "syntheses": {
                        link_path: synthesis_title,
                    },
                }
                new_index_text = rebuild_index_text(
                    client,
                    kb_root,
                    index_text,
                    touched_entries=touched_entries,
                )
                new_overview_text = upsert_overview_synthesis_block(overview_text, link_path, overview_note)
                new_log_text = append_log_entry(
                    log_text,
                    f"已保存综合结论 {synthesis_slug} 到 wiki/syntheses/{synthesis_slug}.md",
                )

                write_page(client, kb_root + "wiki/index.md", new_index_text)
                if new_overview_text != overview_text:
                    write_page(client, kb_root + "wiki/overview.md", new_overview_text)
                write_page(client, kb_root + "wiki/log.md", new_log_text)

                result["saved"] = True
                result["synthesis_uri"] = resolved_synthesis_uri
                result["synthesis_slug"] = synthesis_slug
                result["save_deprecated"] = True
                result["legacy_save_requeries"] = True
                result["created"] = should_create
                result["updated"] = not should_create
                result["overview_updated"] = new_overview_text != overview_text
                result["index_update_mode"] = "rebuild"
                result["touched_index_entries"] = touched_entries

            if args.output_file:
                output_path = Path(args.output_file).expanduser()
                write_json_file(output_path, result, pretty=args.pretty)

            print_json(result, pretty=args.pretty)
            return 0

    except Exception as exc:
        print_json(build_error_result(exc, kb_root=kb_root), pretty=args.pretty)
        return 1


if __name__ == "__main__":
    sys.exit(main())
