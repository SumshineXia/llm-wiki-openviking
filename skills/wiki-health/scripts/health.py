from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

try:
  from common import build_kb_root
  from ovfs import OVFSClient, OVFSConfig, OVFSError, OVFSHTTPError
except ModuleNotFoundError:
  scriptDir = Path(__file__).resolve().parent
  if str(scriptDir) not in sys.path:
    sys.path.insert(0, str(scriptDir))
  from common import build_kb_root
  from ovfs import OVFSClient, OVFSConfig, OVFSError, OVFSHTTPError


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

  if "#" in target:
    target = target.split("#", 1)[0]
  if "?" in target:
    target = target.split("?", 1)[0]

  target = target.lstrip("/")

  if target.endswith("/"):
    return None

  if not target.endswith(".md"):
    target = f"{target}.md"

  parts: list[str] = []
  for part in PurePosixPath(target).parts:
    if part in ("", "."):
      continue
    if part == "..":
      if parts:
        parts.pop()
      continue
    parts.append(part)

  normalized = PurePosixPath(*parts).as_posix()
  if not normalized:
    return None

  return normalized


def extract_index_links(indexText: str) -> set[str]:
  results: set[str] = set()

  wikilinkPattern = re.compile(r"\[\[([^\]]+)\]\]")
  markdownLinkPattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

  for raw in wikilinkPattern.findall(indexText):
    normalized = normalize_relative_wiki_target(raw)
    if normalized:
      results.add(normalized)

  for raw in markdownLinkPattern.findall(indexText):
    normalized = normalize_relative_wiki_target(raw)
    if normalized:
      results.add(normalized)

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


def basename_without_ext(uri: str) -> str:
  name = PurePosixPath(uri).name
  if name.endswith(".md"):
    return name[:-3]
  return name


def get_uri_stat(client: OVFSClient, uri: str) -> dict[str, Any] | None:
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
    nestedCandidate = uri.rstrip("/") + f"/{basename}"
    nestedStat = get_uri_stat(client, nestedCandidate)
    if nestedStat and not nestedStat.get("isDir", False):
      return nestedCandidate

  try:
    children = client.ls(uri.rstrip("/") + "/", recursive=False)
  except Exception:
    children = []

  for child in children:
    childUri: str | None = None
    childIsDir: bool | None = None

    if isinstance(child, str):
      childUri = child
    elif isinstance(child, dict):
      childUri = child.get("uri") or child.get("path")
      if isinstance(child.get("isDir"), bool):
        childIsDir = child["isDir"]

    if not childUri or not isinstance(childUri, str):
      continue
    if not childUri.endswith(".md"):
      continue

    if childIsDir is None:
      childStat = get_uri_stat(client, childUri)
      childIsDir = bool(childStat and childStat.get("isDir", False))

    if not childIsDir:
      return childUri

  return None


def get_log_match_stem(uri: str, sourcesRoot: str) -> str:
  stem = basename_without_ext(uri).lower()
  if not stem.startswith("tmp"):
    return stem

  normalizedUri = uri.rstrip("/")
  normalizedSourcesRoot = sourcesRoot.rstrip("/") + "/"
  if normalizedUri.startswith(normalizedSourcesRoot):
    segments = normalizedUri.split("/")
    if len(segments) >= 2:
      parentName = segments[-2]
      if parentName.endswith(".md"):
        return parentName[:-3].lower()

  return stem


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
  sourcesRoot = kbRoot + "wiki/sources/"
  logUri = f"{kbRoot}wiki/log.md"

  canonicalLogUri = resolve_canonical_markdown_uri(client, logUri)
  if not canonicalLogUri:
    return []

  logText = client.read_text(canonicalLogUri).lower()
  sourcePages = list_markdown_pages(client, sourcesRoot)

  missingInLog: list[str] = []
  for uri in sourcePages:
    stem = get_log_match_stem(uri, sourcesRoot)
    if stem not in logText:
      missingInLog.append(uri)

  return missingInLog


def build_report(client: OVFSClient, kbRoot: str) -> dict[str, Any]:
  missingDirs, missingFiles = check_required_structure(client, kbRoot)
  emptyKeyPages = check_empty_key_pages(client, kbRoot)
  linkedTargets, brokenIndexTargets = check_index_targets(client, kbRoot)
  missingSourceLogEntries = check_source_log_coverage(client, kbRoot)

  allWikiPages = list_markdown_pages(client, kbRoot + "wiki/")
  allSourcePages = list_markdown_pages(client, kbRoot + "wiki/sources/")
  allEntityPages = list_markdown_pages(client, kbRoot + "wiki/entities/")
  allConceptPages = list_markdown_pages(client, kbRoot + "wiki/concepts/")
  allSynthesisPages = list_markdown_pages(client, kbRoot + "wiki/syntheses/")

  errors: list[str] = []
  warnings: list[str] = []

  if missingDirs:
    errors.append(f"Missing required directories: {len(missingDirs)}")
  if missingFiles:
    errors.append(f"Missing required root files: {len(missingFiles)}")
  if emptyKeyPages:
    errors.append(f"Empty or invalid key pages: {len(emptyKeyPages)}")
  if brokenIndexTargets:
    errors.append(f"Broken links referenced by wiki/index.md: {len(brokenIndexTargets)}")
  if not allSourcePages:
    warnings.append("No source pages found under wiki/sources/")

  if not linkedTargets:
    warnings.append("wiki/index.md contains no parseable internal links")
  if not allEntityPages and not allConceptPages and not allSynthesisPages:
    warnings.append("No entity, concept, or synthesis pages found")
  if len(allWikiPages) <= 3:
    warnings.append("Wiki appears to contain only root pages")

  if missingSourceLogEntries:
    warnings.append(
      f"Source pages not reflected in wiki/log.md: {len(missingSourceLogEntries)}"
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
    },
    "errors": errors,
    "warnings": warnings,
    "details": {
      "missing_dirs": missingDirs,
      "missing_files": missingFiles,
      "empty_key_pages": emptyKeyPages,
      "broken_index_targets": brokenIndexTargets,
      "missing_source_log_entries": missingSourceLogEntries,
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
  kbRoot = build_kb_root(args.kb_name)
  config = OVFSConfig.load()

  try:
    with OVFSClient(config) as client:
      report = build_report(client, kbRoot)
  except OVFSError as exc:
    errorReport = {
      "status": "error",
      "kb_root": kbRoot,
      "errors": [f"OVFS error: {str(exc)}"],
      "warnings": [],
      "details": {},
    }
    print(json.dumps(errorReport, ensure_ascii=False, indent=2))
    return 2
  except Exception as exc:
    errorReport = {
      "status": "error",
      "kb_root": kbRoot,
      "errors": [f"Unexpected error: {str(exc)}"],
      "warnings": [],
      "details": {},
    }
    print(json.dumps(errorReport, ensure_ascii=False, indent=2))
    return 3

  if args.pretty:
    print(json.dumps(report, ensure_ascii=False, indent=2))
  else:
    print(json.dumps(report, ensure_ascii=False))

  return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
  sys.exit(main())
