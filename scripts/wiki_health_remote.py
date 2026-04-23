from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import PurePosixPath
from typing import Any, Dict, List, Set, Tuple

from scripts.ovfs import OVFSClient, OVFSConfig, OVFSError, OVFSHTTPError


REQUIRED_DIRS = [
    "raw/",
    "wiki/",
    "wiki/sources/",
    "wiki/entities/",
    "wiki/concepts/",
    "wiki/syntheses/",
    "graph/",
]

REQUIRED_FILES = [
    "wiki/index.md",
    "wiki/overview.md",
    "wiki/log.md",
]

DERIVED_FILE_NAMES = {".abstract.md", ".overview.md", ".relations.json"}


def build_kb_root(kb_name: str) -> str:
    normalized_name = kb_name.strip().strip("/")
    if not normalized_name:
        raise ValueError("--kb-name cannot be empty")
    if normalized_name.startswith("viking://"):
        raise ValueError("--kb-name should be a resource name, not a full URI")
    return f"viking://resources/{normalized_name}/"


def extract_uri_from_ls_item(item: Any) -> str | None:
    """
    Be tolerant to different OpenViking ls() response shapes.
    """
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


def normalize_relative_wiki_target(target: str) -> str | None:
    """
    Normalize a link target found inside wiki/index.md or other pages.

    Supported:
    - [[concepts/foo]]
    - [[concepts/foo.md]]
    - [foo](concepts/foo.md)
    - [foo](wiki/concepts/foo.md)

    Ignore:
    - http(s) links
    - anchors
    """
    target = target.strip()
    if not target:
        return None
    if target.startswith("http://") or target.startswith("https://"):
        return None
    if target.startswith("#"):
        return None

    if target.startswith("wiki/"):
        target = target[len("wiki/"):]

    if target.endswith("/"):
        return None

    if not target.endswith(".md"):
        target = f"{target}.md"

    return target


def extract_index_links(index_text: str) -> Set[str]:
    """
    Extract relative wiki paths from:
    - [[wikilinks]]
    - markdown links: [text](target)
    """
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


def is_meaningful_page(text: str) -> bool:
    """
    Simple non-LLM heuristic for detecting empty/stub pages.
    """
    stripped = text.strip()
    if not stripped:
        return False

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(lines) <= 1:
        return False

    content_chars = sum(len(line) for line in lines)
    return content_chars >= 30


def basename_without_ext(uri: str) -> str:
    name = PurePosixPath(uri).name
    if name.endswith(".md"):
        return name[:-3]
    return name


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

    basename = PurePosixPath(uri.rstrip("/")).name
    if basename:
        nested_candidate = uri.rstrip("/") + f"/{basename}"
        nested_stat = get_uri_stat(client, nested_candidate)
        if nested_stat and not nested_stat.get("isDir", False):
            return nested_candidate

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

        if child_is_dir is None:
            child_stat = get_uri_stat(client, child_uri)
            child_is_dir = bool(child_stat and child_stat.get("isDir", False))

        if not child_is_dir:
            return child_uri

    return None


def get_log_match_stem(uri: str, sources_root: str) -> str:
    stem = basename_without_ext(uri).lower()
    if not stem.startswith("tmp"):
        return stem

    normalized_uri = uri.rstrip("/")
    normalized_sources_root = sources_root.rstrip("/") + "/"
    if normalized_uri.startswith(normalized_sources_root):
        segments = normalized_uri.split("/")
        if len(segments) >= 2:
            parent_name = segments[-2]
            if parent_name.endswith(".md"):
                return parent_name[:-3].lower()

    return stem


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
        if PurePosixPath(uri).name in DERIVED_FILE_NAMES:
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

    # Deduplicate while preserving order
    seen: Set[str] = set()
    deduped: List[str] = []
    for uri in uris:
        if uri not in seen:
            seen.add(uri)
            deduped.append(uri)

    return deduped


def check_required_structure(client: OVFSClient, kb_root: str) -> Tuple[List[str], List[str]]:
    missing_dirs: List[str] = []
    missing_files: List[str] = []

    for rel in REQUIRED_DIRS:
        uri = kb_root + rel
        stat = get_uri_stat(client, uri)
        if not stat or not stat.get("isDir", False):
            missing_dirs.append(uri)

    for rel in REQUIRED_FILES:
        uri = kb_root + rel
        canonical_uri = resolve_canonical_markdown_uri(client, uri)
        if not canonical_uri:
            missing_files.append(uri)

    return missing_dirs, missing_files


def check_empty_key_pages(client: OVFSClient, kb_root: str) -> List[str]:
    empty_pages: List[str] = []

    for rel in REQUIRED_FILES:
        uri = kb_root + rel
        canonical_uri = resolve_canonical_markdown_uri(client, uri)
        if not canonical_uri:
            continue
        try:
            text = client.read_text(canonical_uri)
        except Exception:
            empty_pages.append(uri)
            continue
        if not is_meaningful_page(text):
            empty_pages.append(uri)

    return empty_pages


def check_index_targets(client: OVFSClient, kb_root: str) -> Tuple[List[str], List[str]]:
    index_uri = kb_root + "wiki/index.md"
    canonical_index_uri = resolve_canonical_markdown_uri(client, index_uri)
    if not canonical_index_uri:
        return [], [index_uri]

    try:
        index_text = client.read_text(canonical_index_uri)
    except Exception:
        return [], [index_uri]

    linked_targets = sorted(extract_index_links(index_text))

    broken: List[str] = []
    for rel in linked_targets:
        target_uri = kb_root + "wiki/" + rel
        canonical_target_uri = resolve_canonical_markdown_uri(client, target_uri)
        if not canonical_target_uri:
            broken.append(target_uri)

    return linked_targets, broken


def check_source_log_coverage(client: OVFSClient, kb_root: str) -> List[str]:
    sources_root = kb_root + "wiki/sources/"
    log_uri = kb_root + "wiki/log.md"

    canonical_log_uri = resolve_canonical_markdown_uri(client, log_uri)
    if not canonical_log_uri:
        return []

    log_text = client.read_text(canonical_log_uri).lower()
    source_pages = list_markdown_pages(client, sources_root)

    missing_in_log: List[str] = []
    for uri in source_pages:
        stem = get_log_match_stem(uri, sources_root)
        if stem not in log_text:
            missing_in_log.append(uri)

    return missing_in_log


def build_report(client: OVFSClient, kb_root: str) -> Dict[str, Any]:
    missing_dirs, missing_files = check_required_structure(client, kb_root)
    empty_key_pages = check_empty_key_pages(client, kb_root)
    linked_targets, broken_index_targets = check_index_targets(client, kb_root)
    missing_source_log_entries = check_source_log_coverage(client, kb_root)

    all_wiki_pages = list_markdown_pages(client, kb_root + "wiki/")
    all_source_pages = list_markdown_pages(client, kb_root + "wiki/sources/")
    all_entity_pages = list_markdown_pages(client, kb_root + "wiki/entities/")
    all_concept_pages = list_markdown_pages(client, kb_root + "wiki/concepts/")
    all_synthesis_pages = list_markdown_pages(client, kb_root + "wiki/syntheses/")

    errors: List[str] = []
    warnings: List[str] = []

    if missing_dirs:
        errors.append(f"Missing required directories: {len(missing_dirs)}")
    if missing_files:
        errors.append(f"Missing required root files: {len(missing_files)}")
    if empty_key_pages:
        errors.append(f"Empty or invalid key pages: {len(empty_key_pages)}")
    if broken_index_targets:
        errors.append(f"Broken links referenced by wiki/index.md: {len(broken_index_targets)}")
    if not all_source_pages:
        warnings.append("No source pages found under wiki/sources/")

    if not linked_targets:
        warnings.append("wiki/index.md contains no parseable internal links")
    if not all_entity_pages and not all_concept_pages and not all_synthesis_pages:
        warnings.append("No entity, concept, or synthesis pages found")
    if len(all_wiki_pages) <= 3:
        warnings.append("Wiki appears to contain only root pages")

    if missing_source_log_entries:
        warnings.append(
            f"Source pages not reflected in wiki/log.md: {len(missing_source_log_entries)}"
        )

    status = "ok" if not errors else "error"

    return {
        "status": status,
        "kb_root": kb_root,
        "summary": {
            "wiki_pages": len(all_wiki_pages),
            "source_pages": len(all_source_pages),
            "entity_pages": len(all_entity_pages),
            "concept_pages": len(all_concept_pages),
            "synthesis_pages": len(all_synthesis_pages),
            "index_links": len(linked_targets),
        },
        "errors": errors,
        "warnings": warnings,
        "details": {
            "missing_dirs": missing_dirs,
            "missing_files": missing_files,
            "empty_key_pages": empty_key_pages,
            "broken_index_targets": broken_index_targets,
            "missing_source_log_entries": missing_source_log_entries,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run structural health checks on a remote OpenViking wiki KB.")
    parser.add_argument(
        "--kb-name",
        required=True,
        help="Knowledge base name under viking://resources/",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kb_root = build_kb_root(args.kb_name)
    config = OVFSConfig.load()

    try:
        with OVFSClient(config) as client:
            report = build_report(client, kb_root)
    except OVFSError as exc:
        error_report = {
            "status": "error",
            "kb_root": kb_root,
            "errors": [f"OVFS error: {str(exc)}"],
            "warnings": [],
            "details": {},
        }
        print(json.dumps(error_report, ensure_ascii=False, indent=2))
        return 2
    except Exception as exc:
        error_report = {
            "status": "error",
            "kb_root": kb_root,
            "errors": [f"Unexpected error: {str(exc)}"],
            "warnings": [],
            "details": {},
        }
        print(json.dumps(error_report, ensure_ascii=False, indent=2))
        return 3

    if args.pretty:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False))

    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
