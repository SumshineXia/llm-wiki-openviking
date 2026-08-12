from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Set

from common import build_error_result, print_json
from ovfs import OVFSClient, OVFSConfig, OVFSError, OVFSHTTPError


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


def find_direct_content_child(client: OVFSClient, uri: str, extensions: tuple[str, ...] = (".md",)) -> str | None:
    if not uri.endswith("/"):
        uri = uri.rstrip("/") + "/"
    try:
        children = client.ls(uri, recursive=False)
    except Exception:
        return None

    candidates: List[str] = []

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
        name = PurePosixPath(child_uri).name
        if name == "abstract.md":
            continue

        if child_is_dir is None:
            child_stat = get_uri_stat(client, child_uri)
            child_is_dir = bool(child_stat and child_stat.get("isDir", False))

        if not child_is_dir:
            return child_uri

    return None


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


def extract_child_is_dir_hint(item: Any) -> bool | None:
    if not isinstance(item, dict):
        return None

    if isinstance(item.get("isDir"), bool):
        return item["isDir"]

    if isinstance(item.get("is_dir"), bool):
        return item["is_dir"]

    item_type = str(item.get("type", "")).lower()
    if item_type in {"dir", "directory", "folder"}:
        return True
    if item_type in {"file"}:
        return False

    return None


class LintLinkResolutionIndex:
    def __init__(
        self,
        file_rel_to_uri: Dict[str, str],
        dir_rels: Set[str],
        direct_markdown_children_by_dir: Dict[str, List[str]],
    ) -> None:
        self.file_rel_to_uri = file_rel_to_uri
        self.dir_rels = dir_rels
        self.direct_markdown_children_by_dir = direct_markdown_children_by_dir


def parent_rel_path(rel: str) -> str:
    parent = str(PurePosixPath(rel).parent)
    return "" if parent == "." else parent


def build_link_resolution_index(
    kb_root: str,
    wiki_tree_items: List[Any],
    page_uris: List[str],
) -> LintLinkResolutionIndex:
    wiki_root = kb_root + "wiki/"

    file_rel_to_uri: Dict[str, str] = {}
    dir_rels: Set[str] = set()
    all_rels_in_tree: List[str] = []

    for item in wiki_tree_items:
        uri = extract_uri_from_ls_item(item)
        if not uri or not isinstance(uri, str):
            continue
        if not uri.startswith(wiki_root):
            continue

        rel = wiki_relative_path(kb_root, uri).strip("/")
        if not rel:
            continue

        all_rels_in_tree.append(rel)

        is_dir = extract_child_is_dir_hint(item)
        if is_dir is True:
            dir_rels.add(rel)
        elif is_dir is False and rel.endswith(".md"):
            file_rel_to_uri.setdefault(rel, uri)

    for uri in page_uris:
        if not uri.startswith(wiki_root):
            continue
        rel = wiki_relative_path(kb_root, uri).strip("/")
        if rel and rel.endswith(".md"):
            file_rel_to_uri.setdefault(rel, uri)
            all_rels_in_tree.append(rel)

    for rel in all_rels_in_tree:
        parts = [part for part in PurePosixPath(rel).parts if part not in ("", ".")]
        for index in range(1, len(parts)):
            dir_rels.add(PurePosixPath(*parts[:index]).as_posix())

    direct_markdown_children_by_dir: Dict[str, List[str]] = {}
    for rel in file_rel_to_uri.keys():
        parent = parent_rel_path(rel)
        if not parent:
            continue
        direct_markdown_children_by_dir.setdefault(parent, []).append(rel)

    return LintLinkResolutionIndex(
        file_rel_to_uri=file_rel_to_uri,
        dir_rels=dir_rels,
        direct_markdown_children_by_dir=direct_markdown_children_by_dir,
    )


def build_link_resolution_index_from_page_map(
    kb_root: str,
    page_map: Dict[str, str],
) -> LintLinkResolutionIndex:
    return build_link_resolution_index(kb_root, [], list(page_map.keys()))


def select_direct_content_child_from_index(
    link_index: LintLinkResolutionIndex,
    dir_rel: str,
) -> str | None:
    children = [
        child_rel
        for child_rel in link_index.direct_markdown_children_by_dir.get(dir_rel, [])
        if child_rel.endswith(".md")
        and PurePosixPath(child_rel).name != "abstract.md"
    ]

    if not children:
        return None

    parent_name = PurePosixPath(dir_rel.rstrip("/")).name

    for child_rel in children:
        if PurePosixPath(child_rel).name == parent_name:
            return child_rel

    for child_rel in children:
        if PurePosixPath(child_rel).name.startswith("tmp"):
            return child_rel

    return children[0]


def resolve_canonical_markdown_uri_from_index(
    kb_root: str,
    link_index: LintLinkResolutionIndex,
    uri: str,
) -> str | None:
    wiki_root = kb_root + "wiki/"
    if not uri.startswith(wiki_root):
        return None

    rel = wiki_relative_path(kb_root, uri).strip("/")
    if not rel:
        return None

    actual_file_uri = link_index.file_rel_to_uri.get(rel)
    if actual_file_uri:
        return actual_file_uri

    if rel not in link_index.dir_rels:
        return None

    direct_child_rel = select_direct_content_child_from_index(link_index, rel)
    if direct_child_rel:
        return link_index.file_rel_to_uri.get(direct_child_rel)

    basename = PurePosixPath(rel.rstrip("/")).name
    if basename:
        nested_rel = PurePosixPath(rel, basename).as_posix()
        nested_uri = link_index.file_rel_to_uri.get(nested_rel)
        if nested_uri:
            return nested_uri

    return None


def resolve_internal_link_target_from_index(
    kb_root: str,
    source_page_uri: str,
    rel_target: str,
    link_index: LintLinkResolutionIndex,
) -> str | None:
    candidates = build_candidate_target_uris(kb_root, source_page_uri, rel_target)

    for candidate in candidates:
        canonical = resolve_canonical_markdown_uri_from_index(kb_root, link_index, candidate)
        if canonical:
            return canonical

    return None


def build_internal_link_graph(
    kb_root: str,
    page_map: Dict[str, str],
    link_index: LintLinkResolutionIndex,
) -> tuple[Dict[str, Set[str]], List[Dict[str, str]]]:
    graph: Dict[str, Set[str]] = {uri: set() for uri in page_map.keys()}
    broken: List[Dict[str, str]] = []

    for source_uri, text in page_map.items():
        for rel_target in sorted(extract_internal_links(text)):
            target_uri = resolve_internal_link_target_from_index(
                kb_root,
                source_uri,
                rel_target,
                link_index,
            )

            if target_uri:
                graph.setdefault(source_uri, set()).add(target_uri)
            else:
                broken.append(
                    {
                        "source_uri": source_uri,
                        "target": rel_target,
                    }
                )

    return graph, broken


def list_wiki_tree_items(client: OVFSClient, wiki_root: str) -> List[Any]:
  try:
    return client.ls(wiki_root, recursive=True)
  except Exception:
    return []


def list_markdown_pages_from_items(
  client: OVFSClient,
  root_uri: str,
  items: List[Any],
) -> List[str]:
  del root_uri

  uris: List[str] = []

  for item in items:
    uri = extract_uri_from_ls_item(item)
    if not uri:
      continue
    if not isinstance(uri, str) or not uri.startswith("viking://"):
      continue

    is_dir = extract_child_is_dir_hint(item)
    if is_dir is None:
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


def list_markdown_pages(client: OVFSClient, root_uri: str) -> List[str]:
  items = list_wiki_tree_items(client, root_uri)
  return list_markdown_pages_from_items(client, root_uri, items)


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

  lower_target = target.lower()
  blocked_schemes = (
      "mailto:",
      "tel:",
      "javascript:",
      "data:",
      "viking://",
      "http://",
      "https://",
  )
  if lower_target.startswith(blocked_schemes):
    return None

  target = target.split("#", 1)[0].split("?", 1)[0].strip()
  if not target:
    return None
  if target.startswith("#"):
    return None

  if target.startswith("wiki/"):
    target = target[len("wiki/"):]

  target_path = PurePosixPath(target)
  if target_path.is_absolute():
    target_path = PurePosixPath(str(target_path).lstrip("/"))

  normalized_parts: List[str] = []
  for part in target_path.parts:
    if part in ("", "."):
      continue
    if part == "..":
      if normalized_parts:
        normalized_parts.pop()
      continue
    normalized_parts.append(part)

  normalized_target = "/".join(normalized_parts)
  if not normalized_target:
    return None

  if normalized_target.endswith("/"):
    return None

  if not normalized_target.endswith(".md"):
    normalized_target = f"{normalized_target}.md"

  return normalized_target


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

    candidates.append(kb_root + "wiki/" + target)

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
    link_index: LintLinkResolutionIndex | None = None,
    precomputed_broken_links: List[Dict[str, str]] | None = None,
) -> List[Dict[str, str]]:
    del client

    if precomputed_broken_links is not None:
        return precomputed_broken_links

    if link_index is None:
        link_index = build_link_resolution_index_from_page_map(kb_root, page_map)

    _, broken = build_internal_link_graph(kb_root, page_map, link_index)
    return broken


def check_orphan_pages(
    client: OVFSClient,
    kb_root: str,
    page_map: Dict[str, str],
    link_index: LintLinkResolutionIndex | None = None,
    link_graph: Dict[str, Set[str]] | None = None,
) -> List[str]:
    del client

    if link_index is None:
        link_index = build_link_resolution_index_from_page_map(kb_root, page_map)

    if link_graph is None:
        link_graph, _ = build_internal_link_graph(kb_root, page_map, link_index)

    inbound_counts: Dict[str, int] = {uri: 0 for uri in page_map.keys()}

    for target_uris in link_graph.values():
        for target_uri in target_uris:
            if target_uri in inbound_counts:
                inbound_counts[target_uri] += 1

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


def check_nested_resource_dirs_from_items(kb_root: str, items: List[Any]) -> List[str]:
  wiki_uri = kb_root + "wiki/"
  nested_dirs: List[str] = []

  for item in items:
    uri = extract_uri_from_ls_item(item)

    if not uri or not isinstance(uri, str):
      continue
    if not uri.startswith(kb_root):
      continue

    rel_from_wiki = uri[len(wiki_uri):]
    parts = [p for p in rel_from_wiki.split("/") if p]
    if len(parts) < 2:
      continue

    for i in range(len(parts) - 1):
      if parts[i] == parts[i + 1]:
        nested_dirs.append(uri)
        break

  return sorted(set(nested_dirs))


def check_nested_resource_dirs(client: OVFSClient, kb_root: str) -> List[str]:
  wiki_uri = kb_root + "wiki/"
  items = list_wiki_tree_items(client, wiki_uri)
  return check_nested_resource_dirs_from_items(kb_root, items)


def build_report(client: OVFSClient, kb_root: str) -> Dict[str, Any]:
  wiki_root = kb_root + "wiki/"
  wiki_tree_items = list_wiki_tree_items(client, wiki_root)

  all_pages = list_markdown_pages_from_items(client, wiki_root, wiki_tree_items)
  unexpected_wiki_root_entries = check_unexpected_wiki_root_entries(client, kb_root)

  link_index = build_link_resolution_index(kb_root, wiki_tree_items, all_pages)

  page_map: Dict[str, str] = {}
  for uri in all_pages:
    try:
      page_map[uri] = client.read_text(uri)
    except Exception:
      page_map[uri] = ""

  link_graph, broken_links = build_internal_link_graph(kb_root, page_map, link_index)

  orphan_pages = check_orphan_pages(
    client,
    kb_root,
    page_map,
    link_index=link_index,
    link_graph=link_graph,
  )

  no_outbound_links = check_pages_without_outbound_links(kb_root, page_map)
  duplicate_titles = check_duplicate_titles(page_map)
  stub_pages = check_stub_pages(page_map)
  _nested_dirs = check_nested_resource_dirs_from_items(kb_root, wiki_tree_items)
  del _nested_dirs

  errors: List[str] = []
  warnings: List[str] = []

  if broken_links:
    errors.append(f"内部链接失效：{len(broken_links)}")

  if unexpected_wiki_root_entries:
    errors.append(f"wiki 根目录存在非预期条目：{len(unexpected_wiki_root_entries)}")

  if orphan_pages:
    warnings.append(f"孤立页面：{len(orphan_pages)}")

  if no_outbound_links:
    warnings.append(f"缺少出站内部链接的页面：{len(no_outbound_links)}")

  if duplicate_titles:
    warnings.append(f"页面标题重复：{len(duplicate_titles)}")

  if stub_pages:
    warnings.append(f"占位或近似空页面：{len(stub_pages)}")

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
    parser.add_argument("--config", default=None, help="Path to config JSON")
    parser.add_argument("--profile", default=None, help="Profile name")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kb_root = ""

    try:
        kb_root = build_kb_root(args.kb_name)
        config = OVFSConfig.load(config_path=args.config, profile=args.profile)

        with OVFSClient(config) as client:
            report = build_report(client, kb_root)
    except Exception as exc:
        print_json(build_error_result(exc, kb_root=kb_root), pretty=args.pretty)
        return 1

    print_json(report, pretty=args.pretty)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
