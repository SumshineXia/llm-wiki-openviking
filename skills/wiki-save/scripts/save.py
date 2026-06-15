from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

import time as _time

from common import build_error_result, build_kb_root, print_json
from ovfs import OVFSClient, OVFSConfig, OVFSHTTPError
from wiki_index import rebuild_index_text, resolve_markdown_write_target_uri

_phaseTimes: list[dict[str, Any]] = []

def _stamp(label: str) -> None:
  _phaseTimes.append({"label": label, "ts": _time.monotonic()})


INDEX_TITLE = "# 索引"
OVERVIEW_TITLE = "# 概览"
LOG_TITLE = "# 操作日志\n"


def resolveWriteUri(client: OVFSClient, uri: str) -> str:
  canonical = resolveCanonicalMarkdownUri(client, uri)
  if canonical:
    return canonical
  return uri


def nowIso() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str) -> str:
  normalized = text.strip().lower()
  tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", normalized)
  if not tokens:
    return "untitled"
  return "-".join(tokens)


def getUriStat(client: OVFSClient, uri: str) -> dict[str, Any] | None:
  try:
    return client.stat(uri)
  except OVFSHTTPError as exc:
    message = str(exc).lower()
    if "404" in message or "not found" in message:
      return None
    raise


def findDirectContentChild(client: OVFSClient, uri: str) -> str | None:
  targetUri = uri.rstrip("/") + "/"
  try:
    children = client.ls(targetUri, recursive=False)
  except OVFSHTTPError as exc:
    message = str(exc).lower()
    if "404" in message or "not found" in message:
      return None
    raise

  candidates: list[str] = []
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
    name = PurePosixPath(childUri).name
    if not name.endswith(".md") or name == "abstract.md":
      continue

    if childIsDir is None:
      childStat = getUriStat(client, childUri)
      childIsDir = bool(childStat and childStat.get("isDir", False))

    if not childIsDir:
      candidates.append(childUri)

  parentName = PurePosixPath(uri.rstrip("/")).name
  for candidate in candidates:
    if PurePosixPath(candidate).name == parentName:
      return candidate
  return candidates[0] if candidates else None


def resolveCanonicalMarkdownUri(client: OVFSClient, uri: str) -> str | None:
  stat = getUriStat(client, uri)
  if not stat:
    return None

  if not stat.get("isDir", False):
    return uri

  directChild = findDirectContentChild(client, uri)
  if directChild:
    return directChild

  baseName = PurePosixPath(uri.rstrip("/")).name
  if not baseName:
    return None

  nestedUri = uri.rstrip("/") + f"/{baseName}"
  nestedStat = getUriStat(client, nestedUri)
  if nestedStat and not nestedStat.get("isDir", False):
    return nestedUri

  return None


def readIfExists(client: OVFSClient, uri: str, default: str = "") -> str:
  readUri = resolveCanonicalMarkdownUri(client, uri)
  if not readUri:
    return default
  return client.read_text(readUri)


def ensureSection(indexText: str, heading: str) -> str:
  if heading in indexText:
    return indexText
  text = indexText.rstrip()
  if text:
    text += "\n\n"
  return text + f"{heading}\n\n"


def appendUniqueBullet(indexText: str, heading: str, bullet: str) -> str:
  text = ensureSection(indexText, heading)
  if bullet in text:
    return text

  pattern = re.compile(rf"(^{re.escape(heading)}\s*$)", re.MULTILINE)
  match = pattern.search(text)
  if not match:
    return text.rstrip() + f"\n\n{heading}\n{bullet}\n"

  insertPos = match.end()
  return text[:insertPos] + "\n" + bullet + text[insertPos:]


def upsert_index_link_bullet(indexText: str, heading: str, linkPath: str, title: str) -> str:
  text = ensureSection(indexText, heading)
  bullet = f"- [[{linkPath}]] - {title}"
  pattern = re.compile(rf"^-\s*\[\[{re.escape(linkPath)}\]\]\s*-\s*.*$", re.MULTILINE)
  if pattern.search(text):
    return pattern.sub(bullet, text, count=1)
  return appendUniqueBullet(text, heading, bullet)


def build_overview_note(linkPath: str, title: str) -> str:
  return f"- [[{linkPath}]] - {title}"


def upsert_overview_synthesis_block(overviewText: str, linkPath: str, note: str) -> str:
  startTag = f"<!-- synthesis:{linkPath}:start -->"
  endTag = f"<!-- synthesis:{linkPath}:end -->"
  block = f"{startTag}\n{note}\n{endTag}"
  pattern = re.compile(
    rf"{re.escape(startTag)}\\n.*?\\n{re.escape(endTag)}",
    re.DOTALL,
  )
  if pattern.search(overviewText):
    return pattern.sub(block, overviewText, count=1)
  return overviewText.rstrip() + "\n\n" + block + "\n"


def appendLogEntry(logText: str, entry: str) -> str:
  normalizedEntry = entry.strip()
  if not normalizedEntry:
    return logText
  line = f"- {nowIso()} - {normalizedEntry}"
  if line in logText:
    return logText
  return logText.rstrip() + "\n" + line + "\n"


def renderSynthesisMarkdown(title: str, question: str, answerMarkdown: str, usedPages: list[str]) -> str:
  usedSection = "\n".join(f"- {uri}" for uri in usedPages) if usedPages else "- 无"
  return f"""# {title}

## 问题

{question}

## 回答

{answerMarkdown}

## 使用的页面

{usedSection}
"""


def render_synthesis_markdown(title: str, question: str, answerMarkdown: str, usedPages: list[str]) -> str:
  return renderSynthesisMarkdown(title, question, answerMarkdown, usedPages)


def resolveSynthesisTarget(kbRoot: str, slug: str | None, title: str) -> tuple[str, str, str]:
  if slug and slug.strip():
    synthesisSlug = slugify(slug)
  else:
    synthesisSlug = slugify(title)

  relPath = f"wiki/syntheses/{synthesisSlug}.md"
  return relPath, synthesisSlug, kbRoot + relPath


def loadPayload(path: str) -> dict[str, Any]:
  with open(path, "r", encoding="utf-8") as fp:
    data = json.load(fp)
  if not isinstance(data, dict):
    raise ValueError("--payload-file 必须是 JSON object")
  return data


def parseArgs() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="保存综合结论到 KB wiki/syntheses")
  parser.add_argument("--kb-name", default=None, help="知识库名称")
  parser.add_argument("--payload-file", default=None, help="wiki-query 输出 payload JSON 文件")
  parser.add_argument("--answer-file", default=None, help="答案 markdown 文件路径")
  parser.add_argument("--question", default=None, help="问题文本")
  parser.add_argument("--title", default=None, help="综合结论标题")
  parser.add_argument("--slug", default=None, help="综合结论 slug")
  parser.add_argument("--used-page", action="append", default=[], help="可重复，记录使用页面 URI")
  parser.add_argument("--overview-note", default=None, help="追加到 overview 的备注")
  parser.add_argument("--on-conflict", choices=["update", "error", "unique"], default="update")
  parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入远端")
  parser.add_argument("--config", default=None, help="配置文件路径")
  parser.add_argument("--profile", default=None, help="profile 名称")
  parser.add_argument("--pretty", action="store_true", help="格式化输出 JSON")
  parser.add_argument("--answer", default=None, help=argparse.SUPPRESS)
  args = parser.parse_args()

  if args.answer is not None:
    parser.error("不支持 --answer，请使用 --answer-file")

  if args.payload_file and args.answer_file:
    parser.error("--payload-file 与 --answer-file 不能同时使用")
  if args.payload_file and args.question:
    parser.error("--payload-file 与 --question 不能同时使用")

  return args


def buildInput(args: argparse.Namespace) -> dict[str, Any]:
  if args.payload_file:
    payload = loadPayload(args.payload_file)
    rawKbName = payload.get("kb_name")
    if not isinstance(rawKbName, str) or not rawKbName.strip():
      raise ValueError("payload 缺少 kb_name")
    payloadKbName = rawKbName.strip()
    if not payloadKbName:
      raise ValueError("payload 缺少 kb_name")
    if args.kb_name and args.kb_name.strip() and args.kb_name.strip() != payloadKbName:
      raise ValueError("payload 的 kb_name 与 --kb-name 冲突")

    rawAnswerMarkdown = payload.get("answer_markdown")
    rawQuestion = payload.get("question")
    rawTitle = payload.get("synthesis_title")
    if not isinstance(rawAnswerMarkdown, str) or not rawAnswerMarkdown.strip():
      raise ValueError("payload 缺少 answer_markdown")
    if not isinstance(rawQuestion, str) or not rawQuestion.strip():
      raise ValueError("payload 缺少 question")
    if not isinstance(rawTitle, str) or not rawTitle.strip():
      raise ValueError("payload 缺少 synthesis_title")

    answerMarkdown = rawAnswerMarkdown.strip()
    question = rawQuestion.strip()
    title = rawTitle.strip()
    usedPagesRaw = payload.get("used_pages", [])
    if not isinstance(usedPagesRaw, list):
      raise ValueError("payload 的 used_pages 必须是 list[str]")
    if not all(isinstance(item, str) for item in usedPagesRaw):
      raise ValueError("payload 的 used_pages 必须是 list[str]")
    usedPages = [item.strip() for item in usedPagesRaw if item.strip()]

    if not answerMarkdown:
      raise ValueError("payload 缺少 answer_markdown")
    if not question:
      raise ValueError("payload 缺少 question")
    if not title:
      raise ValueError("payload 缺少 synthesis_title")

    rawPayloadKbRoot = payload.get("kb_root", "")
    if rawPayloadKbRoot is None:
      payloadKbRoot = ""
    elif isinstance(rawPayloadKbRoot, str):
      payloadKbRoot = rawPayloadKbRoot.strip()
    else:
      raise ValueError("payload 的 kb_root 必须是字符串")

    return {
      "kbName": payloadKbName,
      "question": question,
      "answerMarkdown": answerMarkdown,
      "title": title,
      "usedPages": usedPages,
      "kbRootInPayload": payloadKbRoot,
    }

  if not args.kb_name:
    raise ValueError("非 payload 模式必须提供 --kb-name")
  if not args.answer_file:
    raise ValueError("非 payload 模式必须提供 --answer-file")
  if not args.question or not args.question.strip():
    raise ValueError("非 payload 模式必须提供 --question")
  if not args.title or not args.title.strip():
    raise ValueError("非 payload 模式必须提供 --title")

  with open(args.answer_file, "r", encoding="utf-8") as fp:
    answerMarkdown = fp.read().strip()
  if not answerMarkdown:
    raise ValueError("--answer-file 内容为空")

  return {
    "kbName": args.kb_name.strip(),
    "question": args.question.strip(),
    "answerMarkdown": answerMarkdown,
    "title": args.title.strip(),
    "usedPages": [item.strip() for item in args.used_page if item and item.strip()],
    "kbRootInPayload": "",
  }


def chooseTargetUri(client: OVFSClient, baseUri: str, onConflict: str) -> tuple[str, str, bool]:
  canonical = resolveCanonicalMarkdownUri(client, baseUri)
  if canonical:
    if onConflict == "error":
      raise ValueError(f"目标已存在: {canonical}")
    if onConflict == "update":
      return canonical, PurePosixPath(canonical).stem, False
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    uniqueUri = baseUri.replace(".md", f"-{suffix}.md")
    return uniqueUri, PurePosixPath(uniqueUri).stem, True
  return baseUri, PurePosixPath(baseUri).stem, True


def main() -> int:
  args = parseArgs()
  try:
    normalizedInput = buildInput(args)
    kbName = normalizedInput["kbName"]
    kbRoot = build_kb_root(kbName)

    payloadKbRoot = normalizedInput["kbRootInPayload"]
    payloadKbRootMismatch = bool(payloadKbRoot and payloadKbRoot != kbRoot)

    relPath, requestedSlug, requestedUri = resolveSynthesisTarget(kbRoot, args.slug, normalizedInput["title"])
    config = OVFSConfig.load(config_path=args.config, profile=args.profile)

    with OVFSClient(config) as client:
      _stamp("client_ready")
      targetUri, finalSlug, willCreate = chooseTargetUri(client, requestedUri, args.on_conflict)
      _stamp("choose_target_end")
      finalRelPath = "wiki/syntheses/" + PurePosixPath(targetUri).name

      synthesisMarkdown = render_synthesis_markdown(
        normalizedInput["title"],
        normalizedInput["question"],
        normalizedInput["answerMarkdown"],
        normalizedInput["usedPages"],
      )
      _stamp("render_end")

      indexText = readIfExists(client, kbRoot + "wiki/index.md", INDEX_TITLE + "\n")
      _stamp("read_index_end")
      overviewText = readIfExists(client, kbRoot + "wiki/overview.md", OVERVIEW_TITLE + "\n")
      _stamp("read_overview_end")
      logText = readIfExists(client, kbRoot + "wiki/log.md", LOG_TITLE)
      _stamp("read_log_end")

      linkPath = f"syntheses/{finalSlug}.md"
      touched_entries = {"syntheses": {linkPath: normalizedInput["title"]}}
      newIndexText = rebuild_index_text(client, kbRoot, indexText, touched_entries=touched_entries)
      overviewNote = build_overview_note(linkPath, normalizedInput["title"])
      if args.overview_note and args.overview_note.strip():
        overviewNote = args.overview_note.strip()
      newOverviewText = upsert_overview_synthesis_block(overviewText, linkPath, overviewNote)
      newLogText = appendLogEntry(logText, f"已保存综合结论 {finalSlug} 到 {finalRelPath}")

      if not args.dry_run:
        _stamp("write_synthesis_start")
        client.write_text(targetUri, synthesisMarkdown, create=willCreate, wait=False)
        _stamp("write_synthesis_end")
        indexWriteUri, indexShouldCreate = resolve_markdown_write_target_uri(client, kbRoot + "wiki/index.md")
        client.write_text(indexWriteUri, newIndexText, create=indexShouldCreate, wait=False)
        _stamp("write_index_end")
        if newOverviewText != overviewText:
          overviewWriteUri = resolveWriteUri(client, kbRoot + "wiki/overview.md")
          client.write_text(overviewWriteUri, newOverviewText, create=False, wait=False)
        _stamp("write_overview_end")
        logWriteUri = resolveWriteUri(client, kbRoot + "wiki/log.md")
        client.write_text(logWriteUri, newLogText, create=False, wait=False)
        _stamp("write_log_end")

      result = {
        "status": "ok",
        "kb_name": kbName,
        "kb_root": kbRoot,
        "requested_synthesis_uri": requestedUri,
        "synthesis_uri": targetUri,
        "synthesis_slug": finalSlug,
        "on_conflict": args.on_conflict,
        "dry_run": args.dry_run,
        "would_create": willCreate,
        "payload_kb_root_mismatch": payloadKbRootMismatch,
        "writes": [
          {"uri": targetUri, "kind": "synthesis"},
          {"uri": kbRoot + "wiki/index.md", "kind": "index"},
          {"uri": kbRoot + "wiki/overview.md", "kind": "overview"},
          {"uri": kbRoot + "wiki/log.md", "kind": "log"},
        ],
        "requested_relative_path": relPath,
        "requested_slug": requestedSlug,
        "index_update_mode": "rebuild",
        "touched_index_entries": touched_entries,
      }
      if len(_phaseTimes) >= 2:
        result["phase_durations_ms"] = {}
        for i in range(1, len(_phaseTimes)):
          prev = _phaseTimes[i - 1]
          curr = _phaseTimes[i]
          dur = round((curr["ts"] - prev["ts"]) * 1000)
          result["phase_durations_ms"][curr["label"]] = dur
        totalMs = round((_phaseTimes[-1]["ts"] - _phaseTimes[0]["ts"]) * 1000)
        result["phase_durations_ms"]["total_writes_ms"] = totalMs
      print_json(result, pretty=args.pretty)
      return 0
  except Exception as exc:
    print_json(build_error_result(exc), pretty=args.pretty)
    return 1


if __name__ == "__main__":
  sys.exit(main())
