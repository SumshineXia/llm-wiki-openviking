from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from ovfs import OVFSHTTPError


SECTION_ORDER = ("sources", "entities", "concepts", "syntheses")

SECTION_DIRS = {
  "sources": "sources/",
  "entities": "entities/",
  "concepts": "concepts/",
  "syntheses": "syntheses/",
}

CANONICAL_SECTION_HEADINGS = {
  "sources": "## 资料来源",
  "entities": "## 实体",
  "concepts": "## 概念",
  "syntheses": "## 综合结论",
}

SECTION_HEADING_ALIASES = {
  "sources": ("## 资料来源", "## Sources"),
  "entities": ("## 实体", "## Entities"),
  "concepts": ("## 概念", "## Concepts"),
  "syntheses": ("## 综合结论", "## Syntheses"),
}

WIKI_DERIVED_FILE_NAMES = {".abstract.md", ".overview.md", ".relations.json"}
BUNDLE_METADATA_FILE_NAMES = {"abstract.md"}

_HEADING_TO_SECTION_KEY = {
  heading: sectionKey
  for sectionKey, headings in SECTION_HEADING_ALIASES.items()
  for heading in headings
}

_H1_PATTERN = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
_WIKI_LINK_BULLET_PATTERN = re.compile(r"^\s*-\s*\[\[([^\]]+)\]\]\s*-\s*(.+?)\s*$")
_MARKDOWN_LINK_BULLET_PATTERN = re.compile(r"^\s*-\s*\[([^\]]+)\]\(([^)]+)\)\s*$")


@dataclass
class IndexSectionBlock:
  heading: str | None
  section_key: str | None
  body_lines: list[str]


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


def _is_dir_stat(stat: dict[str, Any]) -> bool:
  if isinstance(stat.get("isDir"), bool):
    return stat["isDir"]
  if isinstance(stat.get("is_dir"), bool):
    return stat["is_dir"]
  return str(stat.get("type", "")).lower() in {"dir", "directory", "folder"}


def get_uri_stat(client: Any, uri: str) -> dict[str, Any] | None:
  try:
    return client.stat(uri)
  except OVFSHTTPError as exc:
    message = str(exc).lower()
    if "404" in message or "not found" in message:
      return None
    raise


def expected_content_child_uri(uri: str) -> str:
  normalizedUri = uri.rstrip("/")
  basename = PurePosixPath(normalizedUri).name
  return f"{normalizedUri}/{basename}"


def _extract_child_is_dir_hint(item: Any) -> bool | None:
  if not isinstance(item, dict):
    return None
  if isinstance(item.get("isDir"), bool):
    return item["isDir"]
  if isinstance(item.get("is_dir"), bool):
    return item["is_dir"]
  if str(item.get("type", "")).lower() in {"dir", "directory", "folder"}:
    return True
  return None


def find_direct_content_child(client: Any, uri: str, extensions: tuple[str, ...] = (".md",)) -> str | None:
  targetUri = uri.rstrip("/") + "/"
  try:
    children = client.ls(targetUri, recursive=False)
  except OVFSHTTPError as exc:
    message = str(exc).lower()
    if "404" in message or "not found" in message:
      return None
    raise

  candidates: list[str] = []
  sameNameUri = expected_content_child_uri(uri)

  for child in children:
    childUri = extract_uri_from_ls_item(child)
    if not childUri:
      continue

    name = PurePosixPath(childUri.rstrip("/")).name
    if name in WIKI_DERIVED_FILE_NAMES:
      continue
    if name in BUNDLE_METADATA_FILE_NAMES:
      continue
    if not name.endswith(extensions):
      continue

    childIsDir = _extract_child_is_dir_hint(child)
    if childIsDir is None:
      childStat = get_uri_stat(client, childUri)
      childIsDir = bool(childStat and _is_dir_stat(childStat))
    if childIsDir:
      continue

    candidates.append(childUri)

  for candidate in candidates:
    if candidate.rstrip("/") == sameNameUri:
      return candidate

  for candidate in candidates:
    if PurePosixPath(candidate).name.startswith("tmp"):
      return candidate

  return candidates[0] if candidates else None


def resolve_canonical_markdown_uri(client: Any, uri: str) -> str | None:
  stat = get_uri_stat(client, uri)
  if not stat:
    return None
  if not _is_dir_stat(stat):
    return uri

  directChild = find_direct_content_child(client, uri, extensions=(".md",))
  if directChild:
    return directChild

  sameNameUri = expected_content_child_uri(uri)
  sameNameStat = get_uri_stat(client, sameNameUri)
  if sameNameStat and not _is_dir_stat(sameNameStat):
    return sameNameUri

  return None


def resolve_markdown_write_target_uri(client: Any, uri: str) -> tuple[str, bool]:
  stat = get_uri_stat(client, uri)
  if not stat:
    return uri, True
  if not _is_dir_stat(stat):
    return uri, False

  sameNameUri = expected_content_child_uri(uri)
  sameNameStat = get_uri_stat(client, sameNameUri)
  if sameNameStat and not _is_dir_stat(sameNameStat):
    return sameNameUri, False

  directChild = find_direct_content_child(client, uri, extensions=(".md",))
  if directChild:
    return directChild, False

  return sameNameUri, True


def normalize_relative_wiki_target(target: str) -> str | None:
  normalizedTarget = target.strip()
  if not normalizedTarget:
    return None

  lowered = normalizedTarget.lower()
  if lowered.startswith("http://") or lowered.startswith("https://"):
    return None
  if normalizedTarget.startswith("#"):
    return None

  normalizedTarget = normalizedTarget.split("#", 1)[0].split("?", 1)[0].strip()
  if normalizedTarget.startswith("wiki/"):
    normalizedTarget = normalizedTarget[len("wiki/"):]
  normalizedTarget = normalizedTarget.lstrip("/")
  if not normalizedTarget or normalizedTarget.endswith("/"):
    return None

  parts: list[str] = []
  for part in PurePosixPath(normalizedTarget).parts:
    if part in ("", "."):
      continue
    if part == "..":
      if parts:
        parts.pop()
      continue
    parts.append(part)

  if not parts:
    return None

  relPath = PurePosixPath(*parts).as_posix()
  if not relPath.endswith(".md"):
    relPath = f"{relPath}.md"
  return relPath


def canonical_index_rel_path_from_uri(kb_root: str, uri: str) -> str | None:
  normalizedKbRoot = kb_root.rstrip("/") + "/"
  wikiRoot = normalizedKbRoot + "wiki/"
  if not uri.startswith(wikiRoot):
    return None

  relPath = uri[len(wikiRoot):].rstrip("/")
  if not relPath:
    return None

  parts = [part for part in PurePosixPath(relPath).parts if part not in ("", ".")]
  if not parts:
    return None

  for index, part in enumerate(parts):
    if part.endswith(".md"):
      return PurePosixPath(*parts[:index + 1]).as_posix()

  return None


def _natural_sort_key(text: str) -> list[Any]:
  return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def list_indexable_wiki_pages(
  client: Any,
  kb_root: str,
  section_key: str | None = None,
) -> dict[str, list[str]]:
  normalizedKbRoot = kb_root.rstrip("/") + "/"
  if section_key is None:
    targetSections = SECTION_ORDER
  elif section_key in SECTION_ORDER:
    targetSections = (section_key,)
  else:
    return {section_key: []}

  pagesBySection = {currentSectionKey: [] for currentSectionKey in targetSections}
  seenBySection = {currentSectionKey: set() for currentSectionKey in targetSections}

  for sectionKey in targetSections:
    rootUri = normalizedKbRoot + "wiki/" + SECTION_DIRS[sectionKey]
    try:
      items = client.ls(rootUri, recursive=True)
    except OVFSHTTPError as exc:
      message = str(exc).lower()
      if "404" in message or "not found" in message:
        continue
      raise

    for item in items:
      uri = extract_uri_from_ls_item(item)
      if not uri or not uri.startswith("viking://"):
        continue

      isDir = _extract_child_is_dir_hint(item)
      if isDir is None:
        stat = get_uri_stat(client, uri)
        isDir = bool(stat and _is_dir_stat(stat))
      if isDir:
        continue

      name = PurePosixPath(uri.rstrip("/")).name
      if name in WIKI_DERIVED_FILE_NAMES:
        continue
      if not uri.endswith(".md"):
        continue

      relPath = canonical_index_rel_path_from_uri(kb_root, uri)
      if not relPath or not relPath.startswith(SECTION_DIRS[sectionKey]):
        continue
      if relPath in seenBySection[sectionKey]:
        continue

      seenBySection[sectionKey].add(relPath)
      pagesBySection[sectionKey].append(relPath)

  for sectionKey in targetSections:
    pagesBySection[sectionKey].sort(key=_natural_sort_key)

  return pagesBySection


def detect_existing_section_headings(index_text: str) -> dict[str, str]:
  headings: dict[str, str] = {}
  for block in split_index_into_blocks(index_text):
    if block.section_key and block.heading and block.section_key not in headings:
      headings[block.section_key] = block.heading
  return headings


def parse_index_bullet_link_and_title(line: str) -> tuple[str, str] | None:
  wikiMatch = _WIKI_LINK_BULLET_PATTERN.match(line)
  if wikiMatch:
    rawTarget = wikiMatch.group(1).split("|", 1)[0].strip()
    title = wikiMatch.group(2).strip()
    normalizedTarget = normalize_relative_wiki_target(rawTarget)
    if normalizedTarget and title:
      return normalizedTarget, title

  markdownMatch = _MARKDOWN_LINK_BULLET_PATTERN.match(line)
  if markdownMatch:
    title = markdownMatch.group(1).strip()
    normalizedTarget = normalize_relative_wiki_target(markdownMatch.group(2))
    if normalizedTarget and title:
      return normalizedTarget, title

  return None


def parse_managed_index_bullet(line: str) -> tuple[str, str, str] | None:
  parsed = parse_index_bullet_link_and_title(line)
  if not parsed:
    return None

  relPath, title = parsed
  parts = PurePosixPath(relPath).parts
  if not parts:
    return None

  sectionKey = parts[0]
  if sectionKey not in SECTION_ORDER:
    return None

  return sectionKey, relPath, title


def parse_index_entry_map(index_text: str) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
  entryMap = {sectionKey: {} for sectionKey in SECTION_ORDER}
  entryOrder = {sectionKey: [] for sectionKey in SECTION_ORDER}

  for block in split_index_into_blocks(index_text):
    if not block.section_key:
      continue
    for line in block.body_lines:
      parsed = parse_managed_index_bullet(line)
      if not parsed:
        continue
      sectionKey, relPath, title = parsed
      if sectionKey != block.section_key:
        continue
      if relPath not in entryOrder[sectionKey]:
        entryOrder[sectionKey].append(relPath)
      entryMap[sectionKey][relPath] = title

  return entryMap, entryOrder


def extract_title_from_markdown(markdown_text: str) -> str | None:
  match = _H1_PATTERN.search(markdown_text)
  if not match:
    return None
  title = match.group(1).strip()
  return title or None


def read_page_title(client: Any, kb_root: str, rel_path: str, fallback: str) -> str:
  uri = kb_root.rstrip("/") + "/wiki/" + rel_path
  canonicalUri = resolve_canonical_markdown_uri(client, uri)
  if not canonicalUri:
    return fallback

  try:
    markdownText = client.read_text(canonicalUri)
  except Exception:
    return fallback

  title = extract_title_from_markdown(markdownText)
  if title:
    return title

  return fallback


def split_index_into_blocks(index_text: str) -> list[IndexSectionBlock]:
  blocks: list[IndexSectionBlock] = []
  currentHeading: str | None = None
  currentBodyLines: list[str] = []

  for line in index_text.splitlines(keepends=True):
    strippedLine = line.rstrip("\r\n")
    if strippedLine.startswith("## "):
      blocks.append(IndexSectionBlock(currentHeading, _HEADING_TO_SECTION_KEY.get(currentHeading), currentBodyLines))
      currentHeading = strippedLine
      currentBodyLines = []
      continue
    currentBodyLines.append(line)

  blocks.append(IndexSectionBlock(currentHeading, _HEADING_TO_SECTION_KEY.get(currentHeading), currentBodyLines))
  return blocks


def strip_managed_bullets_from_body(block: IndexSectionBlock) -> tuple[list[str], int]:
  retainedLines: list[str] = []
  insertAt = 0
  managedBulletSeen = False

  for line in block.body_lines:
    parsed = parse_managed_index_bullet(line)
    if parsed and block.section_key and parsed[0] == block.section_key:
      if not managedBulletSeen:
        insertAt = len(retainedLines)
        managedBulletSeen = True
      continue
    retainedLines.append(line)

  if not managedBulletSeen:
    insertAt = len(retainedLines)

  return retainedLines, insertAt


def render_managed_section_body(
  section_key: str,
  entries: dict[str, str],
  ordered_paths: list[str] | None = None,
  preserved_lines: list[str] | None = None,
  insert_at: int = 0,
) -> str:
  del section_key
  mergedLines = list(preserved_lines or [])
  if ordered_paths is None:
    orderedPaths = sorted(entries, key=_natural_sort_key)
  else:
    orderedPaths = [relPath for relPath in ordered_paths if relPath in entries]
  managedLines = [
    f"- [[{relPath}]] - {entries[relPath]}\n"
    for relPath in orderedPaths
  ]

  if managedLines:
    safeInsertAt = min(max(insert_at, 0), len(mergedLines))
    mergedLines[safeInsertAt:safeInsertAt] = managedLines

  rendered = "".join(mergedLines)
  if rendered:
    if not rendered.endswith("\n"):
      rendered += "\n"
    return rendered
  return "\n"


def rebuild_index_text(
  client: Any,
  kb_root: str,
  previous_index_text: str,
  touched_entries: dict[str, dict[str, str]] | None = None,
) -> str:
  indexText = previous_index_text
  if not indexText.strip():
    indexText = "# 索引\n\n- [概览](./overview.md)\n- [操作日志](./log.md)\n"

  existingEntries, existingOrder = parse_index_entry_map(indexText)
  scannedPages = list_indexable_wiki_pages(client, kb_root)
  normalizedTouchedEntries = {
    sectionKey: dict((touched_entries or {}).get(sectionKey, {}))
    for sectionKey in SECTION_ORDER
  }
  normalizedEntries: dict[str, dict[str, str]] = {}
  orderedEntries: dict[str, list[str]] = {}

  for sectionKey in SECTION_ORDER:
    sectionEntries: dict[str, str] = {}

    for relPath in scannedPages[sectionKey]:
      touchedTitle = normalizedTouchedEntries[sectionKey].get(relPath)
      if touchedTitle:
        sectionEntries[relPath] = touchedTitle
        continue

      existingTitle = existingEntries[sectionKey].get(relPath)
      if existingTitle:
        sectionEntries[relPath] = existingTitle
        continue

      sectionEntries[relPath] = read_page_title(client, kb_root, relPath, PurePosixPath(relPath).stem)

    sectionEntries.update(normalizedTouchedEntries[sectionKey])
    normalizedEntries[sectionKey] = sectionEntries

    preservedOrder = [
      relPath for relPath in existingOrder[sectionKey]
      if relPath in sectionEntries
    ]
    newPaths = sorted(
      [relPath for relPath in sectionEntries if relPath not in existingOrder[sectionKey]],
      key=_natural_sort_key,
    )
    orderedEntries[sectionKey] = preservedOrder + newPaths

  existingHeadings = detect_existing_section_headings(indexText)
  blocks = split_index_into_blocks(indexText)

  renderedBlocks: list[str] = []
  handledSections: set[str] = set()

  for block in blocks:
    if block.heading is None:
      renderedBlocks.append("".join(block.body_lines))
      continue

    if block.section_key:
      handledSections.add(block.section_key)
      preservedLines, insertAt = strip_managed_bullets_from_body(block)
      body = render_managed_section_body(
        block.section_key,
        normalizedEntries[block.section_key],
        orderedEntries[block.section_key],
        preservedLines,
        insertAt,
      )
      renderedBlocks.append(f"{block.heading}\n{body}")
      continue

    renderedBlocks.append(f"{block.heading}\n{''.join(block.body_lines)}")

  rebuilt = "".join(renderedBlocks)

  for sectionKey in SECTION_ORDER:
    if sectionKey in handledSections:
      continue

    heading = existingHeadings.get(sectionKey, CANONICAL_SECTION_HEADINGS[sectionKey])
    body = render_managed_section_body(sectionKey, normalizedEntries[sectionKey], orderedEntries[sectionKey])
    if rebuilt and not rebuilt.endswith("\n"):
      rebuilt += "\n"
    if rebuilt and not rebuilt.endswith("\n\n"):
      rebuilt += "\n"
    rebuilt += f"{heading}\n{body}"

  if not rebuilt.endswith("\n"):
    rebuilt += "\n"
  return rebuilt
