from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Set, Tuple

from scripts.ovfs import OVFSClient, OVFSConfig, OVFSError, OVFSHTTPError


ROOT_PAGES = {
    "index.md",
    "overview.md",
    "log.md",
}

WIKI_SUBDIRS = [
    "sources",
    "entities",
    "concepts",
    "syntheses",
]

ALLOWED_WIKI_ROOT_NAMES = ROOT_PAGES | set(WIKI_SUBDIRS)


def build_kb_root(kb_name: str) -> str:
    normalized_name = kb_name.strip().strip("/")
    if not normalized_name:
        raise ValueError("--kb-name cannot be empty")
    if normalized_name.startswith("viking://"):
        raise ValueError("--kb-name should be a resource name, not a full URI")
    return f"viking://resources/{normalized_name}/"


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
        child_uri: Optional[str] = None
        child_is_dir: Optional[bool] = None

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


def check_unexpected_wiki_root_entries(client: OVFSClient, kb_root: str) -> List[str]:
    wiki_root = kb_root + "wiki/"
    try:
        items = client.ls(wiki_root, recursive=False)
    except Exception:
        return []

    unexpected_entries: List[str] = []
    for item in items:
        uri = extract_uri_from_ls_item(item)
        if not uri:
            continue

        if uri.startswith(wiki_root):
            rel = uri[len(wiki_root):].strip("/")
            if not rel:
                continue
            root_name = rel.split("/", 1)[0]
        else:
            root_name = PurePosixPath(uri).name.strip("/")
            if not root_name:
                continue

        if root_name not in ALLOWED_WIKI_ROOT_NAMES:
            unexpected_entries.append(uri)

    return sorted(set(unexpected_entries))


def wiki_relative_path(kb_root: str, uri: str) -> str:
    prefix = kb_root + "wiki/"
    if uri.startswith(prefix):
        return uri[len(prefix):]
    return PurePosixPath(uri).name


def normalize_relative_wiki_target(target: str) -> str | None:
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


def extract_internal_links(text: str) -> Set[str]:
    results: Set[str] = set()

    wikilink_pattern = re.compile(r"\[\[([^\]]+)\]\]")
    markdown_link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

    for raw in wikilink_pattern.findall(text):
        normalized = normalize_relative_wiki_target(raw)
        if normalized:
            results.add(normalized)

    for raw in markdown_link_pattern.findall(text):
        normalized = normalize_relative_wiki_target(raw)
        if normalized:
            results.add(normalized)

    return results


def build_candidate_target_uris(kb_root: str, source_page_uri: str, relative_target: str) -> List[str]:
    """
    Resolve a wiki-internal target into candidate URIs.

    Cases:
    - concepts/foo.md -> direct
    - foo.md -> try same dir, then common subdirs
    """
    target = relative_target.strip().lstrip("/")
    source_rel = wiki_relative_path(kb_root, source_page_uri)
    source_dir = str(PurePosixPath(source_rel).parent)

    candidates: List[str] = []

    if "/" in target:
        candidates.append(kb_root + "wiki/" + target)
        return candidates

    if source_dir and source_dir != ".":
        candidates.append(kb_root + f"wiki/{source_dir}/{target}")

    for subdir in WIKI_SUBDIRS:
        candidates.append(kb_root + f"wiki/{subdir}/{target}")

    # root fallback
    candidates.append(kb_root + "wiki/" + target)

    # dedupe preserve order
    seen: Set[str] = set()
    deduped: List[str] = []
    for uri in candidates:
        if uri not in seen:
            seen.add(uri)
            deduped.append(uri)
    return deduped


def is_meaningful_page(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(lines) <= 1:
        return False

    content_chars = sum(len(line) for line in lines)
    return content_chars >= 30


def page_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def check_broken_links(
    client: OVFSClient,
    kb_root: str,
    page_map: Dict[str, str],
) -> List[Dict[str, str]]:
    broken: List[Dict[str, str]] = []

    for source_uri, text in page_map.items():
        for rel_target in sorted(extract_internal_links(text)):
            candidates = build_candidate_target_uris(kb_root, source_uri, rel_target)
            found = False
            for candidate in candidates:
                canonical = resolve_canonical_markdown_uri(client, candidate)
                if canonical:
                    found = True
                    break
            if not found:
                broken.append(
                    {
                        "source_uri": source_uri,
                        "target": rel_target,
                    }
                )

    return broken


def check_orphan_pages(
    kb_root: str,
    page_map: Dict[str, str],
) -> List[str]:
    inbound_counts: Dict[str, int] = {uri: 0 for uri in page_map.keys()}

    for source_uri, text in page_map.items():
        for rel_target in extract_internal_links(text):
            candidates = build_candidate_target_uris(kb_root, source_uri, rel_target)
            for candidate in candidates:
                if candidate in inbound_counts:
                    inbound_counts[candidate] += 1
                    break

    orphans: List[str] = []
    for uri, count in inbound_counts.items():
        rel = wiki_relative_path(kb_root, uri)
        name = PurePosixPath(rel).name
        if name in ROOT_PAGES:
            continue
        if count == 0:
            orphans.append(uri)

    return sorted(orphans)


def check_pages_without_outbound_links(
    kb_root: str,
    page_map: Dict[str, str],
) -> List[str]:
    results: List[str] = []

    for uri, text in page_map.items():
        rel = wiki_relative_path(kb_root, uri)
        name = PurePosixPath(rel).name
        if name in ROOT_PAGES:
            continue

        links = extract_internal_links(text)
        if not links:
            results.append(uri)

    return sorted(results)


def check_duplicate_titles(page_map: Dict[str, str]) -> Dict[str, List[str]]:
    title_map: Dict[str, List[str]] = {}

    for uri, text in page_map.items():
        title = page_title(text).strip()
        if not title:
            continue
        key = title.lower()
        title_map.setdefault(key, []).append(uri)

    duplicates: Dict[str, List[str]] = {}
    for key, uris in title_map.items():
        if len(uris) > 1:
            duplicates[key] = sorted(uris)

    return duplicates


def check_stub_pages(page_map: Dict[str, str]) -> List[str]:
    stubs: List[str] = []
    for uri, text in page_map.items():
        if not is_meaningful_page(text):
            stubs.append(uri)
    return sorted(stubs)


def build_report(client: OVFSClient, kb_root: str) -> Dict[str, Any]:
    all_pages = list_markdown_pages(client, kb_root + "wiki/")
    unexpected_wiki_root_entries = check_unexpected_wiki_root_entries(client, kb_root)
    page_map: Dict[str, str] = {}

    for uri in all_pages:
        try:
            page_map[uri] = client.read_text(uri)
        except Exception:
            page_map[uri] = ""

    broken_links = check_broken_links(client, kb_root, page_map)
    orphan_pages = check_orphan_pages(kb_root, page_map)
    no_outbound_links = check_pages_without_outbound_links(kb_root, page_map)
    duplicate_titles = check_duplicate_titles(page_map)
    stub_pages = check_stub_pages(page_map)

    errors: List[str] = []
    warnings: List[str] = []

    if broken_links:
        errors.append(f"Broken internal links: {len(broken_links)}")

    if unexpected_wiki_root_entries:
        errors.append(f"Unexpected wiki root entries: {len(unexpected_wiki_root_entries)}")

    if orphan_pages:
        warnings.append(f"Orphan pages: {len(orphan_pages)}")

    if no_outbound_links:
        warnings.append(f"Pages without outbound internal links: {len(no_outbound_links)}")

    if duplicate_titles:
        warnings.append(f"Duplicate page titles: {len(duplicate_titles)}")

    if stub_pages:
        warnings.append(f"Stub or nearly empty pages: {len(stub_pages)}")

    status = "ok"
    if errors:
        status = "error"
    elif warnings:
        status = "warn"

    return {
        "status": status,
        "kb_root": kb_root,
        "summary": {
            "total_pages": len(all_pages),
            "unexpected_wiki_root_entries": len(unexpected_wiki_root_entries),
            "broken_links": len(broken_links),
            "orphan_pages": len(orphan_pages),
            "pages_without_outbound_links": len(no_outbound_links),
            "duplicate_titles": len(duplicate_titles),
            "stub_pages": len(stub_pages),
        },
        "errors": errors,
        "warnings": warnings,
        "details": {
            "unexpected_wiki_root_entries": unexpected_wiki_root_entries,
            "broken_links": broken_links,
            "orphan_pages": orphan_pages,
            "pages_without_outbound_links": no_outbound_links,
            "duplicate_titles": duplicate_titles,
            "stub_pages": stub_pages,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run structural lint checks on a remote OpenViking wiki KB.")
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
