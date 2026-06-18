from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
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


WIKI_DERIVED_FILE_NAMES = {".abstract.md", ".overview.md", ".relations.json"}
BUNDLE_METADATA_FILE_NAMES = {"abstract.md"}
DERIVED_OR_METADATA_FILE_NAMES = WIKI_DERIVED_FILE_NAMES | BUNDLE_METADATA_FILE_NAMES

derivedFileNames = DERIVED_OR_METADATA_FILE_NAMES

ROOT_PAGES = {"index.md", "overview.md", "log.md"}
WIKI_SUBDIRS = {"sources", "entities", "concepts", "syntheses"}
ALLOWED_WIKI_ROOT_NAMES = ROOT_PAGES | WIKI_SUBDIRS


def stat_is_dir(stat: dict[str, Any] | None) -> bool:
  if not stat:
    return False
  if isinstance(stat.get("isDir"), bool):
    return stat["isDir"]
  if isinstance(stat.get("is_dir"), bool):
    return stat["is_dir"]
  return str(stat.get("type", "")).lower() in {"dir", "directory", "folder"}


def slugify(text: str) -> str:
  text = text.strip().lower()
  text = re.sub(r"[^\w\s-]", "", text)
  text = re.sub(r"[\s_]+", "-", text)
  text = re.sub(r"-+", "-", text)
  return text.strip("-") or "untitled"


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


def strip_openviking_hash_suffix(stem: str) -> str:
  stripped = re.sub(r"[_-]{1,2}[0-9a-fA-F]{16,64}$", "", stem)
  return stripped or stem


def candidate_source_slugs_from_raw_child_uri(uri: str) -> list[str]:
  stem = source_title_stem_from_uri(uri)
  candidates = [slugify(stem)]

  strippedStem = strip_openviking_hash_suffix(stem)
  strippedSlug = slugify(strippedStem)
  if strippedSlug not in candidates:
    candidates.append(strippedSlug)

  return candidates


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
      isDir = stat_is_dir(stat)

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


def page_log_match_tokens(client: OVFSClient, kbRoot: str, rel_path: str) -> set[str]:
  tokens = {
    f"wiki/{rel_path}".lower(),
    rel_path.lower(),
    PurePosixPath(rel_path).stem.lower(),
  }
  title = read_page_title(client, kbRoot, rel_path, PurePosixPath(rel_path).stem)
  if title:
    tokens.add(title.lower())
  return {token for token in tokens if token}


def log_contains_page_token(logText: str, token: str) -> bool:
  if "/" in token:
    return token in logText

  return bool(
    re.search(
      rf"(?<![0-9a-z\u4e00-\u9fff]){re.escape(token)}(?![0-9a-z\u4e00-\u9fff])",
      logText,
    )
  )


def source_log_match_tokens(client: OVFSClient, kbRoot: str, rel_path: str) -> set[str]:
  return page_log_match_tokens(client, kbRoot, rel_path)


def log_contains_source_token(logText: str, token: str) -> bool:
  return log_contains_page_token(logText, token)


def check_required_structure(client: OVFSClient, kbRoot: str) -> tuple[list[str], list[str]]:
  missingDirs: list[str] = []
  missingFiles: list[str] = []

  for rel in requiredDirs:
    uri = kbRoot + rel
    stat = get_uri_stat(client, uri)
    if not stat_is_dir(stat):
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


def check_page_log_coverage(
  client: OVFSClient,
  kbRoot: str,
  section_key: str,
) -> list[str]:
  if section_key not in {"sources", "syntheses"}:
    return []

  logUri = f"{kbRoot}wiki/log.md"
  canonicalLogUri = resolve_canonical_markdown_uri(client, logUri)
  if not canonicalLogUri:
    return []

  logText = client.read_text(canonicalLogUri).lower()
  pages = list_indexable_wiki_pages(client, kbRoot, section_key=section_key)[section_key]

  missingInLog: list[str] = []

  for relPath in pages:
    tokens = page_log_match_tokens(client, kbRoot, relPath)
    if any(log_contains_page_token(logText, token) for token in tokens):
      continue
    missingInLog.append(kbRoot + "wiki/" + relPath)

  return missingInLog


def check_source_log_coverage(client: OVFSClient, kbRoot: str) -> list[str]:
  return check_page_log_coverage(client, kbRoot, "sources")


def check_synthesis_log_coverage(client: OVFSClient, kbRoot: str) -> list[str]:
  return check_page_log_coverage(client, kbRoot, "syntheses")


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


def check_unexpected_wiki_root_entries(client: OVFSClient, kbRoot: str) -> list[str]:
  wikiUri = kbRoot + "wiki/"
  try:
    children = client.ls(wikiUri, recursive=False)
  except Exception:
    return []

  unexpected: list[str] = []

  for child in children:
    childUri = extract_uri_from_ls_item(child)
    if not childUri:
      continue

    name = PurePosixPath(childUri.rstrip("/")).name
    if name in ALLOWED_WIKI_ROOT_NAMES:
      continue

    unexpected.append(childUri)

  return sorted(set(unexpected))


def build_repair_recommendations(
  *,
  missingDirs: list[str],
  missingFiles: list[str],
  brokenIndexTargets: list[str],
  unindexedWikiPages: list[str],
  duplicateIndexTargets: list[str],
  missingSourceLogEntries: list[str],
  missingSynthesisLogEntries: list[str],
  rawSourcesWithoutSourcePages: list[dict[str, Any]],
  unexpectedWikiRootEntries: list[str],
) -> list[dict[str, Any]]:
  recommendations: list[dict[str, Any]] = []

  if missingDirs or missingFiles:
    recommendations.append({
      "code": "missing_structure",
      "severity": "error",
      "safe_to_auto_repair": True,
      "command": "wiki-health --repair-structure",
      "note": "创建缺失的必要目录或根页面；不删除、不移动、不覆盖已有页面。"
    })

  if brokenIndexTargets or unindexedWikiPages or duplicateIndexTargets:
    recommendations.append({
      "code": "index_drift",
      "severity": "error",
      "safe_to_auto_repair": True,
      "command": "wiki-health --repair-index",
      "note": "重建 wiki/index.md，使 managed sections 与真实 wiki 页面一致。"
    })

  if missingSourceLogEntries or missingSynthesisLogEntries:
    recommendations.append({
      "code": "log_drift",
      "severity": "warning",
      "safe_to_auto_repair": True,
      "command": "wiki-health --repair-log",
      "note": "向 wiki/log.md 追加 health-reconcile 补录记录，不伪造原始操作时间。"
    })

  if rawSourcesWithoutSourcePages:
    recommendations.append({
      "code": "raw_pending_ingest",
      "severity": "warning",
      "safe_to_auto_repair": False,
      "command": "wiki-ingest",
      "note": "raw source candidate 需要用户确认后执行 ingest；wiki-health 不调用 LLM。"
    })

  if unexpectedWikiRootEntries:
    recommendations.append({
      "code": "unexpected_wiki_root_entries",
      "severity": "warning",
      "safe_to_auto_repair": False,
      "command": "manual_move_or_delete",
      "note": "wiki/ 根目录的非标准条目需要人工判断应迁移到哪个 section。"
    })

  return recommendations


def build_initial_key_page_content(fileUri: str) -> str:
  if fileUri.endswith("wiki/index.md"):
    return (
      "# 索引\n\n"
      "- [概览](./overview.md)\n"
      "- [操作日志](./log.md)\n\n"
      "## 资料来源\n\n"
      "## 实体\n\n"
      "## 概念\n\n"
      "## 综合结论\n"
    )

  if fileUri.endswith("wiki/overview.md"):
    return (
      "# 概览\n\n"
      "当前知识库概览尚未生成。请在完成 source ingest 后，"
      "根据知识库内容补充主要主题、关键实体、核心概念和已知缺口。\n"
    )

  if fileUri.endswith("wiki/log.md"):
    return "# 操作日志\n\n"

  return ""


def repair_structure(client: OVFSClient, kbRoot: str) -> dict[str, Any]:
  createdDirs: list[str] = []
  createdFiles: list[str] = []
  skippedConflicts: list[str] = []

  for rel in requiredDirs:
    uri = kbRoot + rel
    stat = get_uri_stat(client, uri)

    if stat and stat_is_dir(stat):
      continue

    if stat and not stat_is_dir(stat):
      skippedConflicts.append(uri)
      continue

    client.mkdir(uri, description="llm-wiki health repair")
    createdDirs.append(uri)

  for fileUri in required_wiki_pages(kbRoot):
    canonicalUri = resolve_canonical_markdown_uri(client, fileUri)
    if canonicalUri:
      continue

    targetUri, shouldCreate = resolve_markdown_write_target_uri(client, fileUri)
    client.write_text(
      targetUri,
      build_initial_key_page_content(fileUri),
      create=shouldCreate,
      wait=True,
    )
    createdFiles.append(targetUri)

  return {
    "type": "repair_structure",
    "structure_repaired": True,
    "created_dirs": createdDirs,
    "created_files": createdFiles,
    "skipped_conflicts": skippedConflicts,
  }


def repair_index(client: OVFSClient, kbRoot: str) -> dict[str, Any]:
  indexUri = kbRoot + "wiki/index.md"
  canonicalIndexUri = resolve_canonical_markdown_uri(client, indexUri)
  previousIndexText = client.read_text(canonicalIndexUri) if canonicalIndexUri else ""

  repairedIndexText = rebuild_index_text(
    client,
    kbRoot,
    previousIndexText,
    touched_entries=None,
  )

  indexWriteUri, indexShouldCreate = resolve_markdown_write_target_uri(client, indexUri)
  client.write_text(indexWriteUri, repairedIndexText, create=indexShouldCreate, wait=True)

  return {
    "type": "repair_index",
    "index_rebuilt": True,
    "index_uri": indexUri,
    "index_write_uri": indexWriteUri,
  }


def now_iso() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rel_path_from_wiki_page_uri(kbRoot: str, pageUri: str) -> str | None:
  prefix = kbRoot.rstrip("/") + "/wiki/"
  if not pageUri.startswith(prefix):
    return None
  return pageUri[len(prefix):]


def build_health_reconcile_log_entry(kind: str, relPath: str, title: str) -> str:
  return (
    f"已补录 {kind} 页面: {title}; "
    f"page=wiki/{relPath}; "
    f"note=health-reconcile，根据远端现有页面补录，不代表原始操作时间"
  )


def repair_log(client: OVFSClient, kbRoot: str) -> dict[str, Any]:
  logUri = kbRoot + "wiki/log.md"
  createdInitialLog = False

  canonicalLogUri = resolve_canonical_markdown_uri(client, logUri)

  if not canonicalLogUri:
    logWriteUri, shouldCreate = resolve_markdown_write_target_uri(client, logUri)
    initialLogText = build_initial_key_page_content(logUri)
    client.write_text(logWriteUri, initialLogText, create=shouldCreate, wait=True)
    createdInitialLog = True
    canonicalLogUri = resolve_canonical_markdown_uri(client, logUri) or logWriteUri

  currentLogText = client.read_text(canonicalLogUri)

  missingSourceLogEntries = check_source_log_coverage(client, kbRoot)
  missingSynthesisLogEntries = check_synthesis_log_coverage(client, kbRoot)

  appendedEntries: list[str] = []

  for pageUri in missingSourceLogEntries:
    relPath = rel_path_from_wiki_page_uri(kbRoot, pageUri)
    if not relPath:
      continue
    title = read_page_title(client, kbRoot, relPath, PurePosixPath(relPath).stem)
    entry = build_health_reconcile_log_entry("source", relPath, title)
    appendedEntries.append(f"- {now_iso()} - {entry}")

  for pageUri in missingSynthesisLogEntries:
    relPath = rel_path_from_wiki_page_uri(kbRoot, pageUri)
    if not relPath:
      continue
    title = read_page_title(client, kbRoot, relPath, PurePosixPath(relPath).stem)
    entry = build_health_reconcile_log_entry("synthesis", relPath, title)
    appendedEntries.append(f"- {now_iso()} - {entry}")

  if not appendedEntries:
    return {
      "type": "repair_log",
      "log_repaired": createdInitialLog,
      "created_initial_log": createdInitialLog,
      "log_uri": logUri,
      "log_write_uri": canonicalLogUri if createdInitialLog else None,
      "appended_entries": [],
    }

  newLogText = currentLogText.rstrip() + "\n" + "\n".join(appendedEntries) + "\n"

  logWriteUri, shouldCreate = resolve_markdown_write_target_uri(client, logUri)
  client.write_text(logWriteUri, newLogText, create=shouldCreate, wait=True)

  return {
    "type": "repair_log",
    "log_repaired": True,
    "created_initial_log": createdInitialLog,
    "log_uri": logUri,
    "log_write_uri": logWriteUri,
    "appended_entries": appendedEntries,
  }


def list_raw_source_candidates(client: OVFSClient, kbRoot: str) -> list[dict[str, Any]]:
  rawUri = kbRoot + "raw/"
  try:
    children = client.ls(rawUri, recursive=False)
  except Exception:
    return []

  candidates: list[dict[str, Any]] = []

  for child in children:
    childUri = extract_uri_from_ls_item(child)
    if not childUri:
      continue

    name = PurePosixPath(childUri.rstrip("/")).name
    if name in DERIVED_OR_METADATA_FILE_NAMES:
      continue

    if isinstance(child, dict) and isinstance(child.get("isDir"), bool):
      isDir = child["isDir"]
    else:
      stat = get_uri_stat(client, childUri)
      isDir = stat_is_dir(stat)

    if isDir:
      candidates.append({
        "raw_uri": childUri,
        "is_dir": True,
        "source_slug_candidates": candidate_source_slugs_from_raw_child_uri(childUri),
      })
      continue

    if childUri.lower().endswith(".md"):
      candidates.append({
        "raw_uri": childUri,
        "is_dir": False,
        "source_slug_candidates": candidate_source_slugs_from_raw_child_uri(childUri),
      })

  return candidates


def check_raw_sources_without_source_pages(
  client: OVFSClient,
  kbRoot: str,
  rawSourceCandidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
  existingSources = list_indexable_wiki_pages(
    client,
    kbRoot,
    section_key="sources",
  )["sources"]

  existingSourceSlugs = {
    PurePosixPath(relPath).stem
    for relPath in existingSources
  }

  candidates = rawSourceCandidates
  if candidates is None:
    candidates = list_raw_source_candidates(client, kbRoot)

  results: list[dict[str, Any]] = []

  for candidate in candidates:
    candidateSlugs = candidate["source_slug_candidates"]
    if any(slug in existingSourceSlugs for slug in candidateSlugs):
      continue

    primarySlug = candidateSlugs[0]
    results.append({
      "raw_uri": candidate["raw_uri"],
      "is_dir": candidate["is_dir"],
      "source_slug_candidates": candidateSlugs,
      "expected_source_page": kbRoot + f"wiki/sources/{primarySlug}.md",
    })

  return results


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
  unexpectedWikiRootEntries = check_unexpected_wiki_root_entries(client, kbRoot)
  rawSourceCandidates = list_raw_source_candidates(client, kbRoot)
  rawSourcesWithoutSourcePages = check_raw_sources_without_source_pages(
    client,
    kbRoot,
    rawSourceCandidates=rawSourceCandidates,
  )
  missingSynthesisLogEntries = check_synthesis_log_coverage(client, kbRoot)

  repairRecommendations = build_repair_recommendations(
    missingDirs=missingDirs,
    missingFiles=missingFiles,
    brokenIndexTargets=brokenIndexTargets,
    unindexedWikiPages=unindexedWikiPages,
    duplicateIndexTargets=duplicateIndexTargets,
    missingSourceLogEntries=missingSourceLogEntries,
    missingSynthesisLogEntries=missingSynthesisLogEntries,
    rawSourcesWithoutSourcePages=rawSourcesWithoutSourcePages,
    unexpectedWikiRootEntries=unexpectedWikiRootEntries,
  )

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

  if unexpectedWikiRootEntries:
    warnings.append(f"wiki/ 根目录存在不符合 schema 的条目：{len(unexpectedWikiRootEntries)}")

  if rawSourcesWithoutSourcePages:
    warnings.append(f"raw/ 下存在尚未 ingest 的 source candidate：{len(rawSourcesWithoutSourcePages)}")

  if missingSynthesisLogEntries:
    warnings.append(f"综合结论页面未记录到 wiki/log.md：{len(missingSynthesisLogEntries)}")

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
      "missing_source_log_entries": len(missingSourceLogEntries),
      "missing_synthesis_log_entries": len(missingSynthesisLogEntries),
      "unexpected_wiki_root_entries": len(unexpectedWikiRootEntries),
      "raw_source_candidates": len(rawSourceCandidates),
      "raw_sources_without_source_pages": len(rawSourcesWithoutSourcePages),
      "nested_resource_dirs": len(nestedDirs),
      "repairable_issues": sum(1 for item in repairRecommendations if item["safe_to_auto_repair"]),
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
      "unexpected_wiki_root_entries": unexpectedWikiRootEntries,
      "raw_source_candidates": rawSourceCandidates,
      "raw_sources_without_source_pages": rawSourcesWithoutSourcePages,
      "missing_synthesis_log_entries": missingSynthesisLogEntries,
      "repair_recommendations": repairRecommendations,
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

  parser.add_argument(
    "--repair-structure",
    action="store_true",
    help="创建缺失的必要目录和缺失的根页面；不删除、不移动、不覆盖已有页面、不调用 LLM。",
  )

  parser.add_argument(
    "--repair-log",
    action="store_true",
    help="为已存在但未被 log 覆盖的 source/synthesis 页面追加 health-reconcile 补录记录。",
  )

  parser.add_argument(
    "--repair-all",
    action="store_true",
    help="执行所有安全修复：repair-structure + repair-index + repair-log。",
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

    repairStructure = bool(args.repair_structure or args.repair_all)
    repairIndex = bool(args.repair_index or args.repair_all)
    repairLog = bool(args.repair_log or args.repair_all)

    with OVFSClient(config) as client:
      repairInfo = {
        "requested": {
          "repair_structure": repairStructure,
          "repair_index": repairIndex,
          "repair_log": repairLog,
          "repair_all": bool(args.repair_all),
        },
        "actions": [],
      }

      if repairStructure:
        repairInfo["actions"].append(repair_structure(client, kbRoot))

      if repairIndex:
        repairInfo["actions"].append(repair_index(client, kbRoot))

      if repairLog:
        repairInfo["actions"].append(repair_log(client, kbRoot))

      report = build_report(client, kbRoot)

      if repairStructure or repairIndex or repairLog:
        report["repair"] = repairInfo
  except Exception as exc:
    print_json(build_error_result(exc, kb_root=kbRoot), pretty=args.pretty)
    return 1

  print_json(report, pretty=args.pretty)
  return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
  sys.exit(main())
