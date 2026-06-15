# Wiki Index Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `wiki-ingest`、`wiki-save`、legacy `wiki-query --save`、`wiki-health --repair-index` 在更新 `wiki/index.md` 时都使用同一套确定性的、非破坏性的 rebuild 逻辑，并让 `wiki-health` 能准确诊断 index 覆盖缺陷与重复项。

**Architecture:** 新增四份内容完全一致的 `wiki_index.py` helper，集中承载 OpenViking bundle 解析、真实页面扫描、index 解析、非破坏性 rebuild。`ingest.py`、`save.py`、`query.py`、`health.py` 只接入 helper，不在各自脚本里继续维护第二套 index 语义。health 的 repair 模式只重建 `wiki/index.md`，不删除页面、不调用 LLM，并保留 index 中所有非 managed 内容。

**Tech Stack:** Python 3、OpenViking OVFSClient、pytest、OpenAI Python SDK（仅现有 ingest/query 继续使用）

---

## File Structure

**Create:**
- `skills/wiki-ingest/scripts/wiki_index.py`
- `skills/wiki-save/scripts/wiki_index.py`
- `skills/wiki-health/scripts/wiki_index.py`
- `skills/wiki-query/scripts/wiki_index.py`
- `tests/skills/test_index_rebuild.py`

**Modify:**
- `skills/wiki-ingest/scripts/ingest.py`
- `skills/wiki-save/scripts/save.py`
- `skills/wiki-query/scripts/query.py`
- `skills/wiki-health/scripts/health.py`
- `skills/wiki-health/SKILL.md`
- `tests/skills/test_health_checks.py`
- `tests/skills/test_save_updates.py`
- `tests/skills/test_query_save_legacy_semantics.py`
- `tests/skills/test_zh_language_defaults.py`
- `tests/skills/test_shared_script_consistency.py`

**Responsibilities:**
- `skills/*/scripts/wiki_index.py`: 统一承载 section 配置、bundle-safe 读写目标、真实页面扫描、managed link 解析、非破坏性 rebuild。
- `skills/wiki-ingest/scripts/ingest.py`: 继续负责 ingest 主流程、LLM 调用、页面写入、overview/log 更新；index 更新改为调用 helper rebuild。
- `skills/wiki-save/scripts/save.py`: 继续负责 synthesis 保存、overview/log 更新；index 更新改为 helper rebuild。
- `skills/wiki-query/scripts/query.py`: 继续负责 query 与 legacy `--save`；legacy save 的 index 更新改为 helper rebuild。
- `skills/wiki-health/scripts/health.py`: 继续负责结构健康检查；新增重复 target、未索引真实页面、改进 source-log 匹配与 `--repair-index`。
- `tests/skills/test_index_rebuild.py`: 验证 helper 的 bundle 语义、合法页面过滤、非破坏性 rebuild。
- 其他测试文件：锁定 legacy heading、health import fallback、save/query/health 新行为与一致性约束。

## Implementation Notes

- 只忽略 `WIKI_DERIVED_FILE_NAMES = {".abstract.md", ".overview.md", ".relations.json"}`；**不要**在 shared helper 里忽略 bare `abstract.md` / `overview.md`。
- `wiki/index.md` 的 rebuild 必须是**非破坏性**的：只替换 managed section 中的 managed wiki page bullet，保留非 managed section、用户说明、HTML 注释、额外导航、以及 managed section 内的非 managed 行。
- `skills/wiki-health/scripts/health.py` 导入 `wiki_index.py` 时，必须放进现有 `ModuleNotFoundError` fallback 结构内，保持 `tests/skills/test_health_checks.py` 现在的 `spec_from_file_location(...).exec_module(...)` 加载方式可用。
- 如果 `wiki_index.py` 继续使用 `@dataclass`，所有通过 `spec_from_file_location(...).exec_module(...)` 加载它的测试，都必须先执行 `sys.modules[spec.name] = module`，避免 dataclass 解析 postponed annotations 时因为模块未注册而报错。
- 四份 `skills/*/scripts/wiki_index.py` 内容必须字节级一致；不要在某个 skill 目录里做局部特化。
- 使用 `~/.config/opencode/skills/wiki-health/scripts/run.sh` 对 `xiay` 做真实验收前，先确认安装目录中的 skill 已同步本仓库实现；如果安装目录不是当前 worktree 的映射，先同步再跑远端命令。
- 不要修改 `common.py`、`ovfs.py`、README 主流程、query 检索逻辑、raw 目录结构。

### Task 1: 建立共享 `wiki_index.py` helper 与核心测试

**Files:**
- Create: `skills/wiki-ingest/scripts/wiki_index.py`
- Create: `skills/wiki-save/scripts/wiki_index.py`
- Create: `skills/wiki-health/scripts/wiki_index.py`
- Create: `skills/wiki-query/scripts/wiki_index.py`
- Create: `tests/skills/test_index_rebuild.py`
- Modify: `tests/skills/test_shared_script_consistency.py`

- [ ] **Step 1: 写 helper 失败测试与一致性测试**

```python
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


repoRoot = Path(__file__).resolve().parents[2]
helperPath = repoRoot / "skills" / "wiki-ingest" / "scripts" / "wiki_index.py"
helperDir = helperPath.parent
sys.path.insert(0, str(helperDir))
spec = spec_from_file_location("wiki_index_helper", helperPath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-ingest/scripts/wiki_index.py")
module = module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FakeClient:
  def __init__(self, stats: dict[str, dict[str, bool]], texts: dict[str, str] | None = None, listings: dict[tuple[str, bool], list[object]] | None = None) -> None:
    self.stats = stats
    self.texts = texts or {}
    self.listings = listings or {}

  def stat(self, uri: str):
    if uri not in self.stats:
      raise RuntimeError("404 not found")
    return self.stats[uri]

  def ls(self, uri: str, recursive: bool = False):
    return self.listings.get((uri, recursive), [])

  def read_text(self, uri: str) -> str:
    return self.texts[uri]


def test_canonical_index_rel_path_folds_bundle_path() -> None:
  kbRoot = "viking://resources/demo/"
  uri = "viking://resources/demo/wiki/sources/foo.md/foo.md"
  assert module.canonical_index_rel_path_from_uri(kbRoot, uri) == "sources/foo.md"


def test_resolve_markdown_write_target_uri_prefers_same_name_child() -> None:
  client = FakeClient(
    stats={
      "viking://resources/demo/wiki/index.md": {"isDir": True},
    },
    listings={("viking://resources/demo/wiki/index.md/", False): []},
  )
  assert module.resolve_markdown_write_target_uri(client, "viking://resources/demo/wiki/index.md") == (
    "viking://resources/demo/wiki/index.md/index.md",
    True,
  )


def test_list_indexable_wiki_pages_keeps_bare_overview_page() -> None:
  kbRoot = "viking://resources/demo/"
  client = FakeClient(
    stats={
      f"{kbRoot}wiki/sources/overview.md/overview.md": {"isDir": False},
    },
    listings={
      (f"{kbRoot}wiki/sources/", True): [
        {"uri": f"{kbRoot}wiki/sources/overview.md/overview.md", "isDir": False},
      ],
      (f"{kbRoot}wiki/entities/", True): [],
      (f"{kbRoot}wiki/concepts/", True): [],
      (f"{kbRoot}wiki/syntheses/", True): [],
    },
  )
  pages = module.list_indexable_wiki_pages(client, kbRoot)
  assert pages["sources"] == ["sources/overview.md"]


def test_list_indexable_wiki_pages_keeps_bare_abstract_page() -> None:
  kbRoot = "viking://resources/demo/"
  client = FakeClient(
    stats={
      f"{kbRoot}wiki/syntheses/abstract.md/abstract.md": {"isDir": False},
    },
    listings={
      (f"{kbRoot}wiki/sources/", True): [],
      (f"{kbRoot}wiki/entities/", True): [],
      (f"{kbRoot}wiki/concepts/", True): [],
      (f"{kbRoot}wiki/syntheses/", True): [
        {"uri": f"{kbRoot}wiki/syntheses/abstract.md/abstract.md", "isDir": False},
      ],
    },
  )
  pages = module.list_indexable_wiki_pages(client, kbRoot)
  assert pages["syntheses"] == ["syntheses/abstract.md"]


def test_list_indexable_wiki_pages_ignores_dot_prefixed_derived_files() -> None:
  kbRoot = "viking://resources/demo/"
  client = FakeClient(
    stats={
      f"{kbRoot}wiki/sources/foo.md/.overview.md": {"isDir": False},
      f"{kbRoot}wiki/sources/foo.md/.abstract.md": {"isDir": False},
      f"{kbRoot}wiki/sources/foo.md/.relations.json": {"isDir": False},
      f"{kbRoot}wiki/sources/foo.md/foo.md": {"isDir": False},
    },
    listings={
      (f"{kbRoot}wiki/sources/", True): [
        {"uri": f"{kbRoot}wiki/sources/foo.md/.overview.md", "isDir": False},
        {"uri": f"{kbRoot}wiki/sources/foo.md/.abstract.md", "isDir": False},
        {"uri": f"{kbRoot}wiki/sources/foo.md/.relations.json", "isDir": False},
        {"uri": f"{kbRoot}wiki/sources/foo.md/foo.md", "isDir": False},
      ],
      (f"{kbRoot}wiki/entities/", True): [],
      (f"{kbRoot}wiki/concepts/", True): [],
      (f"{kbRoot}wiki/syntheses/", True): [],
    },
  )
  pages = module.list_indexable_wiki_pages(client, kbRoot)
  assert pages["sources"] == ["sources/foo.md"]


def test_rebuild_index_text_preserves_non_managed_sections_and_manual_lines() -> None:
  kbRoot = "viking://resources/demo/"
  previous = """# 索引

- [概览](./overview.md)

## 资料来源
这里是用户写的资料说明，不能删。
- [[sources/old.md]] - Old

## 自定义说明
这段用户手写内容必须保留。

## 实体
- [[entities/aihub.md]] - AIHub

<!-- manual comment -->

## 附加导航
- [外部链接](https://example.com)
"""
  client = FakeClient(
    stats={
      f"{kbRoot}wiki/sources/new.md/new.md": {"isDir": False},
      f"{kbRoot}wiki/entities/aihub.md/aihub.md": {"isDir": False},
    },
    texts={
      f"{kbRoot}wiki/sources/new.md/new.md": "# New\n\n正文\n",
      f"{kbRoot}wiki/entities/aihub.md/aihub.md": "# AIHub\n\n正文\n",
    },
    listings={
      (f"{kbRoot}wiki/sources/", True): [
        {"uri": f"{kbRoot}wiki/sources/new.md/new.md", "isDir": False},
      ],
      (f"{kbRoot}wiki/entities/", True): [
        {"uri": f"{kbRoot}wiki/entities/aihub.md/aihub.md", "isDir": False},
      ],
      (f"{kbRoot}wiki/concepts/", True): [],
      (f"{kbRoot}wiki/syntheses/", True): [],
    },
  )
  rebuilt = module.rebuild_index_text(client, kbRoot, previous)
  assert "sources/old.md" not in rebuilt
  assert "sources/new.md" in rebuilt
  assert "这里是用户写的资料说明，不能删。" in rebuilt
  assert "## 自定义说明" in rebuilt
  assert "这段用户手写内容必须保留。" in rebuilt
  assert "<!-- manual comment -->" in rebuilt
  assert "## 附加导航" in rebuilt
  assert "https://example.com" in rebuilt


def test_rebuild_index_text_preserves_manual_lines_inside_managed_section() -> None:
  kbRoot = "viking://resources/demo/"
  previous = "## 资料来源\n\n这里是用户写的资料说明，不能删。\n\n- [[sources/old.md]] - Old\n"
  client = FakeClient(
    stats={
      f"{kbRoot}wiki/sources/new.md/new.md": {"isDir": False},
    },
    texts={
      f"{kbRoot}wiki/sources/new.md/new.md": "# New\n\n正文\n",
    },
    listings={
      (f"{kbRoot}wiki/sources/", True): [
        {"uri": f"{kbRoot}wiki/sources/new.md/new.md", "isDir": False},
      ],
      (f"{kbRoot}wiki/entities/", True): [],
      (f"{kbRoot}wiki/concepts/", True): [],
      (f"{kbRoot}wiki/syntheses/", True): [],
    },
  )
  rebuilt = module.rebuild_index_text(client, kbRoot, previous)
  assert "sources/old.md" not in rebuilt
  assert "sources/new.md" in rebuilt
  assert "这里是用户写的资料说明，不能删。" in rebuilt
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/skills/test_index_rebuild.py tests/skills/test_shared_script_consistency.py -q`
Expected: FAIL，报错包含 `无法加载 skills/wiki-ingest/scripts/wiki_index.py` 或 `FileNotFoundError`，以及共享一致性测试找不到 `wiki_index.py`。

- [ ] **Step 3: 写最小 helper 实现并复制到四个 skill 目录**

先在 `skills/wiki-ingest/scripts/wiki_index.py` 写入以下代码，再原样复制到另外三个目录：

```python
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any
from dataclasses import dataclass


SECTION_ORDER = ("sources", "entities", "concepts", "syntheses")

SECTION_DIRS = {
  "sources": "sources",
  "entities": "entities",
  "concepts": "concepts",
  "syntheses": "syntheses",
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

WIKI_DERIVED_FILE_NAMES = {
  ".abstract.md",
  ".overview.md",
  ".relations.json",
}


@dataclass
class IndexSectionBlock:
  heading: str | None
  body: str
  section_key: str | None
  start: int
  end: int


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


def get_uri_stat(client, uri: str) -> dict[str, Any] | None:
  try:
    return client.stat(uri)
  except Exception as exc:
    message = str(exc).lower()
    if "404" in message or "not found" in message:
      return None
    raise


def expected_content_child_uri(uri: str) -> str:
  normalized = uri.rstrip("/")
  basename = PurePosixPath(normalized).name
  return f"{normalized}/{basename}"


def find_direct_content_child(client, uri: str, extensions: tuple[str, ...] = (".md",)) -> str | None:
  target_uri = uri.rstrip("/") + "/"
  try:
    children = client.ls(target_uri, recursive=False)
  except Exception:
    return None

  candidates: list[str] = []
  for child in children:
    child_uri = extract_uri_from_ls_item(child)
    if not child_uri:
      continue
    name = PurePosixPath(child_uri).name
    if name in WIKI_DERIVED_FILE_NAMES:
      continue
    if not name.endswith(extensions):
      continue
    if isinstance(child, dict) and isinstance(child.get("isDir"), bool):
      is_dir = child["isDir"]
    else:
      child_stat = get_uri_stat(client, child_uri)
      is_dir = bool(child_stat and child_stat.get("isDir", False))
    if not is_dir:
      candidates.append(child_uri)

  parent_name = PurePosixPath(uri.rstrip("/")).name
  for candidate in candidates:
    if PurePosixPath(candidate).name == parent_name:
      return candidate
  return candidates[0] if candidates else None


def resolve_canonical_markdown_uri(client, uri: str) -> str | None:
  stat = get_uri_stat(client, uri)
  if not stat:
    return None
  if not stat.get("isDir", False):
    return uri
  direct_child = find_direct_content_child(client, uri)
  if direct_child:
    return direct_child
  same_name_child = expected_content_child_uri(uri)
  child_stat = get_uri_stat(client, same_name_child)
  if child_stat and not child_stat.get("isDir", False):
    return same_name_child
  return None


def resolve_markdown_write_target_uri(client, uri: str) -> tuple[str, bool]:
  stat = get_uri_stat(client, uri)
  if not stat:
    return uri, True
  if not stat.get("isDir", False):
    return uri, False
  same_name_child = expected_content_child_uri(uri)
  same_name_stat = get_uri_stat(client, same_name_child)
  if same_name_stat and not same_name_stat.get("isDir", False):
    return same_name_child, False
  content_child = find_direct_content_child(client, uri)
  if content_child:
    return content_child, False
  return same_name_child, True


def normalize_relative_wiki_target(target: str) -> str | None:
  target = target.strip()
  if not target:
    return None
  lowered = target.lower()
  if lowered.startswith("http://") or lowered.startswith("https://"):
    return None
  if target.startswith("#"):
    return None
  target = target.split("#", 1)[0].split("?", 1)[0].strip()
  if not target:
    return None
  target = target.lstrip("/")
  if target.startswith("wiki/"):
    target = target[len("wiki/"):]
  if target.endswith("/"):
    return None

  parts: list[str] = []
  for part in PurePosixPath(target).parts:
    if part in ("", "."):
      continue
    if part == "..":
      if parts:
        parts.pop()
      continue
    parts.append(part)
  if not parts:
    return None
  normalized = PurePosixPath(*parts).as_posix()
  if not normalized.endswith(".md"):
    normalized = f"{normalized}.md"
  return normalized


def canonical_index_rel_path_from_uri(kb_root: str, uri: str) -> str | None:
  wiki_prefix = kb_root + "wiki/"
  if not uri.startswith(wiki_prefix):
    return None
  rel = uri[len(wiki_prefix):].strip("/")
  parts = [part for part in rel.split("/") if part]
  if len(parts) < 2:
    return None
  if parts[0] not in SECTION_DIRS.values():
    return None
  if not parts[1].endswith(".md"):
    return None
  if parts[1] in WIKI_DERIVED_FILE_NAMES:
    return None
  return f"{parts[0]}/{parts[1]}"


def list_indexable_wiki_pages(client, kb_root: str, section_key: str | None = None) -> dict[str, list[str]]:
  result = {key: [] for key in SECTION_ORDER}
  keys = (section_key,) if section_key else SECTION_ORDER
  for key in keys:
    root_uri = kb_root + f"wiki/{SECTION_DIRS[key]}/"
    try:
      items = client.ls(root_uri, recursive=True)
    except Exception:
      items = []
    seen: set[str] = set()
    for item in items:
      uri = extract_uri_from_ls_item(item)
      if not uri:
        continue
      if isinstance(item, dict) and isinstance(item.get("isDir"), bool):
        is_dir = item["isDir"]
      else:
        stat = get_uri_stat(client, uri)
        is_dir = bool(stat and stat.get("isDir", False))
      if is_dir:
        continue
      name = PurePosixPath(uri).name
      if name in WIKI_DERIVED_FILE_NAMES:
        continue
      rel_path = canonical_index_rel_path_from_uri(kb_root, uri)
      if rel_path and rel_path.startswith(f"{SECTION_DIRS[key]}/") and rel_path not in seen:
        seen.add(rel_path)
        result[key].append(rel_path)
    result[key] = sorted(result[key], key=str.lower)
  return result


def detect_existing_section_headings(index_text: str) -> dict[str, str]:
  detected: dict[str, str] = {}
  for line in index_text.splitlines():
    stripped = line.strip()
    if not stripped.startswith("## "):
      continue
    for section_key, aliases in SECTION_HEADING_ALIASES.items():
      if stripped in aliases and section_key not in detected:
        detected[section_key] = stripped
  return detected


def parse_index_bullet_link_and_title(line: str) -> tuple[str, str | None] | None:
  stripped = line.strip()
  if not stripped.startswith("-"):
    return None

  wikilink = re.search(r"^-\s*\[\[([^\]]+)\]\](?:\s*-\s*(.*))?$", stripped)
  if wikilink:
    target = wikilink.group(1).split("|", 1)[0].strip()
    title = (wikilink.group(2) or "").strip() or None
    return target, title

  markdown = re.search(r"^-\s*\[([^\]]+)\]\(([^)]+)\)(?:\s*-\s*(.*))?$", stripped)
  if markdown:
    label = markdown.group(1).strip()
    target = markdown.group(2).strip()
    title = (markdown.group(3) or "").strip() or label or None
    return target, title

  return None


def parse_managed_index_bullet(line: str) -> tuple[str, str] | None:
  parsed = parse_index_bullet_link_and_title(line)
  if not parsed:
    return None
  target, _title = parsed
  rel_path = normalize_relative_wiki_target(target)
  if not rel_path:
    return None
  for section_key, section_dir in SECTION_DIRS.items():
    if rel_path.startswith(f"{section_dir}/") and rel_path.endswith(".md"):
      return section_key, rel_path
  return None


def parse_index_entry_map(index_text: str) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
  titles_by_section = {key: {} for key in SECTION_ORDER}
  order_by_section = {key: [] for key in SECTION_ORDER}
  current_section: str | None = None
  for line in index_text.splitlines():
    stripped = line.strip()
    if stripped.startswith("## "):
      current_section = None
      for section_key, aliases in SECTION_HEADING_ALIASES.items():
        if stripped in aliases:
          current_section = section_key
          break
      continue
    if current_section is None:
      continue
    parsed = parse_managed_index_bullet(line)
    if not parsed:
      continue
    parsed_section, rel_path = parsed
    bullet_meta = parse_index_bullet_link_and_title(line)
    title = bullet_meta[1] if bullet_meta else None
    section_key = parsed_section if parsed_section != current_section else current_section
    if not title:
      title = PurePosixPath(rel_path).stem
    if rel_path not in titles_by_section[section_key]:
      titles_by_section[section_key][rel_path] = title
      order_by_section[section_key].append(rel_path)
  return titles_by_section, order_by_section


def extract_title_from_markdown(markdown: str, fallback: str) -> str:
  for line in markdown.splitlines():
    stripped = line.strip()
    if stripped.startswith("# "):
      title = stripped[2:].strip()
      if title:
        return title
  return fallback


def read_page_title(client, kb_root: str, rel_path: str, fallback: str) -> str:
  page_uri = kb_root + "wiki/" + rel_path
  read_uri = resolve_canonical_markdown_uri(client, page_uri)
  if not read_uri:
    return fallback
  try:
    markdown = client.read_text(read_uri)
  except Exception:
    return fallback
  return extract_title_from_markdown(markdown, fallback)


def split_index_into_blocks(index_text: str) -> list[IndexSectionBlock]:
  pattern = re.compile(r"^##\s+.+$", re.MULTILINE)
  matches = list(pattern.finditer(index_text))
  blocks: list[IndexSectionBlock] = []
  if not matches:
    blocks.append(IndexSectionBlock(None, index_text, None, 0, len(index_text)))
    return blocks
  first = matches[0]
  blocks.append(IndexSectionBlock(None, index_text[:first.start()], None, 0, first.start()))
  for idx, match in enumerate(matches):
    end = matches[idx + 1].start() if idx + 1 < len(matches) else len(index_text)
    heading = match.group(0).strip()
    body = index_text[match.end():end]
    section_key = None
    for key, aliases in SECTION_HEADING_ALIASES.items():
      if heading in aliases:
        section_key = key
        break
    blocks.append(IndexSectionBlock(heading, body, section_key, match.start(), end))
  return blocks


def strip_managed_bullets_from_body(body: str) -> str:
  kept_lines: list[str] = []
  blank_count = 0
  for line in body.splitlines():
    if parse_managed_index_bullet(line):
      continue
    if line.strip():
      blank_count = 0
      kept_lines.append(line)
      continue
    blank_count += 1
    if blank_count <= 2:
      kept_lines.append(line)
  text = "\n".join(kept_lines).strip("\n")
  return text


def render_managed_section_body(section_key: str, entries: list[tuple[str, str]], preserved_body: str) -> str:
  bullet_lines = [f"- [[{rel_path}]] - {title}" for rel_path, title in entries]
  parts: list[str] = []
  if bullet_lines:
    parts.append("\n".join(bullet_lines))
  if preserved_body.strip():
    parts.append(preserved_body.strip("\n"))
  if not parts:
    return "\n"
  return "\n\n" + "\n\n".join(parts) + "\n"


def rebuild_index_text(client, kb_root: str, previous_index_text: str, touched_entries: dict[str, dict[str, str]] | None = None) -> str:
  touched_entries = touched_entries or {}
  if not previous_index_text:
    previous_index_text = "# 索引\n\n- [概览](./overview.md)\n- [操作日志](./log.md)\n"

  existing_headings = detect_existing_section_headings(previous_index_text)
  titles_by_section, order_by_section = parse_index_entry_map(previous_index_text)
  actual_pages = list_indexable_wiki_pages(client, kb_root)
  merged_pages: dict[str, list[str]] = {key: list(actual_pages[key]) for key in SECTION_ORDER}
  for section_key, rel_map in touched_entries.items():
    for rel_path in rel_map:
      if rel_path not in merged_pages[section_key]:
        merged_pages[section_key].append(rel_path)
    merged_pages[section_key] = sorted(merged_pages[section_key], key=str.lower)

  ordered_entries: dict[str, list[tuple[str, str]]] = {key: [] for key in SECTION_ORDER}
  for section_key in SECTION_ORDER:
    existing_order = [rel for rel in order_by_section[section_key] if rel in merged_pages[section_key]]
    new_order = [rel for rel in merged_pages[section_key] if rel not in existing_order]
    for rel_path in existing_order + sorted(new_order, key=str.lower):
      fallback = PurePosixPath(rel_path).stem
      title = touched_entries.get(section_key, {}).get(rel_path)
      if not title:
        title = titles_by_section[section_key].get(rel_path)
      if not title:
        title = read_page_title(client, kb_root, rel_path, fallback)
      ordered_entries[section_key].append((rel_path, title or fallback))

  blocks = split_index_into_blocks(previous_index_text)
  rendered_parts: list[str] = []
  seen_sections: set[str] = set()
  for block in blocks:
    if block.heading is None:
      rendered_parts.append(block.body)
      continue
    if block.section_key is None:
      rendered_parts.append(f"{block.heading}{block.body}")
      continue
    section_key = block.section_key
    seen_sections.add(section_key)
    preserved_body = strip_managed_bullets_from_body(block.body)
    heading = existing_headings.get(section_key, block.heading or CANONICAL_SECTION_HEADINGS[section_key])
    body = render_managed_section_body(section_key, ordered_entries[section_key], preserved_body)
    rendered_parts.append(f"{heading}{body}")

  for section_key in SECTION_ORDER:
    if section_key in seen_sections:
      continue
    heading = existing_headings.get(section_key, CANONICAL_SECTION_HEADINGS[section_key])
    body = render_managed_section_body(section_key, ordered_entries[section_key], "")
    rendered_parts.append(f"\n{heading}{body}")

  rebuilt = "".join(rendered_parts).rstrip("\n") + "\n"
  return rebuilt
```

同时把 `tests/skills/test_shared_script_consistency.py` 扩展为：

```python
def test_wiki_index_py_files_are_consistent_for_index_writers() -> None:
  skillNames = ["wiki-ingest", "wiki-save", "wiki-health", "wiki-query"]
  contents = [
    (repo_root / "skills" / skill_name / "scripts" / "wiki_index.py").read_text(encoding="utf-8")
    for skill_name in skillNames
  ]
  assert all(text == contents[0] for text in contents)
```

- [ ] **Step 4: 运行 helper 测试并确认通过**

Run: `python -m pytest tests/skills/test_index_rebuild.py tests/skills/test_shared_script_consistency.py -q`
Expected: PASS，输出包含 `6 passed` 或更多通过项，且无 `ModuleNotFoundError`。

- [ ] **Step 5: Commit**

```bash
git add skills/wiki-ingest/scripts/wiki_index.py skills/wiki-save/scripts/wiki_index.py skills/wiki-health/scripts/wiki_index.py skills/wiki-query/scripts/wiki_index.py tests/skills/test_index_rebuild.py tests/skills/test_shared_script_consistency.py
git commit -m "feat: add shared wiki index rebuild helper"
```

### Task 2: 接入 `wiki-ingest` 的 rebuild index 与确定性 log

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py`
- Test: `tests/skills/test_zh_language_defaults.py`
- Test: `tests/skills/test_ingest_chunking.py`

- [ ] **Step 1: 先写/补充 ingest 主流程失败测试**

在 `tests/skills/test_ingest_chunking.py` 增加一个最小主流程测试，验证结果包含 rebuild 字段：

```python
def test_main_outputs_rebuild_index_metadata(monkeypatch, capsys) -> None:
  class FakeClient:
    def __init__(self, _config) -> None:
      self.writeCalls = []

    def __enter__(self):
      return self

    def __exit__(self, excType, exc, tb) -> None:
      return None

    def stat(self, uri: str):
      if uri.endswith("wiki/sources/source.md"):
        raise module.OVFSHTTPError("404")
      return {"isDir": False}

    def ls(self, uri: str, recursive: bool = False):
      return []

    def read_text(self, uri: str) -> str:
      if uri.endswith("wiki/index.md"):
        return "# 索引\n"
      if uri.endswith("wiki/overview.md"):
        return "# 概览\n"
      if uri.endswith("wiki/log.md"):
        return "# 操作日志\n"
      return "raw"

    def write_text(self, uri: str, content: str, create: bool, wait: bool) -> None:
      self.writeCalls.append((uri, create, wait))

  monkeypatch.setattr(module, "OVFSClient", FakeClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())
  monkeypatch.setattr(module, "read_local_schema", lambda: "schema")
  monkeypatch.setattr(module, "resolve_openai_settings", lambda args: {"api_key": "k", "base_url": None, "model": "m"})
  monkeypatch.setattr(module, "resolve_ingest_source_bundle", lambda client, uri: module.IngestSourceBundle(root_uri=uri, markdown_uris=[uri], ignored_metadata_uris=[], source_kind="file"))
  monkeypatch.setattr(module, "read_source_bundle_text", lambda client, bundle: "source body")
  monkeypatch.setattr(module, "call_llm", lambda prompt, *, api_key, base_url, model: {
    "source_title": "来源标题",
    "source_page_markdown": "# 来源标题\n\n正文\n",
    "entity_pages": [],
    "concept_pages": [],
    "overview_note": "概览补充",
    "log_note": "说明",
  })
  monkeypatch.setattr(sys, "argv", ["ingest.py", "--kb-name", "demo", "--source-uri", "viking://resources/demo/raw/source.md", "--dry-run"])

  code = module.main()
  output = json.loads(capsys.readouterr().out)
  assert code == 0
  assert output["index_update_mode"] == "rebuild"
  assert output["touched_index_entries"]["sources"] == {"sources/source.md": "来源标题"}
```

- [ ] **Step 2: 运行 ingest 定向测试并确认失败**

Run: `python -m pytest tests/skills/test_ingest_chunking.py::test_main_outputs_rebuild_index_metadata tests/skills/test_zh_language_defaults.py -q`
Expected: FAIL，当前输出缺少 `index_update_mode` / `touched_index_entries`，或仍走 `update_index_text()`。

- [ ] **Step 3: 在 `ingest.py` 接入 helper 与确定性 log**

在 `skills/wiki-ingest/scripts/ingest.py` 顶部新增：

```python
from wiki_index import rebuild_index_text
```

在 `append_log_entry()` 之后新增：

```python
def build_ingest_log_entry(source_slug: str, source_title: str, log_note: str) -> str:
    base = (
        f"已 ingest source: {source_title}; "
        f"source_slug={source_slug}; "
        f"source_page=wiki/sources/{source_slug}.md"
    )
    if log_note.strip():
        return base + f"; note={log_note.strip()}"
    return base
```

把主流程中的 index/log 更新代码替换为：

```python
            touched_entries = {
                "sources": {
                    f"sources/{source_slug}.md": source_title,
                },
                "entities": {
                    f"entities/{page['slug']}.md": page["title"]
                    for page in entity_pages
                },
                "concepts": {
                    f"concepts/{page['slug']}.md": page["title"]
                    for page in concept_pages
                },
            }

            new_index_text = rebuild_index_text(
                client,
                kb_root,
                context["index_text"],
                touched_entries=touched_entries,
            )
            new_overview_text = append_overview_note(context["overview_text"], overview_note, source_title)
            new_log_text = append_log_entry(
                context["log_text"],
                build_ingest_log_entry(source_slug, source_title, log_note),
            )
```

把结果对象扩展为：

```python
                "index_update_mode": "rebuild",
                "touched_index_entries": touched_entries,
```

- [ ] **Step 4: 运行 ingest 相关测试并确认通过**

Run: `python -m pytest tests/skills/test_ingest_chunking.py tests/skills/test_zh_language_defaults.py -q`
Expected: PASS，`update_index_text()` 旧兼容测试仍通过，新的主流程输出字段测试通过。

- [ ] **Step 5: Commit**

```bash
git add skills/wiki-ingest/scripts/ingest.py tests/skills/test_ingest_chunking.py tests/skills/test_zh_language_defaults.py
git commit -m "feat: rebuild index during wiki ingest"
```

### Task 3: 接入 `wiki-save` 的 rebuild index 与 bundle-safe index 写入

**Files:**
- Modify: `skills/wiki-save/scripts/save.py`
- Modify: `tests/skills/test_save_updates.py`

- [ ] **Step 1: 先写 save 失败测试**

在 `tests/skills/test_save_updates.py` 增加：

```python
def test_save_rebuilds_index_and_preserves_manual_sections(monkeypatch, tmp_path: Path, capsys) -> None:
  answerPath = tmp_path / "answer.md"
  answerPath.write_text("答案", encoding="utf-8")
  createdClients = []

  class FakeClient:
    def __init__(self, _config) -> None:
      self.writeCalls: list[tuple[str, str, bool, bool]] = []

    def __enter__(self):
      return self

    def __exit__(self, excType, exc, tb) -> None:
      return None

    def stat(self, uri: str):
      if uri.endswith("wiki/syntheses/t.md"):
        raise module.OVFSHTTPError("404")
      if uri.endswith("wiki/index.md"):
        return {"isDir": True}
      return {"isDir": False}

    def ls(self, uri: str, recursive: bool = False):
      if uri.endswith("wiki/index.md/"):
        return []
      return []

    def read_text(self, uri: str) -> str:
      if uri.endswith("index.md"):
        return "# 索引\n\n## 资料来源\n- [[sources/old.md]] - Old\n\n## 自定义说明\n手工备注\n"
      if uri.endswith("overview.md"):
        return "# 概览\n"
      if uri.endswith("log.md"):
        return "# 操作日志\n"
      return "# 新标题\n\n正文\n"

    def write_text(self, uri: str, content: str, create: bool, wait: bool) -> None:
      self.writeCalls.append((uri, content, create, wait))

  def makeClient(config):
    client = FakeClient(config)
    createdClients.append(client)
    return client

  monkeypatch.setattr(sys, "argv", ["save.py", "--kb-name", "kb", "--answer-file", str(answerPath), "--question", "q", "--title", "t"])
  monkeypatch.setattr(module, "OVFSClient", makeClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())

  code = module.main()
  output = json.loads(capsys.readouterr().out)
  fakeClient = createdClients[0]
  writtenIndex = next(
    content
    for uri, content, _create, _wait in fakeClient.writeCalls
    if uri.endswith("wiki/index.md/index.md")
  )
  assert code == 0
  assert output["index_update_mode"] == "rebuild"
  assert output["touched_index_entries"]["syntheses"] == {"syntheses/t.md": "t"}
  assert any(uri.endswith("wiki/index.md/index.md") for uri, _content, _create, _wait in fakeClient.writeCalls)
  assert "## 自定义说明" in writtenIndex
  assert "手工备注" in writtenIndex
```

- [ ] **Step 2: 运行 save 定向测试并确认失败**

Run: `python -m pytest tests/skills/test_save_updates.py::test_save_rebuilds_index_and_preserves_manual_sections -q`
Expected: FAIL，当前输出缺少 `index_update_mode`，或 index 仍通过 `upsert_index_link_bullet()` 局部更新。

- [ ] **Step 3: 在 `save.py` 接入 helper**

在 `skills/wiki-save/scripts/save.py` 顶部新增：

```python
from wiki_index import rebuild_index_text, resolve_markdown_write_target_uri
```

把 index 更新改为：

```python
      linkPath = f"syntheses/{finalSlug}.md"
      touched_entries = {
        "syntheses": {
          linkPath: normalizedInput["title"],
        },
      }
      newIndexText = rebuild_index_text(
        client,
        kbRoot,
        indexText,
        touched_entries=touched_entries,
      )
```

把 index 写入改为：

```python
        indexWriteUri, indexShouldCreate = resolve_markdown_write_target_uri(
          client,
          kbRoot + "wiki/index.md",
        )
        client.write_text(indexWriteUri, newIndexText, create=indexShouldCreate, wait=False)
```

把结果对象扩展为：

```python
        "index_update_mode": "rebuild",
        "touched_index_entries": touched_entries,
```

- [ ] **Step 4: 运行 save 测试并确认通过**

Run: `python -m pytest tests/skills/test_save_updates.py tests/skills/test_save_payload.py -q`
Expected: PASS，包含旧 payload/overview 行为测试和新的 rebuild 字段测试。

- [ ] **Step 5: Commit**

```bash
git add skills/wiki-save/scripts/save.py tests/skills/test_save_updates.py
git commit -m "feat: rebuild index during wiki save"
```

### Task 4: 接入 legacy `wiki-query --save` 的 rebuild index

**Files:**
- Modify: `skills/wiki-query/scripts/query.py`
- Modify: `tests/skills/test_query_save_legacy_semantics.py`

- [ ] **Step 1: 先写 legacy save 失败测试**

在 `tests/skills/test_query_save_legacy_semantics.py` 里把主断言扩展为：

```python
  assert output["index_update_mode"] == "rebuild"
  writtenIndex = next(content for uri, content, _create in fakeClient.writeCalls if uri == "viking://resources/kb/wiki/index.md")
  assert "## 综合结论" in writtenIndex
  assert "syntheses/标题.md" in writtenIndex
  assert "<!-- synthesis:syntheses/标题.md:start -->" not in writtenIndex
```

再补一个保留非 managed 内容的测试：

```python
def test_legacy_save_preserves_non_managed_index_content(monkeypatch, capsys) -> None:
  class FakeClient(FakeOVFSClient):
    def read_text(self, uri: str) -> str:
      if uri.endswith("wiki/index.md"):
        return "# 索引\n\n## 自定义说明\n手工备注\n\n## 综合结论\n- [[syntheses/标题.md]] - 旧标题\n"
      if uri.endswith("wiki/overview.md"):
        return "# 概览\n"
      return "# 操作日志\n"

  fakeClient = FakeClient(None)
  monkeypatch.setattr(sys, "argv", ["query.py", "--kb-name", "kb", "--question", "q", "--save", "--slug", "标题"])
  monkeypatch.setattr(queryModule, "OVFSClient", lambda _config: fakeClient)
  monkeypatch.setattr(queryModule.OVFSConfig, "load", lambda config_path=None, profile=None: object())
  monkeypatch.setattr(queryModule, "read_local_schema", lambda: "schema")
  monkeypatch.setattr(queryModule, "select_relevant_pages", lambda client, kb_root, question, top_k: [{"uri": "u1", "content": "c", "score": "1"}])
  monkeypatch.setattr(queryModule, "call_llm", lambda prompt, *, api_key, base_url, model: {"answer_markdown": "当前答案", "used_pages": ["u1"], "synthesis_title": "新标题"})
  monkeypatch.setattr(queryModule, "resolve_openai_settings", lambda args: {"api_key": "k", "base_url": None, "model": "m"})
  monkeypatch.setattr(queryModule, "write_temp_json_file", lambda data, pretty: Path("/tmp/payload.json"))

  code = queryModule.main()
  output = json.loads(capsys.readouterr().out)
  assert code == 0
  assert output["index_update_mode"] == "rebuild"
  writtenIndex = next(content for uri, content, _create in fakeClient.writeCalls if uri == "viking://resources/kb/wiki/index.md")
  assert "## 自定义说明" in writtenIndex
  assert "手工备注" in writtenIndex
```

- [ ] **Step 2: 运行 legacy save 测试并确认失败**

Run: `python -m pytest tests/skills/test_query_save_legacy_semantics.py -q`
Expected: FAIL，当前输出缺少 `index_update_mode`，且 index 仍是局部 upsert。

- [ ] **Step 3: 在 `query.py` 接入 helper rebuild**

在 `skills/wiki-query/scripts/query.py` 顶部新增：

```python
from wiki_index import rebuild_index_text
```

把 legacy save 分支中的 index 更新替换为：

```python
                touched_entries = {
                    "syntheses": {
                        link_path: synthesis_title,
                    },
                }
                new_index_text = rebuild_index_text(
                    client,
                    kb_root,
                    index_text,
                    touched_entries=touched_entries,
                )
```

把结果对象扩展为：

```python
                result["index_update_mode"] = "rebuild"
                result["touched_index_entries"] = touched_entries
```

- [ ] **Step 4: 运行 query 相关测试并确认通过**

Run: `python -m pytest tests/skills/test_query_save_legacy_semantics.py tests/skills/test_query_args.py tests/skills/test_query_save_payload.py -q`
Expected: PASS，legacy save 保留旧字段且新增 rebuild 字段。

- [ ] **Step 5: Commit**

```bash
git add skills/wiki-query/scripts/query.py tests/skills/test_query_save_legacy_semantics.py
git commit -m "feat: rebuild index during legacy query save"
```

### Task 5: 扩展 `wiki-health` 诊断与 `--repair-index`

**Files:**
- Modify: `skills/wiki-health/scripts/health.py`
- Modify: `skills/wiki-health/SKILL.md`
- Modify: `tests/skills/test_health_checks.py`

- [ ] **Step 1: 先写 health 失败测试**

在 `tests/skills/test_health_checks.py` 增加：

```python
def test_duplicate_index_targets_are_reported() -> None:
  duplicates = module.check_duplicate_index_targets("## 实体\n- [[entities/aihub.md]] - AIHub\n- [[entities/aihub.md]] - aihub\n")
  assert duplicates == ["entities/aihub.md"]


def test_unindexed_wiki_pages_are_reported_as_error() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  stats = {
    **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
    **{uri: {"isDir": False} for uri in required_file_uris},
    f"{kb_root}wiki/sources/a.md/a.md": {"isDir": False},
    f"{kb_root}wiki/sources/b.md/b.md": {"isDir": False},
  }
  texts = {
    required_file_uris[0]: "# 索引\n\n## 资料来源\n- [[sources/a.md]] - A\n",
    required_file_uris[1]: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
    required_file_uris[2]: "# 操作日志\n\nsource a\n",
    f"{kb_root}wiki/sources/a.md/a.md": "# A\n\n正文\n",
    f"{kb_root}wiki/sources/b.md/b.md": "# B\n\n正文\n",
  }

  class IndexableClient(FakeClient):
    def ls(self, uri: str, recursive: bool = False):
      if uri == f"{kb_root}wiki/sources/" and recursive:
        return [
          {"uri": f"{kb_root}wiki/sources/a.md/a.md", "isDir": False},
          {"uri": f"{kb_root}wiki/sources/b.md/b.md", "isDir": False},
        ]
      return []

  report = build_report(IndexableClient(texts=texts, stats=stats), kb_root)
  assert report["status"] == "error"
  assert f"{kb_root}wiki/sources/b.md" in report["details"]["unindexed_wiki_pages"]


def test_source_log_title_match_does_not_false_positive() -> None:
  kb_root = "viking://resources/my-kb/"
  sourceUri = f"{kb_root}wiki/sources/axon.md/axon.md"

  class LogClient(FakeClient):
    def ls(self, uri: str, recursive: bool = False):
      if uri == f"{kb_root}wiki/sources/" and recursive:
        return [{"uri": sourceUri, "isDir": False}]
      return []

  stats = {
    f"{kb_root}wiki/log.md": {"isDir": False},
    f"{kb_root}wiki/sources/axon.md": {"isDir": True},
    sourceUri: {"isDir": False},
  }
  texts = {
    f"{kb_root}wiki/log.md": "# 操作日志\n\nIngested source: Axon·灵犀 智能软件工厂\n",
    sourceUri: "# Axon·灵犀 智能软件工厂\n\n正文\n",
  }
  missing = module.check_source_log_coverage(LogClient(texts=texts, stats=stats), kb_root)
  assert missing == []


def test_source_log_slug_missing_still_warns() -> None:
  kb_root = "viking://resources/my-kb/"
  sourceUri = f"{kb_root}wiki/sources/debug-write-probe-after-vlm-fix.md/debug-write-probe-after-vlm-fix.md"

  class MissingLogClient(FakeClient):
    def ls(self, uri: str, recursive: bool = False):
      if uri == f"{kb_root}wiki/sources/" and recursive:
        return [{"uri": sourceUri, "isDir": False}]
      return []

  stats = {
    f"{kb_root}wiki/log.md": {"isDir": False},
    f"{kb_root}wiki/sources/debug-write-probe-after-vlm-fix.md": {"isDir": True},
    sourceUri: {"isDir": False},
  }
  texts = {
    f"{kb_root}wiki/log.md": "# 操作日志\n\nother entry\n",
    sourceUri: "# debug-write-probe-after-vlm-fix\n\n正文\n",
  }
  missing = module.check_source_log_coverage(MissingLogClient(texts=texts, stats=stats), kb_root)
  assert missing == [f"{kb_root}wiki/sources/debug-write-probe-after-vlm-fix.md"]
```

- [ ] **Step 2: 运行 health 定向测试并确认失败**

Run: `python -m pytest tests/skills/test_health_checks.py -q`
Expected: FAIL，当前 `health.py` 还没有 `duplicate_index_targets` / `unindexed_wiki_pages` / 多 token log 匹配。

- [ ] **Step 3: 在 `health.py` 接入 helper 与 repair 模式**

把顶部导入替换为：

```python
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
```

新增这些函数：

```python
def extract_index_links(index_text: str) -> set[str]:
  return set(extract_index_link_occurrences(index_text))


def extract_index_link_occurrences(index_text: str) -> list[str]:
  results: list[str] = []
  wikilinkPattern = re.compile(r"\[\[([^\]]+)\]\]")
  markdownLinkPattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
  for raw in wikilinkPattern.findall(index_text):
    normalized = normalize_relative_wiki_target(raw.split("|", 1)[0].strip())
    if normalized:
      results.append(normalized)
  for raw in markdownLinkPattern.findall(index_text):
    normalized = normalize_relative_wiki_target(raw)
    if normalized:
      results.append(normalized)
  return results


def check_duplicate_index_targets(index_text: str) -> list[str]:
  seen: set[str] = set()
  duplicates: set[str] = set()
  for target in extract_index_link_occurrences(index_text):
    if target in seen:
      duplicates.add(target)
    seen.add(target)
  return sorted(duplicates)


def check_unindexed_wiki_pages(client, kb_root: str, linked_targets: set[str]) -> list[str]:
  pages = list_indexable_wiki_pages(client, kb_root)
  missing: list[str] = []
  for section_key in ("sources", "entities", "concepts", "syntheses"):
    for rel_path in pages[section_key]:
      if rel_path not in linked_targets:
        missing.append(kb_root + "wiki/" + rel_path)
  return missing


def source_log_match_tokens(client, kb_root: str, rel_path: str) -> set[str]:
  stem = PurePosixPath(rel_path).stem.lower()
  title = read_page_title(client, kb_root, rel_path, PurePosixPath(rel_path).stem).lower()
  return {
    f"wiki/{rel_path}".lower(),
    rel_path.lower(),
    stem,
    title,
  }
```

并把 `check_index_targets()` 保持为使用这个新版 `extract_index_links()`，不要继续混用 `health.py` 里旧的 link 解析语义。

把 `check_source_log_coverage()` 替换为：

```python
def check_source_log_coverage(client: OVFSClient, kbRoot: str) -> list[str]:
  logUri = f"{kbRoot}wiki/log.md"
  canonicalLogUri = resolve_canonical_markdown_uri(client, logUri)
  if not canonicalLogUri:
    return []
  logText = client.read_text(canonicalLogUri).lower()
  pages = list_indexable_wiki_pages(client, kbRoot, section_key="sources")["sources"]
  missing: list[str] = []
  for relPath in pages:
    tokens = {token.strip().lower() for token in source_log_match_tokens(client, kbRoot, relPath) if token.strip()}
    if not any(token in logText for token in tokens):
      missing.append(kbRoot + "wiki/" + relPath)
  return missing
```

把 `build_report()` 扩展为：

```python
  canonicalIndexUri = resolve_canonical_markdown_uri(client, kbRoot + "wiki/index.md")
  indexText = client.read_text(canonicalIndexUri) if canonicalIndexUri else ""
  indexLinkOccurrences = extract_index_link_occurrences(indexText)
  duplicateIndexTargets = check_duplicate_index_targets(indexText)
  unindexedWikiPages = check_unindexed_wiki_pages(client, kbRoot, set(linkedTargets))
```

并在 `summary` / `details` / `errors` / `warnings` 里加入计划要求字段。

把 CLI 增加为：

```python
  parser.add_argument("--repair-index", action="store_true", help="重建 wiki/index.md，不删除页面，不调用 LLM")
```

在 `main()` 里处理 repair：

```python
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
```

最后更新 `skills/wiki-health/SKILL.md` 为：

````markdown
默认 wiki-health 只做结构完整性检查，不写远端。

当用户明确要求“修复 index / 重建 index / repair index”时，可以使用：

    bash ~/.config/opencode/skills/wiki-health/scripts/run.sh \
      --kb-name <kb-name> \
      --profile <profile> \
      --repair-index \
      --pretty

该模式只重建 wiki/index.md，不删除页面，不调用 LLM，并保留 index 中 managed section 之外的手工内容。
````

- [ ] **Step 4: 运行 health 测试并确认通过**

Run: `python -m pytest tests/skills/test_health_checks.py -q`
Expected: PASS，`health.py` 仍可被 `spec_from_file_location(...).exec_module(...)` 直接加载，无 `ModuleNotFoundError`。

- [ ] **Step 5: Commit**

```bash
git add skills/wiki-health/scripts/health.py skills/wiki-health/SKILL.md tests/skills/test_health_checks.py
git commit -m "feat: add index diagnostics and repair to wiki health"
```

### Task 6: 跑全量技能测试并验证 `xiay` 真实知识库行为

**Files:**
- Modify: `tests/skills/test_zh_language_defaults.py`
- Verify: `skills/wiki-ingest/scripts/ingest.py`
- Verify: `skills/wiki-save/scripts/save.py`
- Verify: `skills/wiki-query/scripts/query.py`
- Verify: `skills/wiki-health/scripts/health.py`

- [ ] **Step 1: 补充 legacy heading 与 `# Index` 保留测试**

在 `tests/skills/test_zh_language_defaults.py` 增加：

```python
def test_rebuild_index_text_preserves_legacy_english_headings() -> None:
  helperPath = repoRoot / "skills" / "wiki-ingest" / "scripts" / "wiki_index.py"
  sys.path.insert(0, str(helperPath.parent))
  spec = spec_from_file_location("wiki_index_helper_for_zh", helperPath)
  if spec is None or spec.loader is None:
    raise RuntimeError("无法加载 skills/wiki-ingest/scripts/wiki_index.py")
  helper = module_from_spec(spec)
  sys.modules[spec.name] = helper
  spec.loader.exec_module(helper)

  class FakeClient:
    def stat(self, uri: str):
      raise RuntimeError("404")
    def ls(self, uri: str, recursive: bool = False):
      return []
    def read_text(self, uri: str) -> str:
      return ""

  rebuilt = helper.rebuild_index_text(
    FakeClient(),
    "viking://resources/demo/",
    "# Index\n\n- [Overview](./overview.md)\n\n## Sources\n\n## Entities\n\n## Concepts\n\n## Syntheses\n",
  )

  assert rebuilt.startswith("# Index")
  assert "## Sources" in rebuilt
  assert "## Entities" in rebuilt
  assert "## Concepts" in rebuilt
  assert "## Syntheses" in rebuilt
  assert "## 资料来源" not in rebuilt
```

- [ ] **Step 2: 运行本地全量测试**

Run: `python -m pytest tests/skills -q`
Expected: PASS，所有技能测试通过，无新增依赖错误。

- [ ] **Step 3: 运行真实 `xiay` health 验证修复前报告**

Run: `bash ~/.config/opencode/skills/wiki-health/scripts/run.sh --kb-name xiay --profile ESF --pretty`
Expected: `broken_index_targets` 包含 `viking://resources/xiay/wiki/sources/aihub-知识库使用指南-3more-a4030a3b.md`，`unindexed_wiki_pages` 包含 `viking://resources/xiay/wiki/sources/debug-write-probe-after-vlm-fix.md`，`duplicate_index_targets` 包含 `entities/aihub.md`。

- [ ] **Step 4: 运行真实 `xiay` repair 验证修复后报告**

Run: `bash ~/.config/opencode/skills/wiki-health/scripts/run.sh --kb-name xiay --profile ESF --repair-index --pretty`
Expected: `broken_index_targets = 0`，`unindexed_wiki_pages = 0`，`wiki/index.md` 包含 `sources/debug-write-probe-after-vlm-fix.md` 且不再包含 `sources/aihub-知识库使用指南-3more-a4030a3b.md`，如果仍有 source-log warning，仅限日志缺失本身。

- [ ] **Step 5: Commit**

```bash
git add tests/skills/test_zh_language_defaults.py
git commit -m "test: cover legacy headings and index rebuild regression"
```

## Self-Review

- Spec coverage: 已覆盖 helper 统一实现、ingest/save/legacy query-save 接入、health 诊断与 repair、SKILL.md 更新、共享一致性测试、legacy heading 测试、真实 `xiay` 验收命令与注意点。
- Placeholder scan: 文档中没有 `TODO`、`TBD`、`implement later`、`similar to Task N` 这类占位描述；所有代码步骤都给了具体代码或明确替换片段。
- Type consistency: helper 统一使用 `rebuild_index_text()`、`resolve_markdown_write_target_uri()`、`list_indexable_wiki_pages()`、`read_page_title()`；主流程输出统一使用 `index_update_mode` 与 `touched_index_entries`。
