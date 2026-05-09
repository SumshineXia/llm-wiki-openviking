from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ovfs import OVFSClient, OVFSConfig, OVFSError, OVFSHTTPError
from common import build_kb_root, load_config


DEFAULT_LLM_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "llm-wiki-config.json"
)

LEGACY_LLM_CONFIG_PATHS = [
    Path(__file__).resolve().parent.parent / "config" / "wiki_ingest.conf.json",
    Path(__file__).resolve().parent.parent / "config" / "wiki_query.conf.json",
]

INDEX_TITLE = "# 索引"
OVERVIEW_TITLE = "# 概览"
LOG_TITLE = "# 操作日志"

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


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-") or "untitled"


def basename_without_ext(uri: str) -> str:
    name = PurePosixPath(uri.rstrip("/")).name
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name


def get_schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "wiki_schema.md"


def read_local_schema() -> str:
    return get_schema_path().read_text(encoding="utf-8")


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


def read_if_exists(client: OVFSClient, uri: str, default: str = "") -> str:
    read_uri = resolve_canonical_markdown_uri(client, uri)
    if not read_uri:
        return default
    return client.read_text(read_uri)


def get_uri_stat(client: OVFSClient, uri: str) -> Dict[str, Any] | None:
    try:
        return client.stat(uri)
    except OVFSHTTPError as exc:
        message = str(exc).lower()
        if "404" in message or "not found" in message:
            return None
        raise


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


def list_markdown_pages(client: OVFSClient, root_uri: str) -> List[str]:
    try:
        items = client.ls(root_uri, recursive=True)
    except Exception:
        return []

    uris: List[str] = []
    for item in items:
        if isinstance(item, str):
            uri = item
            is_dir = False
        elif isinstance(item, dict):
            uri = item.get("uri") or item.get("path")
            is_dir = bool(item.get("isDir", False))
        else:
            continue

        if not uri or not isinstance(uri, str):
            continue
        if not uri.startswith("viking://"):
            continue
        if is_dir:
            continue
        if uri.endswith(".md"):
            uris.append(uri)

    seen = set()
    deduped = []
    for uri in uris:
        if uri not in seen:
            seen.add(uri)
            deduped.append(uri)
    return deduped


def build_context_snapshot(client: OVFSClient, kb_root: str) -> Dict[str, Any]:
    index_text = read_if_exists(client, kb_root + "wiki/index.md", INDEX_TITLE + "\n")
    overview_text = read_if_exists(client, kb_root + "wiki/overview.md", OVERVIEW_TITLE + "\n")
    log_text = read_if_exists(client, kb_root + "wiki/log.md", LOG_TITLE + "\n")

    entity_pages = list_markdown_pages(client, kb_root + "wiki/entities/")
    concept_pages = list_markdown_pages(client, kb_root + "wiki/concepts/")
    source_pages = list_markdown_pages(client, kb_root + "wiki/sources/")

    return {
        "index_text": index_text,
        "overview_text": overview_text,
        "log_text": log_text,
        "entity_pages": entity_pages,
        "concept_pages": concept_pages,
        "source_pages": source_pages,
    }


def build_llm_prompt(
    schema_text: str,
    source_uri: str,
    source_text: str,
    context: Dict[str, Any],
    source_slug: str,
) -> str:
    entity_page_names = [PurePosixPath(uri).name for uri in context["entity_pages"]][:100]
    concept_page_names = [PurePosixPath(uri).name for uri in context["concept_pages"]][:100]

    return f"""
你正在为基于远端 OpenViking 的 llm-wiki 知识库生成 wiki 内容。

请严格遵循以下 schema：

--- SCHEMA START ---
{schema_text}
--- SCHEMA END ---

当前 source URI：
{source_uri}

建议使用的 source slug：
{source_slug}

当前 wiki/index.md：
--- INDEX START ---
{context["index_text"]}
--- INDEX END ---

当前 wiki/overview.md：
--- OVERVIEW START ---
{context["overview_text"]}
--- OVERVIEW END ---

已存在的实体页文件名：
{json.dumps(entity_page_names, ensure_ascii=False)}

已存在的概念页文件名：
{json.dumps(concept_page_names, ensure_ascii=False)}

原始 source 文本：
--- SOURCE START ---
{source_text}
--- SOURCE END ---

仅返回合法 JSON，且必须严格匹配以下结构：

{{
  "source_title": "string",
  "source_page_markdown": "source 页面完整 markdown 内容",
  "entity_pages": [
    {{
      "slug": "kebab-case-slug",
      "title": "string",
      "markdown": "完整 markdown 内容"
    }}
  ],
  "concept_pages": [
    {{
      "slug": "kebab-case-slug",
      "title": "string",
      "markdown": "完整 markdown 内容"
    }}
  ],
  "overview_note": "追加到 overview 的 1-2 段 markdown 摘要",
  "log_note": "一行简短日志内容"
}}

规则：
- 所有自然语言内容必须使用简体中文。
- 标题必须使用简体中文。
- 正文必须使用简体中文。
- 原始资料为英文时，不直接生成英文 wiki 页面，应提炼为中文内容。
- 必要技术术语、代码名、API名、路径、命令、库名可保留英文。
- JSON 字段名必须保持英文。
- slug 必须稳定，且使用小写 kebab-case。
- 优先只创建必要的 entity/concept 页面。
- 在合适位置使用 [[wikilinks]] 进行链接。
- 不要包含代码块围栏。
- 不要在 JSON 之外返回任何额外说明。
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
                "content": "你是一个严谨的知识库构建助手。你必须只输出合法 JSON，不要输出任何额外文本。",
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


def sanitize_pages(items: Any, kind: str) -> List[Dict[str, str]]:
    if not isinstance(items, list):
        return []

    cleaned: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = slugify(str(item.get("slug", "")).strip())
        title = str(item.get("title", "")).strip()
        markdown = str(item.get("markdown", "")).strip()

        if not slug or not title or not markdown:
            continue

        cleaned.append(
            {
                "slug": slug,
                "title": title,
                "markdown": markdown,
                "kind": kind,
            }
        )
    return cleaned


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
        # fallback append
        return index_text.rstrip() + f"\n\n{heading}\n{bullet}\n"

    insert_pos = match.end()
    return index_text[:insert_pos] + "\n" + bullet + index_text[insert_pos:]


def update_index_text(
    index_text: str,
    source_slug: str,
    source_title: str,
    entity_pages: List[Dict[str, str]],
    concept_pages: List[Dict[str, str]],
) -> str:
    updated = index_text

    for section_key in ("sources", "entities", "concepts", "syntheses"):
        heading, _ = get_section_heading_by_key(updated, section_key)
        updated = ensure_section(updated, heading)

    source_bullet = f"- [[sources/{source_slug}.md]] - {source_title}"
    updated = append_unique_bullet(updated, "sources", source_bullet)

    for page in entity_pages:
        bullet = f"- [[entities/{page['slug']}.md]] - {page['title']}"
        updated = append_unique_bullet(updated, "entities", bullet)

    for page in concept_pages:
        bullet = f"- [[concepts/{page['slug']}.md]] - {page['title']}"
        updated = append_unique_bullet(updated, "concepts", bullet)

    return updated


def append_overview_note(overview_text: str, note: str, source_title: str) -> str:
    note = note.strip()
    if not note:
        return overview_text

    section_heading = "## 最近更新"
    if section_heading not in overview_text:
        overview_text = overview_text.rstrip() + f"\n\n{section_heading}\n"

    existing_block_pattern = re.compile(
        rf"^###\s+{re.escape(source_title)}\s+\([^\n]+\)\n\n{re.escape(note)}\n$",
        re.MULTILINE,
    )
    if existing_block_pattern.search(overview_text):
        return overview_text

    stamp = now_iso()
    block = f"\n### {source_title} ({stamp})\n\n{note}\n"
    return overview_text.rstrip() + block + "\n"


def append_log_entry(log_text: str, entry: str) -> str:
    entry = entry.strip()
    if not entry:
        return log_text

    stamp = now_iso()
    line = f"- {stamp} - {entry}"
    if line in log_text:
        return log_text
    return log_text.rstrip() + "\n" + line + "\n"


def write_page(client: OVFSClient, uri: str, markdown: str) -> None:
    target_uri, should_create = resolve_write_target_uri(client, uri)
    if should_create:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fp:
            fp.write(markdown)
            local_file_path = fp.name

        client.add_local_resource(
            file_path=local_file_path,
            to=target_uri,
            reason="wiki ingest create page",
            wait=False,
        )
        return

    client.write_text(target_uri, markdown, create=False, wait=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest a remote raw source into an OpenViking-backed wiki.")
    parser.add_argument("--kb-name", required=True, help="Knowledge base name under viking://resources/")
    parser.add_argument("--source-uri", required=True, help="Full raw source URI, e.g. viking://resources/my-kb/raw/foo.md")
    parser.add_argument("--model", default=None, help="Override model name")
    parser.add_argument("--openai-api-key", default=None, help="Override OpenAI API key")
    parser.add_argument("--openai-base-url", default=None, help="Override OpenAI base URL")
    parser.add_argument(
        "--llm-config",
        default=str(DEFAULT_LLM_CONFIG_PATH),
        help="Path to LLM config JSON (default: project config/llm-wiki-config.json)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes back to OpenViking")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print result JSON")
    parser.add_argument("--config", default=None, help="Path to config JSON")
    parser.add_argument("--profile", default=None, help="Profile name")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kb_root = build_kb_root(args.kb_name)
    schema_text = read_local_schema()
    _ = load_config(config_path=args.config, profile=args.profile)
    config = OVFSConfig.load(config_path=args.config, profile=args.profile)
    openai_settings = resolve_openai_settings(args)

    try:
        with OVFSClient(config) as client:
            canonical_source_uri = resolve_canonical_markdown_uri(client, args.source_uri)
            if not canonical_source_uri:
                raise OVFSHTTPError(f"File not found: {args.source_uri}")

            source_text = client.read_text(canonical_source_uri)
            context = build_context_snapshot(client, kb_root)

            source_slug = slugify(basename_without_ext(args.source_uri))
            prompt = build_llm_prompt(
                schema_text=schema_text,
                source_uri=args.source_uri,
                source_text=source_text,
                context=context,
                source_slug=source_slug,
            )
            llm_result = call_llm(
                prompt,
                api_key=openai_settings["api_key"],
                base_url=openai_settings["base_url"],
                model=openai_settings["model"],
            )

            source_title = str(llm_result.get("source_title", "")).strip() or source_slug
            source_page_markdown = str(llm_result.get("source_page_markdown", "")).strip()
            overview_note = str(llm_result.get("overview_note", "")).strip()
            log_note = str(llm_result.get("log_note", "")).strip()

            entity_pages = sanitize_pages(llm_result.get("entity_pages", []), "entity")
            concept_pages = sanitize_pages(llm_result.get("concept_pages", []), "concept")

            if not source_page_markdown:
                raise RuntimeError("LLM did not return source_page_markdown")

            source_page_uri = kb_root + f"wiki/sources/{source_slug}.md"
            index_uri = kb_root + "wiki/index.md"
            overview_uri = kb_root + "wiki/overview.md"
            log_uri = kb_root + "wiki/log.md"

            new_index_text = update_index_text(
                context["index_text"],
                source_slug=source_slug,
                source_title=source_title,
                entity_pages=entity_pages,
                concept_pages=concept_pages,
            )
            new_overview_text = append_overview_note(context["overview_text"], overview_note, source_title)
            new_log_text = append_log_entry(
                context["log_text"],
                log_note or f"已将资料 {source_slug} 整理为 wiki/sources/{source_slug}.md",
            )

            write_plan = {
                "source_page": source_page_uri,
                "entity_pages": [kb_root + f"wiki/entities/{p['slug']}.md" for p in entity_pages],
                "concept_pages": [kb_root + f"wiki/concepts/{p['slug']}.md" for p in concept_pages],
                "index_uri": index_uri,
                "overview_uri": overview_uri,
                "log_uri": log_uri,
            }

            if not args.dry_run:
                write_page(client, source_page_uri, source_page_markdown)

                for page in entity_pages:
                    uri = kb_root + f"wiki/entities/{page['slug']}.md"
                    write_page(client, uri, page["markdown"])

                for page in concept_pages:
                    uri = kb_root + f"wiki/concepts/{page['slug']}.md"
                    write_page(client, uri, page["markdown"])

                write_page(client, index_uri, new_index_text)
                write_page(client, overview_uri, new_overview_text)
                write_page(client, log_uri, new_log_text)

            result = {
                "status": "ok",
                "kb_root": kb_root,
                "source_uri": args.source_uri,
                "source_slug": source_slug,
                "source_title": source_title,
                "entity_count": len(entity_pages),
                "concept_count": len(concept_pages),
                "dry_run": args.dry_run,
                "write_plan": write_plan,
            }

            if args.pretty:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(json.dumps(result, ensure_ascii=False))

            return 0

    except Exception as exc:
        error_result = {
            "status": "error",
            "kb_root": kb_root,
            "source_uri": args.source_uri,
            "error": str(exc),
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
