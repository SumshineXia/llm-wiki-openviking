from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

try:
  from common import build_error_result, build_kb_root, print_json
  from ovfs import OVFSClient, OVFSConfig, OVFSError, OVFSHTTPError
  from wiki_index import (
    normalize_relative_wiki_target,
    resolve_canonical_markdown_uri,
    resolve_markdown_write_target_uri,
    list_indexable_wiki_pages,
    canonical_index_rel_path_from_uri,
    rebuild_index_text,
    read_page_title,
  )
except ModuleNotFoundError:
  scriptDir = Path(__file__).resolve().parent
  if str(scriptDir) not in sys.path:
    sys.path.insert(0, str(scriptDir))
  from common import build_error_result, build_kb_root, print_json
  from ovfs import OVFSClient, OVFSConfig, OVFSError, OVFSHTTPError
  from wiki_index import (
    normalize_relative_wiki_target,
    resolve_canonical_markdown_uri,
    resolve_markdown_write_target_uri,
    list_indexable_wiki_pages,
    canonical_index_rel_path_from_uri,
    rebuild_index_text,
    read_page_title,
  )


requiredDirs = [
  "raw/",
  "wiki/",
  "wiki/sources/",
  "wiki/entities/",
  "wiki/concepts/",
  "wiki/syntheses/",
  "graph/",
]


def required_wiki_pages(kbRoot: str) -> list[str]:
  return [
    f"{kbRoot}wiki/index.md",
    f"{kbRoot}wiki/overview.md",
    f"{kbRoot}wiki/log.md",
  ]


derivedFileNames = {".abstract.md", ".overview.md", ".relations.json"}


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


def extract_index_links(indexText: str) -> set[str]:
  return set(extract_index_link_occurrences(indexText))


def extract_index_link_occurrences(indexText: str) -> list[str]:
  results: list[str] = []

  wikilinkPattern = re.compile(r"\[\[([^\]]+)\]\]")
  markdownLinkPattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

  for raw in wikilinkPattern.findall(indexText):
    normalized = normalize_relative_wiki_target(raw.split("|", 1)[0])
    if normalized:
      results.append(normalized)

  for raw in markdownLinkPattern.findall(indexText):
    normalized = normalize_relative_wiki_target(raw)
    if normalized:
      results.append(normalized)

  return results


def is_meaningful_page(text: str) -> bool:
  stripped = text.strip()
  if not stripped:
    return False

  lines = [line.strip() for line in stripped.splitlines() if line.strip()]
  if len(lines) <= 1:
    return False

  contentChars = sum(len(line) for line in lines)
  return contentChars >= 30


def get_uri_stat(client: OVFSClient, uri: str) -> dict[str, Any] | None:
  try:
    return client.stat(uri)
  except OVFSHTTPError as exc:
    message = str(exc).lower()
    if "404" in message or "not found" in message:
      return None
    raise


def list_markdown_pages(client: OVFSClient, rootUri: str) -> list[str]:
  try:
    items = client.ls(rootUri, recursive=True)
  except Exception:
    return []

  uris: list[str] = []
  for item in items:
    uri = extract_uri_from_ls_item(item)
    if not uri:
      continue
    if not uri.startswith("viking://"):
      continue
    if PurePosixPath(uri).name in derivedFileNames:
      continue

    if isinstance(item, dict) and isinstance(item.get("isDir"), bool):
      isDir = item["isDir"]
    else:
      stat = get_uri_stat(client, uri)
      isDir = bool(stat and stat.get("isDir", False))

    if isDir:
      continue

    if uri.endswith(".md"):
      uris.append(uri)

  seen: set[str] = set()
  deduped: list[str] = []
  for uri in uris:
    if uri not in seen:
      seen.add(uri)
      deduped.append(uri)

  return deduped


def check_duplicate_index_targets(indexText: str) -> list[str]:
  seen: set[str] = set()
  duplicates: list[str] = []

  for relPath in extract_index_link_occurrences(indexText):
    if relPath in seen:
      if relPath not in duplicates:
        duplicates.append(relPath)
      continue
    seen.add(relPath)

  return duplicates


def check_unindexed_wiki_pages(client: OVFSClient, kbRoot: str, linked_targets: set[str]) -> list[str]:
  unindexedPages: list[str] = []

  for relPaths in list_indexable_wiki_pages(client, kbRoot).values():
    for relPath in relPaths:
      if relPath not in linked_targets:
        unindexedPages.append(kbRoot + "wiki/" + relPath)

  return unindexedPages


def source_log_match_tokens(client: OVFSClient, kbRoot: str, rel_path: str) -> set[str]:
  tokens = {
    f"wiki/{rel_path}".lower(),
    rel_path.lower(),
    PurePosixPath(rel_path).stem.lower(),
  }
  title = read_page_title(client, kbRoot, rel_path, PurePosixPath(rel_path).stem)
  if title:
    tokens.add(title.lower())
  return {token for token in tokens if token}


def log_contains_source_token(logText: str, token: str) -> bool:
  if "/" in token:
    return token in logText

  return bool(re.search(rf"(?<![0-9a-z\u4e00-\u9fff]){re.escape(token)}(?![0-9a-z\u4e00-\u9fff])", logText))


def check_required_structure(client: OVFSClient, kbRoot: str) -> tuple[list[str], list[str]]:
  missingDirs: list[str] = []
  missingFiles: list[str] = []

  for rel in requiredDirs:
    uri = kbRoot + rel
    stat = get_uri_stat(client, uri)
    if not stat or not stat.get("isDir", False):
      missingDirs.append(uri)

  for uri in required_wiki_pages(kbRoot):
    canonicalUri = resolve_canonical_markdown_uri(client, uri)
    if not canonicalUri:
      missingFiles.append(uri)

  return missingDirs, missingFiles


def check_empty_key_pages(client: OVFSClient, kbRoot: str) -> list[str]:
  emptyPages: list[str] = []

  for uri in required_wiki_pages(kbRoot):
    canonicalUri = resolve_canonical_markdown_uri(client, uri)
    if not canonicalUri:
      continue
    try:
      text = client.read_text(canonicalUri)
    except Exception:
      emptyPages.append(uri)
      continue
    if not is_meaningful_page(text):
      emptyPages.append(uri)

  return emptyPages


def check_index_targets(client: OVFSClient, kbRoot: str) -> tuple[list[str], list[str]]:
  indexUri = f"{kbRoot}wiki/index.md"
  canonicalIndexUri = resolve_canonical_markdown_uri(client, indexUri)
  if not canonicalIndexUri:
    return [], [indexUri]

  try:
    indexText = client.read_text(canonicalIndexUri)
  except Exception:
    return [], [indexUri]

  linkedTargets = sorted(extract_index_links(indexText))

  broken: list[str] = []
  for rel in linkedTargets:
    normalizedPath = PurePosixPath("wiki") / rel
    normalizedPath = PurePosixPath(normalizedPath).as_posix()
    normalizedParts: list[str] = []
    for part in PurePosixPath(normalizedPath).parts:
      if part in ("", "."):
        continue
      if part == "..":
        if normalizedParts:
          normalizedParts.pop()
        continue
      normalizedParts.append(part)
    targetUri = kbRoot + PurePosixPath(*normalizedParts).as_posix()
    canonicalTargetUri = resolve_canonical_markdown_uri(client, targetUri)
    if not canonicalTargetUri:
      broken.append(targetUri)

  return linkedTargets, broken


def check_source_log_coverage(client: OVFSClient, kbRoot: str) -> list[str]:
  logUri = f"{kbRoot}wiki/log.md"

  canonicalLogUri = resolve_canonical_markdown_uri(client, logUri)
  if not canonicalLogUri:
    return []

  logText = client.read_text(canonicalLogUri).lower()
  sourcePages = list_indexable_wiki_pages(client, kbRoot, section_key="sources")["sources"]

  missingInLog: list[str] = []
  for relPath in sourcePages:
    if any(log_contains_source_token(logText, token) for token in source_log_match_tokens(client, kbRoot, relPath)):
      continue
    missingInLog.append(kbRoot + "wiki/" + relPath)

  return missingInLog


def check_nested_resource_dirs(client: OVFSClient, kbRoot: str) -> list[str]:
    wikiUri = kbRoot + "wiki/"
    try:
        items = client.ls(wikiUri, recursive=True)
    except Exception:
        return []

    nestedDirs: list[str] = []

    for item in items:
        uri: str | None = None

        if isinstance(item, str):
            uri = item
        elif isinstance(item, dict):
            uri = item.get("uri") or item.get("path")

        if not uri or not isinstance(uri, str):
            continue
        if not uri.startswith(kbRoot):
            continue

        relFromWiki = uri[len(wikiUri):]

        parts = [p for p in relFromWiki.split("/") if p]
        if len(parts) < 2:
            continue

        for i in range(len(parts) - 1):
            if parts[i] == parts[i + 1]:
                nestedDirs.append(uri)
                break

    return sorted(set(nestedDirs))


def build_report(client: OVFSClient, kbRoot: str) -> dict[str, Any]:
  missingDirs, missingFiles = check_required_structure(client, kbRoot)
  emptyKeyPages = check_empty_key_pages(client, kbRoot)
  canonicalIndexUri = resolve_canonical_markdown_uri(client, kbRoot + "wiki/index.md")
  indexText = client.read_text(canonicalIndexUri) if canonicalIndexUri else ""
  indexLinkOccurrences = extract_index_link_occurrences(indexText)
  duplicateIndexTargets = check_duplicate_index_targets(indexText)
  linkedTargets, brokenIndexTargets = check_index_targets(client, kbRoot)
  unindexedWikiPages = check_unindexed_wiki_pages(client, kbRoot, set(linkedTargets))
  missingSourceLogEntries = check_source_log_coverage(client, kbRoot)
  nestedDirs = check_nested_resource_dirs(client, kbRoot)

  allWikiPages = list_markdown_pages(client, kbRoot + "wiki/")
  allSourcePages = list_markdown_pages(client, kbRoot + "wiki/sources/")
  allEntityPages = list_markdown_pages(client, kbRoot + "wiki/entities/")
  allConceptPages = list_markdown_pages(client, kbRoot + "wiki/concepts/")
  allSynthesisPages = list_markdown_pages(client, kbRoot + "wiki/syntheses/")

  errors: list[str] = []
  warnings: list[str] = []

  if missingDirs:
    errors.append(f"缺少必要目录：{len(missingDirs)}")
  if missingFiles:
    errors.append(f"缺少必要根页面文件：{len(missingFiles)}")
  if emptyKeyPages:
    errors.append(f"关键页面为空或无效：{len(emptyKeyPages)}")
  if brokenIndexTargets:
    errors.append(f"wiki/index.md 引用的内部链接失效：{len(brokenIndexTargets)}")
  if unindexedWikiPages:
    errors.append(f"存在未被 wiki/index.md 收录的页面：{len(unindexedWikiPages)}")
  if not allSourcePages:
    warnings.append("wiki/sources/ 下未发现来源页面")
  if duplicateIndexTargets:
    warnings.append(f"wiki/index.md 存在重复内部链接目标：{len(duplicateIndexTargets)}")

  if not linkedTargets:
    warnings.append("wiki/index.md 中未解析到内部链接")
  if not allEntityPages and not allConceptPages and not allSynthesisPages:
    warnings.append("未发现实体、概念或综合结论页面")
  if len(allWikiPages) <= 3:
    warnings.append("Wiki 可能仅包含根页面")

  if missingSourceLogEntries:
    warnings.append(
      f"来源页面未记录到 wiki/log.md：{len(missingSourceLogEntries)}"
    )

  status = "ok" if not errors else "error"

  return {
    "status": status,
    "kb_root": kbRoot,
    "summary": {
      "wiki_pages": len(allWikiPages),
      "source_pages": len(allSourcePages),
      "entity_pages": len(allEntityPages),
      "concept_pages": len(allConceptPages),
      "synthesis_pages": len(allSynthesisPages),
      "index_links": len(linkedTargets),
      "index_link_occurrences": len(indexLinkOccurrences),
      "duplicate_index_targets": len(duplicateIndexTargets),
      "unindexed_wiki_pages": len(unindexedWikiPages),
    },
    "errors": errors,
    "warnings": warnings,
    "details": {
      "index_link_occurrences": indexLinkOccurrences,
      "duplicate_index_targets": duplicateIndexTargets,
      "missing_dirs": missingDirs,
      "missing_files": missingFiles,
      "empty_key_pages": emptyKeyPages,
      "broken_index_targets": brokenIndexTargets,
      "unindexed_wiki_pages": unindexedWikiPages,
      "missing_source_log_entries": missingSourceLogEntries,
      "nested_resource_dirs": nestedDirs,
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
  parser.add_argument(
    "--repair-index",
    action="store_true",
    help="重建 wiki/index.md，不删除页面，不调用 LLM",
  )
  parser.add_argument("--config", default=None, help="Path to config JSON")
  parser.add_argument("--profile", default=None, help="Profile name")
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  kbRoot = ""

  try:
    kbRoot = build_kb_root(args.kb_name)
    config = OVFSConfig.load(config_path=args.config, profile=args.profile)

    with OVFSClient(config) as client:
      repairInfo = None
      if args.repair_index:
        indexUri = kbRoot + "wiki/index.md"
        canonicalIndexUri = resolve_canonical_markdown_uri(client, indexUri)
        previousIndexText = client.read_text(canonicalIndexUri) if canonicalIndexUri else ""
        repairedIndexText = rebuild_index_text(client, kbRoot, previousIndexText, touched_entries=None)
        indexWriteUri, indexShouldCreate = resolve_markdown_write_target_uri(client, indexUri)
        client.write_text(indexWriteUri, repairedIndexText, create=indexShouldCreate, wait=True)
        repairInfo = {
          "index_rebuilt": True,
          "index_uri": indexUri,
          "index_write_uri": indexWriteUri,
        }
      report = build_report(client, kbRoot)
      if repairInfo:
        report["repair"] = repairInfo
  except Exception as exc:
    print_json(build_error_result(exc, kb_root=kbRoot), pretty=args.pretty)
    return 1

  print_json(report, pretty=args.pretty)
  return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
  sys.exit(main())
