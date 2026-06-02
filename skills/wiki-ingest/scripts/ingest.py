from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from ovfs import OVFSClient, OVFSConfig, OVFSError, OVFSHTTPError
from dataclasses import dataclass

from common import build_error_result, build_kb_root, load_config, print_json


class IngestSourceError(RuntimeError):
    pass


IGNORED_SOURCE_MARKDOWN_NAMES = {
    ".abstract.md",
    ".overview.md",
    "abstract.md",
    "overview.md",
}


@dataclass
class IngestSourceBundle:
    root_uri: str
    markdown_uris: List[str]
    ignored_metadata_uris: List[str]
    source_kind: str


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


def is_ignored_source_markdown(uri: str) -> bool:
    name = PurePosixPath(uri.rstrip("/")).name
    return name in IGNORED_SOURCE_MARKDOWN_NAMES


def is_dir_stat(stat: dict[str, Any]) -> bool:
    if isinstance(stat.get("isDir"), bool):
        return stat["isDir"]
    if isinstance(stat.get("is_dir"), bool):
        return stat["is_dir"]
    if str(stat.get("type", "")).lower() in {"dir", "directory", "folder"}:
        return True
    return False


def extract_child_uri_and_is_dir(child: Any) -> tuple[str | None, bool | None]:
    if isinstance(child, str):
        return child, None

    if isinstance(child, dict):
        child_uri = child.get("uri") or child.get("path")
        child_is_dir: bool | None = None

        if isinstance(child.get("isDir"), bool):
            child_is_dir = child["isDir"]
        elif isinstance(child.get("is_dir"), bool):
            child_is_dir = child["is_dir"]
        elif str(child.get("type", "")).lower() in {"dir", "directory", "folder"}:
            child_is_dir = True

        return child_uri, child_is_dir

    return None, None


def find_direct_content_child(client: OVFSClient, uri: str, extensions: tuple[str, ...] = (".md",)) -> str | None:
    if not uri.endswith("/"):
        uri = uri.rstrip("/") + "/"
    try:
        children = client.ls(uri, recursive=False)
    except Exception:
        return None

    candidates: list[str] = []

    for child in children:
        child_uri, child_is_dir_hint = extract_child_uri_and_is_dir(child)
        if not child_uri or not isinstance(child_uri, str):
            continue

        name = PurePosixPath(child_uri).name

        if name == "abstract.md":
            continue

        if not name.endswith(extensions):
            continue

        if child_is_dir_hint is None:
            child_stat = get_uri_stat(client, child_uri)
            child_is_dir_hint = bool(child_stat and is_dir_stat(child_stat))

        if child_is_dir_hint:
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


def expected_content_child_uri(uri: str) -> str:
    normalized = uri.rstrip("/")
    basename = PurePosixPath(normalized).name
    return f"{normalized}/{basename}"


def stat_uri_with_variants(
    client: OVFSClient,
    uri: str,
) -> tuple[str, Dict[str, Any]] | None:
    raw = uri.strip()
    if not raw:
        return None

    candidates = [raw]
    if raw.endswith("/"):
        candidates.append(raw.rstrip("/"))
    else:
        candidates.append(raw.rstrip("/") + "/")

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        stat = get_uri_stat(client, candidate)
        if stat:
            return candidate, stat

    return None


MAX_SOURCE_DISCOVERY_NODES = 1000


def natural_sort_key(text: str) -> list[Any]:
    return [
        int(x) if x.isdigit() else x.lower()
        for x in re.split(r"(\d+)", text)
    ]


def discover_markdown_sources_under_dir(
    client: OVFSClient,
    dir_uri: str,
) -> tuple[List[str], List[str]]:
    if not dir_uri.endswith("/"):
        dir_uri = dir_uri.rstrip("/") + "/"

    markdown_uris: List[str] = []
    ignored_metadata_uris: List[str] = []
    visited: set[str] = set()
    queue: List[str] = [dir_uri]
    nodes_scanned = 0

    while queue:
        current_dir = queue.pop(0)
        if current_dir in visited:
            continue
        visited.add(current_dir)
        nodes_scanned += 1

        if nodes_scanned > MAX_SOURCE_DISCOVERY_NODES:
            raise IngestSourceError(
                f"source bundle 过大或存在循环，已停止扫描; scanned={nodes_scanned}"
            )

        try:
            children = client.ls(current_dir, recursive=False)
        except OVFSHTTPError as exc:
            msg = str(exc).lower()
            if "404" in msg or "not found" in msg:
                continue
            raise IngestSourceError(f"扫描目录失败: {current_dir}: {exc}") from exc
        except Exception as exc:
            raise IngestSourceError(f"扫描目录失败: {current_dir}: {exc}") from exc

        for child in children:
            child_uri, child_is_dir_hint = extract_child_uri_and_is_dir(child)
            if not child_uri or not isinstance(child_uri, str):
                continue

            if child_is_dir_hint is None:
                child_resolved = stat_uri_with_variants(client, child_uri)
                if child_resolved:
                    child_uri = child_resolved[0]
                    child_is_dir_hint = is_dir_stat(child_resolved[1])

            if child_is_dir_hint:
                queue.append(child_uri if child_uri.endswith("/") else child_uri + "/")
                continue

            if not child_uri.lower().endswith(".md"):
                continue

            if is_ignored_source_markdown(child_uri):
                ignored_metadata_uris.append(child_uri)
                continue

            markdown_uris.append(child_uri)

    markdown_uris = sorted(set(markdown_uris), key=natural_sort_key)
    ignored_metadata_uris = sorted(set(ignored_metadata_uris), key=natural_sort_key)
    return markdown_uris, ignored_metadata_uris


def resolve_ingest_source_bundle(
    client: OVFSClient,
    source_uri: str,
) -> IngestSourceBundle:
    resolved = stat_uri_with_variants(client, source_uri)
    if not resolved:
        raise IngestSourceError(f"Source not found: {source_uri}")

    resolved_uri, stat = resolved

    if is_dir_stat(stat):
        markdown_uris, ignored_metadata_uris = discover_markdown_sources_under_dir(
            client, resolved_uri,
        )

        if not markdown_uris:
            if ignored_metadata_uris:
                raise IngestSourceError(
                    "未找到可 ingest 的正文 markdown。"
                    "该目录下只有 metadata markdown，已跳过。"
                )
            raise IngestSourceError(
                "未找到可 ingest 的 markdown。"
                "可能是上传转换尚未完成，或 source-uri 指错。"
            )

        return IngestSourceBundle(
            root_uri=resolved_uri,
            markdown_uris=markdown_uris,
            ignored_metadata_uris=ignored_metadata_uris,
            source_kind=(
                "directory_single_markdown"
                if len(markdown_uris) == 1
                else "directory_bundle"
            ),
        )

    if resolved_uri.lower().endswith(".md"):
        if is_ignored_source_markdown(resolved_uri):
            raise IngestSourceError(
                f"该 markdown 是 metadata 文件，不能 ingest: {resolved_uri}"
            )
        return IngestSourceBundle(
            root_uri=resolved_uri,
            markdown_uris=[resolved_uri],
            ignored_metadata_uris=[],
            source_kind="single_markdown_file",
        )

    raise IngestSourceError(
        f"该 source 不是可 ingest 的 markdown 文件，也不是包含 markdown 的目录: {resolved_uri}"
    )


def read_source_bundle_text(
    client: OVFSClient,
    bundle: IngestSourceBundle,
) -> str:
    parts: List[str] = []
    total = len(bundle.markdown_uris)
    for idx, uri in enumerate(bundle.markdown_uris, start=1):
        content = client.read_text(uri)
        parts.append(f"--- SOURCE FILE {idx}/{total} ---")
        parts.append(f"URI: {uri}")
        parts.append("")
        parts.append(content)
        parts.append("")
    return "\n".join(parts)


def source_name_from_uri(uri: str) -> str:
    return PurePosixPath(uri.rstrip("/")).name


def source_title_stem_from_uri(uri: str) -> str:
    name = source_name_from_uri(uri)
    suffixes = [
        ".docx", ".doc", ".pdf", ".md", ".txt",
        ".json", ".yaml", ".yml", ".sh", ".py",
    ]
    lower = name.lower()
    for suffix in suffixes:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return name


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


def list_markdown_pages_non_recursive(client: OVFSClient, root_uri: str) -> List[str]:
    try:
        items = client.ls(root_uri, recursive=False)
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


def truncate_for_prompt(text: str, max_chars: int) -> Tuple[str, bool]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    if len(text) <= max_chars:
        return text, False

    marker = "\n... [truncated for prompt] ...\n"
    budget = max_chars - len(marker)
    if budget <= 2:
        return text[:max_chars], True

    head_len = budget // 2
    tail_len = budget - head_len
    return text[:head_len] + marker + text[-tail_len:], True


def split_markdown_into_chunks(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    max_chunks: int,
) -> Dict[str, Any]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be non-negative")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    if max_chunks <= 0:
        raise ValueError("max_chunks must be positive")

    original_char_count = len(text)
    if not text:
        return {
            "chunks": [],
            "truncated": False,
            "original_char_count": 0,
            "chunk_count": 0,
            "used_chunk_count": 0,
        }

    chunks: List[str] = []
    start = 0
    while start < len(text):
        tentative_end = min(start + chunk_size, len(text))
        end = tentative_end

        if tentative_end < len(text):
            window = text[start:tentative_end]
            heading_idx = window.rfind("\n#")
            blank_idx = window.rfind("\n\n")
            split_idx = -1
            if heading_idx > 0:
                split_idx = heading_idx + 1
            elif blank_idx > 0:
                split_idx = blank_idx + 2

            if split_idx > 0:
                end = start + split_idx

        if end <= start:
            end = tentative_end

        chunk = text[start:end]
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break
        next_start = end - chunk_overlap
        if next_start <= start:
            next_start = end
        start = next_start

    chunk_count = len(chunks)
    used_chunk_count = min(chunk_count, max_chunks)
    truncated = chunk_count > max_chunks
    return {
        "chunks": chunks,
        "truncated": truncated,
        "original_char_count": original_char_count,
        "chunk_count": chunk_count,
        "used_chunk_count": used_chunk_count,
    }


def extract_page_names_from_index(index_text: str, section_key: str) -> List[str]:
    section_headings = [INDEX_SECTIONS[section_key], *LEGACY_INDEX_SECTIONS.get(section_key, [])]
    lines = index_text.splitlines()

    in_section = False
    names: List[str] = []
    seen = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped in section_headings
            continue

        if not in_section:
            continue

        match = re.search(r"\[\[((?:entities|concepts)/[^\]]+\.md)\]\]", stripped)
        if not match:
            continue
        rel_path = match.group(1)
        page_name = PurePosixPath(rel_path).name
        if page_name and page_name not in seen:
            seen.add(page_name)
            names.append(page_name)

    return names


def build_context_snapshot(
    client: OVFSClient,
    kb_root: str,
    *,
    max_context_chars: int,
    max_existing_page_names: int,
) -> Dict[str, Any]:
    index_text = read_if_exists(client, kb_root + "wiki/index.md", INDEX_TITLE + "\n")
    overview_text = read_if_exists(client, kb_root + "wiki/overview.md", OVERVIEW_TITLE + "\n")
    log_text = read_if_exists(client, kb_root + "wiki/log.md", LOG_TITLE + "\n")

    entity_page_names = extract_page_names_from_index(index_text, "entities")
    concept_page_names = extract_page_names_from_index(index_text, "concepts")

    if not entity_page_names:
        entity_page_names = [
            PurePosixPath(uri).name
            for uri in list_markdown_pages_non_recursive(client, kb_root + "wiki/entities/")
        ]
    if not concept_page_names:
        concept_page_names = [
            PurePosixPath(uri).name
            for uri in list_markdown_pages_non_recursive(client, kb_root + "wiki/concepts/")
        ]

    entity_pages = [kb_root + "wiki/entities/" + name for name in entity_page_names[:max_existing_page_names]]
    concept_pages = [kb_root + "wiki/concepts/" + name for name in concept_page_names[:max_existing_page_names]]
    source_pages = list_markdown_pages(client, kb_root + "wiki/sources/")

    index_excerpt, index_truncated_for_prompt = truncate_for_prompt(index_text, max_context_chars)
    overview_excerpt, overview_truncated_for_prompt = truncate_for_prompt(overview_text, max_context_chars)

    return {
        "index_text": index_text,
        "overview_text": overview_text,
        "log_text": log_text,
        "index_excerpt": index_excerpt,
        "overview_excerpt": overview_excerpt,
        "index_truncated_for_prompt": index_truncated_for_prompt,
        "overview_truncated_for_prompt": overview_truncated_for_prompt,
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
    source_markdown_uris: List[str] | None = None,
) -> str:
    if "index_excerpt" not in context or "overview_excerpt" not in context:
        raise ValueError("context must include index_excerpt and overview_excerpt for prompt building")

    entity_page_names = [PurePosixPath(uri).name for uri in context["entity_pages"]]
    concept_page_names = [PurePosixPath(uri).name for uri in context["concept_pages"]]
    index_excerpt = str(context["index_excerpt"])
    overview_excerpt = str(context["overview_excerpt"])

    bundle_section = ""
    if source_markdown_uris:
        uri_list = "\n".join(f"- {u}" for u in source_markdown_uris)
        bundle_section = f"""
本次 ingest 的 source root URI：
{source_uri}

本次 ingest 包含的正文 markdown URI：
{uri_list}

注意：.abstract.md 和 .overview.md 属于 metadata，不能作为正文来源。

"""

    return f"""
你正在为基于远端 OpenViking 的 llm-wiki 知识库生成 wiki 内容。
{bundle_section}请严格遵循以下 schema：

--- SCHEMA START ---
{schema_text}
--- SCHEMA END ---

当前 source URI：
{source_uri}

建议使用的 source slug：
{source_slug}

当前 wiki/index.md（用于提示的节选）：
--- INDEX START ---
{index_excerpt}
--- INDEX END ---

当前 wiki/overview.md（用于提示的节选）：
--- OVERVIEW START ---
{overview_excerpt}
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


def build_chunk_summary_prompt(
    *,
    source_uri: str,
    source_slug: str,
    chunk_index: int,
    chunk_count: int,
    chunk_text: str,
) -> str:
    return f"""
你正在为 wiki ingest 的长文档流程生成分块摘要。

当前 source URI：
{source_uri}

source slug：
{source_slug}

当前分块：第 {chunk_index}/{chunk_count} 块。

请阅读分块原文并仅返回 JSON：

{{
  "summary": "string",
  "key_entities": ["string"],
  "key_concepts": ["string"],
  "key_claims": ["string"],
  "possible_wikilinks": ["string"]
}}

分块原文：
--- CHUNK START ---
{chunk_text}
--- CHUNK END ---

规则：
- 所有自然语言使用简体中文。
- 只输出合法 JSON，不要输出额外说明。
""".strip()


def summarize_chunk(
    *,
    source_uri: str,
    source_slug: str,
    chunk_index: int,
    chunk_count: int,
    chunk_text: str,
    api_key: Optional[str],
    base_url: Optional[str],
    model: Optional[str],
) -> Dict[str, Any]:
    prompt = build_chunk_summary_prompt(
        source_uri=source_uri,
        source_slug=source_slug,
        chunk_index=chunk_index,
        chunk_count=chunk_count,
        chunk_text=chunk_text,
    )
    result = call_llm(
        prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )

    summary = str(result.get("summary", "")).strip()
    if not summary:
        raise RuntimeError("Chunk summary is empty")

    def normalize_string_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        output: List[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                output.append(text)
        return output

    return {
        "summary": summary,
        "key_entities": normalize_string_list(result.get("key_entities", [])),
        "key_concepts": normalize_string_list(result.get("key_concepts", [])),
        "key_claims": normalize_string_list(result.get("key_claims", [])),
        "possible_wikilinks": normalize_string_list(result.get("possible_wikilinks", [])),
    }


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


def dedupe_pages_by_slug(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen: set[str] = set()
    deduped: List[Dict[str, str]] = []
    for item in items:
        slug = item.get("slug", "")
        if slug in seen:
            continue
        seen.add(slug)
        deduped.append(item)
    return deduped


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

    if note.startswith("### "):
        return overview_text.rstrip() + "\n\n" + note + "\n"

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
    client.write_text(target_uri, markdown, create=should_create, wait=True)


def parse_args() -> argparse.Namespace:
    def positive_int(value: str) -> int:
        parsed = int(value)
        if parsed <= 0:
            raise argparse.ArgumentTypeError("must be a positive integer")
        return parsed

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
    parser.add_argument(
        "--max-context-chars",
        type=positive_int,
        default=12000,
        help="Max characters for each prompt context excerpt",
    )
    parser.add_argument(
        "--max-existing-page-names",
        type=positive_int,
        default=100,
        help="Max existing entity/concept page names included in prompt",
    )
    parser.add_argument("--long-doc-threshold", type=positive_int, default=30000, help="Long doc mode threshold in characters")
    parser.add_argument("--chunk-size", type=positive_int, default=18000, help="Chunk size in characters")
    parser.add_argument("--chunk-overlap", type=positive_int, default=1000, help="Chunk overlap in characters")
    parser.add_argument("--max-chunks", type=positive_int, default=20, help="Maximum chunks for long doc mode")
    parser.add_argument(
        "--allow-partial-chunks",
        action="store_true",
        help="Allow skipping failed chunk summaries (does not allow source truncation)",
    )
    args = parser.parse_args()
    if args.chunk_overlap >= args.chunk_size:
        parser.error("--chunk-overlap must be smaller than --chunk-size")
    return args


def main() -> int:
    args = parse_args()
    kb_root = ""

    try:
        kb_root = build_kb_root(args.kb_name)
        schema_text = read_local_schema()
        config = OVFSConfig.load(config_path=args.config, profile=args.profile)
        openai_settings = resolve_openai_settings(args)

        with OVFSClient(config) as client:
            source_bundle = resolve_ingest_source_bundle(client, args.source_uri)
            source_text = read_source_bundle_text(client, source_bundle)
            context = build_context_snapshot(
                client,
                kb_root,
                max_context_chars=args.max_context_chars,
                max_existing_page_names=args.max_existing_page_names,
            )

            source_slug = slugify(source_title_stem_from_uri(source_bundle.root_uri))
            long_doc_mode = len(source_text) > args.long_doc_threshold
            chunk_count = 1
            used_chunk_count = 1
            chunks_truncated = False
            summary_failures = 0
            partial_chunks_used = False

            if long_doc_mode:
                chunking_result = split_markdown_into_chunks(
                    source_text,
                    chunk_size=args.chunk_size,
                    chunk_overlap=args.chunk_overlap,
                    max_chunks=args.max_chunks,
                )
                chunk_count = int(chunking_result["chunk_count"])
                used_chunk_count = int(chunking_result["used_chunk_count"])
                chunks_truncated = bool(chunking_result["truncated"])

                if chunks_truncated:
                    raise RuntimeError(
                        f"Chunk count {chunk_count} exceeds max_chunks={args.max_chunks}; source truncation is not allowed"
                    )

                chunk_summaries: List[Dict[str, Any]] = []
                for idx, chunk_text in enumerate(chunking_result["chunks"], start=1):
                    try:
                        summary = summarize_chunk(
                            source_uri=source_bundle.root_uri,
                            source_slug=source_slug,
                            chunk_index=idx,
                            chunk_count=chunk_count,
                            chunk_text=chunk_text,
                            api_key=openai_settings["api_key"],
                            base_url=openai_settings["base_url"],
                            model=openai_settings["model"],
                        )
                        chunk_summaries.append(
                            {
                                "chunk_index": idx,
                                **summary,
                            }
                        )
                    except Exception:
                        if not args.allow_partial_chunks:
                            raise
                        summary_failures += 1

                if args.allow_partial_chunks:
                    partial_chunks_used = summary_failures > 0
                    if len(chunk_summaries) < 1:
                        raise RuntimeError("All chunk summaries failed in allow-partial-chunks mode")
                else:
                    partial_chunks_used = False

                source_for_reduce = json.dumps(
                    {
                        "chunk_summaries": chunk_summaries,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            else:
                source_for_reduce = source_text

            prompt = build_llm_prompt(
                schema_text=schema_text,
                source_uri=source_bundle.root_uri,
                source_text=source_for_reduce,
                context=context,
                source_slug=source_slug,
                source_markdown_uris=source_bundle.markdown_uris,
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
            entity_pages = dedupe_pages_by_slug(entity_pages)
            concept_pages = dedupe_pages_by_slug(concept_pages)

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
                "input_source_uri": args.source_uri,
                "source_uri": source_bundle.root_uri,
                "source_root_uri": source_bundle.root_uri,
                "source_kind": source_bundle.source_kind,
                "source_markdown_count": len(source_bundle.markdown_uris),
                "source_markdown_uris": source_bundle.markdown_uris,
                "ignored_metadata_uris": source_bundle.ignored_metadata_uris,
                "source_slug": source_slug,
                "source_title": source_title,
                "entity_count": len(entity_pages),
                "concept_count": len(concept_pages),
                "dry_run": args.dry_run,
                "context_slimming": {
                    "max_context_chars": args.max_context_chars,
                    "max_existing_page_names": args.max_existing_page_names,
                },
                "index_truncated_for_prompt": context["index_truncated_for_prompt"],
                "overview_truncated_for_prompt": context["overview_truncated_for_prompt"],
                "existing_entity_page_count": len(context["entity_pages"]),
                "existing_concept_page_count": len(context["concept_pages"]),
                "write_plan": write_plan,
                "long_doc_mode": long_doc_mode,
                "chunk_count": chunk_count,
                "used_chunk_count": used_chunk_count,
                "chunks_truncated": chunks_truncated,
                "summary_failures": summary_failures,
                "partial_chunks_used": partial_chunks_used,
            }

            print_json(result, pretty=args.pretty)
            return 0

    except Exception as exc:
        print_json(build_error_result(exc, kb_root=kb_root), pretty=args.pretty)
        return 1


if __name__ == "__main__":
    sys.exit(main())
