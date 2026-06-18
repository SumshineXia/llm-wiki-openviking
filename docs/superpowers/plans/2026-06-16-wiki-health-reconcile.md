# wiki-health 被动式一致性检查与安全修复工具 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `wiki-health` 从单纯结构检查升级为被动式 reconcile/repair 工具，检测并安全修复用户在 OpenViking 控制台直接操作造成的 index/log 漂移、raw 未 ingest、wiki 根目录异常条目等问题。

**Architecture:** 远端文件系统是事实源。`index.md` 可重建，`log.md` 只追加 health-reconcile 补录行，不调用 LLM，不删除/移动页面。默认只检查，用户显式传 repair 参数时才写远端。所有读写操作通过 `resolve_canonical_markdown_uri` / `resolve_markdown_write_target_uri` 兼容 OpenViking bundle 目录。

**Tech Stack:** Python 3.9+, pytest, requests（OVFSClient HTTP 适配器）

---

## 修改文件总览

| 文件 | 职责 |
|---|---|
| `skills/wiki-health/scripts/health.py` | 所有新增检查函数、repair 函数、main 流程 |
| `tests/skills/test_health_checks.py` | 新增测试 + 更新现有 repair-index 测试断言 |
| `skills/wiki-health/SKILL.md` | 职责边界和命令示例更新 |
| `README.md`（可选） | 补充 repair 用法 |

**不要修改：** `wiki-ingest/ingest.py`、`wiki-save/save.py`、`wiki-query/query.py`、四份 `wiki_index.py`。

---

## 现有代码关键上下文

health.py 模块加载方式（测试中）：
```python
spec = spec_from_file_location("wiki_health_script", module_path)
module = module_from_spec(spec)
spec.loader.exec_module(module)
```

测试 FakeClient 模式：
```python
class FakeClient:
    def __init__(self, texts, stats, listings=None): ...
    def read_text(self, uri): return self.texts[uri]
    def stat(self, uri): ...  # raise OVFSHTTPError("404") if missing
    def ls(self, uri, recursive=False): ...
```

RepairClient 扩展 FakeClient，增加 `__enter__`/`__exit__`/`write_text`。

main() 测试 monkeypatch 模式：
```python
monkeypatch.setattr(module.OVFSConfig, "load", staticmethod(lambda config_path=None, profile=None: object()))
monkeypatch.setattr(module, "OVFSClient", lambda config: repair_client)
monkeypatch.setattr(module, "build_kb_root", lambda kb_name: kb_root)
monkeypatch.setattr(module, "print_json", lambda data, pretty=False: printed.append(data))
monkeypatch.setattr(module.sys, "argv", ["health.py", ...])
```

health.py 关键 import（已存在，本次新增 `datetime`）：
```python
from ovfs import OVFSClient, OVFSConfig, OVFSError, OVFSHTTPError
from wiki_index import (
    resolve_canonical_markdown_uri,
    resolve_markdown_write_target_uri,
    list_indexable_wiki_pages,
    rebuild_index_text,
    read_page_title,
)
```

---

## Task 1: Foundation — constants, stat_is_dir, slug/hash helpers

**Files:**
- Modify: `skills/wiki-health/scripts/health.py`（imports + 常量 + 新增 helper 函数）
- Test: `tests/skills/test_health_checks.py`

- [ ] **Step 1: 写失败测试 — stat_is_dir + slugify + hash 后缀**

在 `tests/skills/test_health_checks.py` 文件末尾追加：

```python
def test_stat_is_dir_handles_various_stat_shapes() -> None:
  stat_is_dir = module.stat_is_dir
  assert stat_is_dir(None) is False
  assert stat_is_dir({"isDir": True}) is True
  assert stat_is_dir({"isDir": False}) is False
  assert stat_is_dir({"is_dir": True}) is True
  assert stat_is_dir({"type": "directory"}) is True
  assert stat_is_dir({"type": "file"}) is False


def test_slugify_matches_ingest_logic() -> None:
  assert module.slugify("AIHub_用户指南") == "aihub-用户指南"
  assert module.slugify("README__5e5947c8") == "readme-5e5947c8"
  assert module.slugify("  Hello World  ") == "hello-world"


def test_candidate_source_slugs_includes_hash_stripped_variant() -> None:
  uri = "viking://resources/esf/raw/README__5e5947c8ee9740d68e3f926e2877dcf9"
  candidates = module.candidate_source_slugs_from_raw_child_uri(uri)
  assert "readme-5e5947c8ee9740d68e3f926e2877dcf9" in candidates
  assert "readme" in candidates


def test_candidate_source_slugs_without_hash_suffix() -> None:
  uri = "viking://resources/esf/raw/aihub_kb_opencode_usage_guide_revised_draft.md"
  candidates = module.candidate_source_slugs_from_raw_child_uri(uri)
  assert candidates == ["aihub-kb-opencode-usage-guide-revised-draft"]


def test_list_markdown_pages_ignores_bundle_abstract_metadata() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  source_page = f"{kb_root}wiki/sources/readme.md/readme.md"
  abstract_page = f"{kb_root}wiki/sources/readme.md/abstract.md"
  client = FakeClient(
    texts={
      required_file_uris[0]: "# 索引\n\n## 资料来源\n- [[sources/readme.md]] - README\n",
      required_file_uris[1]: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      required_file_uris[2]: "# 操作日志\n\nreadme\n",
      source_page: "# README\n\n正文内容足够长用于通过判断。\n",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      **{uri: {"isDir": False} for uri in required_file_uris},
      f"{kb_root}wiki/sources/readme.md": {"isDir": True},
      source_page: {"isDir": False},
      abstract_page: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/sources/", True): [
        {"uri": source_page, "isDir": False},
        {"uri": abstract_page, "isDir": False},
      ],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": uri, "isDir": False} for uri in required_file_uris
      ] + [{"uri": source_page, "isDir": False}],
    },
  )

  report = build_report(client, kb_root)

  assert report["summary"]["source_pages"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_stat_is_dir_handles_various_stat_shapes tests/skills/test_health_checks.py::test_slugify_matches_ingest_logic tests/skills/test_health_checks.py::test_candidate_source_slugs_includes_hash_stripped_variant tests/skills/test_health_checks.py::test_candidate_source_slugs_without_hash_suffix tests/skills/test_health_checks.py::test_list_markdown_pages_ignores_bundle_abstract_metadata -v
```
Expected: FAIL — `AttributeError: module has no attribute 'stat_is_dir'`

- [ ] **Step 3: 实现 — 添加 import、常量、helper 函数**

3a. 在 health.py 顶部 import 区域（第6行 `import sys` 之后）添加：

```python
from datetime import datetime, timezone
```

3b. 将第58行的 `derivedFileNames = {".abstract.md", ".overview.md", ".relations.json"}` 替换为：

```python
WIKI_DERIVED_FILE_NAMES = {".abstract.md", ".overview.md", ".relations.json"}
BUNDLE_METADATA_FILE_NAMES = {"abstract.md"}
DERIVED_OR_METADATA_FILE_NAMES = WIKI_DERIVED_FILE_NAMES | BUNDLE_METADATA_FILE_NAMES

derivedFileNames = DERIVED_OR_METADATA_FILE_NAMES
```

3c. 在 `derivedFileNames` 之后，`extract_uri_from_ls_item` 之前，添加常量和 helper 函数：

```python
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
```

3d. 在 `list_markdown_pages` 函数中（当前约第142行），将：
```python
      isDir = bool(stat and stat.get("isDir", False))
```
改为：
```python
      isDir = stat_is_dir(stat)
```

3e. 在 `check_required_structure` 函数中（当前约第213行），将：
```python
    if not stat or not stat.get("isDir", False):
      missingDirs.append(uri)
```
改为：
```python
    if not stat_is_dir(stat):
      missingDirs.append(uri)
```

- [ ] **Step 4: 运行新测试确认通过**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_stat_is_dir_handles_various_stat_shapes tests/skills/test_health_checks.py::test_slugify_matches_ingest_logic tests/skills/test_health_checks.py::test_candidate_source_slugs_includes_hash_stripped_variant tests/skills/test_health_checks.py::test_candidate_source_slugs_without_hash_suffix tests/skills/test_health_checks.py::test_list_markdown_pages_ignores_bundle_abstract_metadata -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: 运行全部现有测试确认无回归**

```bash
python3 -m pytest tests/skills/test_health_checks.py tests/skills/test_index_rebuild.py -v
```
Expected: PASS (33 tests)

- [ ] **Step 6: Commit**

```bash
git add skills/wiki-health/scripts/health.py tests/skills/test_health_checks.py
git commit -m "feat(wiki-health): add constants, stat_is_dir, slug/hash helpers"
```

---

## Task 2: check_unexpected_wiki_root_entries

**Files:**
- Modify: `skills/wiki-health/scripts/health.py`
- Test: `tests/skills/test_health_checks.py`

- [ ] **Step 1: 写失败测试 — check_unexpected_wiki_root_entries（纯函数）**

在测试文件末尾追加：

```python
def test_check_unexpected_wiki_root_entries_finds_manual_page() -> None:
  kb_root = "viking://resources/my-kb/"
  manual_uri = f"{kb_root}wiki/manual.md"
  client = FakeClient(
    texts={},
    stats={},
    listings={
      (f"{kb_root}wiki/", False): [
        {"uri": f"{kb_root}wiki/index.md", "isDir": False},
        {"uri": f"{kb_root}wiki/overview.md", "isDir": False},
        {"uri": f"{kb_root}wiki/log.md", "isDir": False},
        {"uri": manual_uri, "isDir": False},
        {"uri": f"{kb_root}wiki/sources", "isDir": True},
        {"uri": f"{kb_root}wiki/entities", "isDir": True},
        {"uri": f"{kb_root}wiki/concepts", "isDir": True},
        {"uri": f"{kb_root}wiki/syntheses", "isDir": True},
      ],
    },
  )

  result = module.check_unexpected_wiki_root_entries(client, kb_root)
  assert result == [manual_uri]


def test_check_unexpected_wiki_root_entries_empty_when_all_standard() -> None:
  kb_root = "viking://resources/my-kb/"
  client = FakeClient(
    texts={},
    stats={},
    listings={
      (f"{kb_root}wiki/", False): [
        {"uri": f"{kb_root}wiki/index.md", "isDir": False},
        {"uri": f"{kb_root}wiki/overview.md", "isDir": False},
        {"uri": f"{kb_root}wiki/log.md", "isDir": False},
        {"uri": f"{kb_root}wiki/sources", "isDir": True},
        {"uri": f"{kb_root}wiki/entities", "isDir": True},
        {"uri": f"{kb_root}wiki/concepts", "isDir": True},
        {"uri": f"{kb_root}wiki/syntheses", "isDir": True},
      ],
    },
  )

  result = module.check_unexpected_wiki_root_entries(client, kb_root)
  assert result == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_check_unexpected_wiki_root_entries_finds_manual_page tests/skills/test_health_checks.py::test_check_unexpected_wiki_root_entries_empty_when_all_standard -v
```
Expected: FAIL — `AttributeError: module has no attribute 'check_unexpected_wiki_root_entries'`

- [ ] **Step 3: 实现 check_unexpected_wiki_root_entries**

在 health.py 的 `check_nested_resource_dirs` 函数之后，添加：

```python
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
```

注意：此函数在 Task 6 中会被 `build_report` 调用，届时 `details["unexpected_wiki_root_entries"]` 字段才会出现在报告中。Task 2 的 Step 1 测试在 Task 6 完成后才能通过。

- [ ] **Step 4: 运行纯函数测试确认通过**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_check_unexpected_wiki_root_entries_finds_manual_page tests/skills/test_health_checks.py::test_check_unexpected_wiki_root_entries_empty_when_all_standard -v
```
Expected: PASS (2 tests)

注意：report 级集成测试（`test_health_reports_unexpected_wiki_root_entries`）将在 Task 6 `build_report` 接入后提交。

- [ ] **Step 5: Commit**

```bash
git add skills/wiki-health/scripts/health.py tests/skills/test_health_checks.py
git commit -m "feat(wiki-health): add check_unexpected_wiki_root_entries"
```

---

## Task 3: Raw source candidate scanning + check

**Files:**
- Modify: `skills/wiki-health/scripts/health.py`
- Test: `tests/skills/test_health_checks.py`

- [ ] **Step 1: 写失败测试 — bundle 不递归误报 + hash 后缀匹配 + 缺失 source**

在测试文件末尾追加：

```python
def test_raw_source_check_only_scans_raw_top_level_children() -> None:
  kb_root = "viking://resources/my-kb/"
  raw_bundle_dir = f"{kb_root}raw/readme.md/"
  raw_nested_dir = f"{raw_bundle_dir}llm-wiki-openviking_用户使用版/"
  raw_fragment = f"{raw_nested_dir}六常用自然语言示例.md"
  source_page = f"{kb_root}wiki/sources/readme.md/readme.md"
  client = FakeClient(
    texts={
      source_page: "# README\n\n正文内容足够长用于通过判断。\n",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      f"{kb_root}wiki/index.md": {"isDir": False},
      f"{kb_root}wiki/overview.md": {"isDir": False},
      f"{kb_root}wiki/log.md": {"isDir": False},
      f"{kb_root}wiki/sources/readme.md": {"isDir": True},
      source_page: {"isDir": False},
      raw_bundle_dir.rstrip("/"): {"isDir": True},
      raw_nested_dir.rstrip("/"): {"isDir": True},
      raw_fragment: {"isDir": False},
    },
    listings={
      (f"{kb_root}raw/", False): [
        {"uri": f"{kb_root}raw/readme.md", "isDir": True},
      ],
      (f"{kb_root}wiki/sources/", True): [
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": f"{kb_root}wiki/index.md", "isDir": False},
        {"uri": f"{kb_root}wiki/overview.md", "isDir": False},
        {"uri": f"{kb_root}wiki/log.md", "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
    },
  )

  result = module.check_raw_sources_without_source_pages(client, kb_root)
  assert result == []


def test_raw_hash_suffix_candidate_matches_existing_source_page() -> None:
  kb_root = "viking://resources/my-kb/"
  raw_uri = f"{kb_root}raw/README__5e5947c8ee9740d68e3f926e2877dcf9"
  source_page = f"{kb_root}wiki/sources/readme.md/readme.md"
  client = FakeClient(
    texts={source_page: "# README\n\n正文\n"},
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      f"{kb_root}wiki/index.md": {"isDir": False},
      f"{kb_root}wiki/overview.md": {"isDir": False},
      f"{kb_root}wiki/log.md": {"isDir": False},
      f"{kb_root}wiki/sources/readme.md": {"isDir": True},
      source_page: {"isDir": False},
      raw_uri: {"isDir": True},
    },
    listings={
      (f"{kb_root}raw/", False): [
        {"uri": raw_uri, "isDir": True},
      ],
      (f"{kb_root}wiki/sources/", True): [
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": f"{kb_root}wiki/index.md", "isDir": False},
        {"uri": f"{kb_root}wiki/overview.md", "isDir": False},
        {"uri": f"{kb_root}wiki/log.md", "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
    },
  )

  candidates = module.candidate_source_slugs_from_raw_child_uri(raw_uri)
  assert "readme-5e5947c8ee9740d68e3f926e2877dcf9" in candidates
  assert "readme" in candidates

  result = module.check_raw_sources_without_source_pages(client, kb_root)
  assert result == []
```

注意：`test_health_reports_raw_source_candidate_without_source_page`（report 级测试）移至 Task 6 一并提交。

- [ ] **Step 2: 运行测试确认失败**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_raw_source_check_only_scans_raw_top_level_children tests/skills/test_health_checks.py::test_raw_hash_suffix_candidate_matches_existing_source_page -v
```
Expected: FAIL — `AttributeError: module has no attribute 'check_raw_sources_without_source_pages'`

- [ ] **Step 3: 实现 list_raw_source_candidates + check_raw_sources_without_source_pages**

在 health.py 的 `check_unexpected_wiki_root_entries` 之后，添加：

```python
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
```

- [ ] **Step 4: 运行纯函数测试确认通过（report 测试在 Task 6 后通过）**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_raw_source_check_only_scans_raw_top_level_children tests/skills/test_health_checks.py::test_raw_hash_suffix_candidate_matches_existing_source_page -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/wiki-health/scripts/health.py tests/skills/test_health_checks.py
git commit -m "feat(wiki-health): add raw source candidate scanning (non-recursive, hash-aware)"
```

---

## Task 4: Log coverage generalization

**Files:**
- Modify: `skills/wiki-health/scripts/health.py`
- Test: `tests/skills/test_health_checks.py`

- [ ] **Step 1: 写失败测试 — synthesis log coverage**

在测试文件末尾追加：

```python
def test_synthesis_log_missing_is_reported() -> None:
  kb_root = "viking://resources/my-kb/"
  synthesis_page = f"{kb_root}wiki/syntheses/answer.md/answer.md"
  client = FakeClient(
    texts={
      f"{kb_root}wiki/log.md": "# 操作日志\n\n无关内容\n",
      synthesis_page: "# Answer\n\n正文\n",
    },
    stats={
      f"{kb_root}wiki/log.md": {"isDir": False},
      f"{kb_root}wiki/syntheses/answer.md": {"isDir": True},
      synthesis_page: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/syntheses/", True): [
        {"uri": synthesis_page, "isDir": False},
      ],
    },
  )

  missing = module.check_synthesis_log_coverage(client, kb_root)

  assert missing == [f"{kb_root}wiki/syntheses/answer.md"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_synthesis_log_missing_is_reported -v
```
Expected: FAIL — `AttributeError: module has no attribute 'check_synthesis_log_coverage'`

- [ ] **Step 3: 实现泛化 log coverage**

3a. 在 `source_log_match_tokens` 函数之前，添加通用函数：

```python
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
```

3b. 将现有 `source_log_match_tokens` 改为 wrapper：

```python
def source_log_match_tokens(client: OVFSClient, kbRoot: str, rel_path: str) -> set[str]:
  return page_log_match_tokens(client, kbRoot, rel_path)
```

3c. 将现有 `log_contains_source_token` 改为 wrapper：

```python
def log_contains_source_token(logText: str, token: str) -> bool:
  return log_contains_page_token(logText, token)
```

3d. 在现有 `check_source_log_coverage` 之前，添加通用 coverage 函数：

```python
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
```

3e. 将现有 `check_source_log_coverage` 改为 wrapper：

```python
def check_source_log_coverage(client: OVFSClient, kbRoot: str) -> list[str]:
  return check_page_log_coverage(client, kbRoot, "sources")
```

3f. 在 `check_source_log_coverage` 之后添加 synthesis 覆盖函数：

```python
def check_synthesis_log_coverage(client: OVFSClient, kbRoot: str) -> list[str]:
  return check_page_log_coverage(client, kbRoot, "syntheses")
```

- [ ] **Step 4: 运行新测试 + 现有 log coverage 测试确认通过**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_synthesis_log_missing_is_reported tests/skills/test_health_checks.py::test_source_log_title_match_does_not_false_positive tests/skills/test_health_checks.py::test_source_log_slug_missing_still_warns tests/skills/test_health_checks.py::test_source_log_short_slug_does_not_match_unrelated_word -v
```
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/wiki-health/scripts/health.py tests/skills/test_health_checks.py
git commit -m "feat(wiki-health): generalize log coverage to support synthesis pages"
```

---

## Task 5: build_repair_recommendations

**Files:**
- Modify: `skills/wiki-health/scripts/health.py`

- [ ] **Step 1: 实现 build_repair_recommendations**

在 `check_nested_resource_dirs` 函数之后（或 `check_unexpected_wiki_root_entries` 之后），添加：

```python
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
```

- [ ] **Step 2: 运行全部现有测试确认无回归**

```bash
python3 -m pytest tests/skills/test_health_checks.py tests/skills/test_index_rebuild.py -v
```
Expected: PASS，具体测试数量以 pytest 输出为准

- [ ] **Step 3: Commit**

```bash
git add skills/wiki-health/scripts/health.py
git commit -m "feat(wiki-health): add build_repair_recommendations"
```

---

## Task 6: Extend build_report

**Files:**
- Modify: `skills/wiki-health/scripts/health.py`
- Test: `tests/skills/test_health_checks.py`

- [ ] **Step 1: 写失败测试 — report 级集成测试（Task 2/3 deferred + unexpected root entries in report）**

在测试文件末尾追加（这些测试依赖 `build_report` 包含新字段）：

```python
def test_health_reports_unexpected_wiki_root_entries() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  manual_uri = f"{kb_root}wiki/manual.md"
  client = FakeClient(
    texts={
      required_file_uris[0]: "# 索引\n\n## 资料来源\n",
      required_file_uris[1]: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      required_file_uris[2]: "# 操作日志\n\n记录\n",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      **{uri: {"isDir": False} for uri in required_file_uris},
      manual_uri: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/", False): [
        {"uri": uri, "isDir": False} for uri in required_file_uris
      ] + [
        {"uri": manual_uri, "isDir": False},
        {"uri": f"{kb_root}wiki/sources", "isDir": True},
        {"uri": f"{kb_root}wiki/entities", "isDir": True},
        {"uri": f"{kb_root}wiki/concepts", "isDir": True},
        {"uri": f"{kb_root}wiki/syntheses", "isDir": True},
      ],
      (f"{kb_root}wiki/sources/", True): [],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}raw/", False): [],
    },
  )

  report = build_report(client, kb_root)

  assert manual_uri in report["details"]["unexpected_wiki_root_entries"]
  assert any("不符合 schema" in w for w in report["warnings"])


def test_health_reports_raw_source_candidate_without_source_page() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  raw_uri = f"{kb_root}raw/new-note.md"
  client = FakeClient(
    texts={
      required_file_uris[0]: "# 索引\n\n## 资料来源\n",
      required_file_uris[1]: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      required_file_uris[2]: "# 操作日志\n\n记录\n",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      **{uri: {"isDir": False} for uri in required_file_uris},
      raw_uri: {"isDir": False},
    },
    listings={
      (f"{kb_root}raw/", False): [
        {"uri": raw_uri, "isDir": False},
      ],
      (f"{kb_root}wiki/sources/", True): [],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": uri, "isDir": False} for uri in required_file_uris
      ],
    },
  )

  report = build_report(client, kb_root)

  raw_pending = report["details"]["raw_sources_without_source_pages"]
  assert len(raw_pending) == 1
  assert raw_pending[0]["raw_uri"] == raw_uri
  assert any("尚未 ingest" in w for w in report["warnings"])
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_health_reports_unexpected_wiki_root_entries tests/skills/test_health_checks.py::test_health_reports_raw_source_candidate_without_source_page -v
```
Expected: FAIL — `KeyError: 'unexpected_wiki_root_entries'`（因为 build_report 还没加这些字段）

- [ ] **Step 3: 修改 build_report 函数**

在 `build_report` 函数体中，在 `nestedDirs = check_nested_resource_dirs(client, kbRoot)` 之后，添加新的检查调用：

```python
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
```

在 warnings 区域，现有 `missingSourceLogEntries` warning 之后，添加：

```python
  if unexpectedWikiRootEntries:
    warnings.append(f"wiki/ 根目录存在不符合 schema 的条目：{len(unexpectedWikiRootEntries)}")

  if rawSourcesWithoutSourcePages:
    warnings.append(f"raw/ 下存在尚未 ingest 的 source candidate：{len(rawSourcesWithoutSourcePages)}")

  if missingSynthesisLogEntries:
    warnings.append(f"综合结论页面未记录到 wiki/log.md：{len(missingSynthesisLogEntries)}")
```

在 summary 字典中，现有字段之后，添加：

```python
      "missing_source_log_entries": len(missingSourceLogEntries),
      "missing_synthesis_log_entries": len(missingSynthesisLogEntries),
      "unexpected_wiki_root_entries": len(unexpectedWikiRootEntries),
      "raw_source_candidates": len(rawSourceCandidates),
      "raw_sources_without_source_pages": len(rawSourcesWithoutSourcePages),
      "nested_resource_dirs": len(nestedDirs),
      "repairable_issues": sum(1 for item in repairRecommendations if item["safe_to_auto_repair"]),
```

在 details 字典中，现有字段之后，添加：

```python
      "unexpected_wiki_root_entries": unexpectedWikiRootEntries,
      "raw_source_candidates": rawSourceCandidates,
      "raw_sources_without_source_pages": rawSourcesWithoutSourcePages,
      "missing_synthesis_log_entries": missingSynthesisLogEntries,
      "repair_recommendations": repairRecommendations,
```

- [ ] **Step 4: 运行全部测试**

```bash
python3 -m pytest tests/skills/test_health_checks.py tests/skills/test_index_rebuild.py -v
```
Expected: PASS — 包括 Task 2 和 Task 3 中之前无法通过的 report 级测试现在全部通过

- [ ] **Step 5: Commit**

```bash
git add skills/wiki-health/scripts/health.py tests/skills/test_health_checks.py
git commit -m "feat(wiki-health): extend build_report with new checks and repair recommendations"
```

---

## Task 7: repair-structure

**Files:**
- Modify: `skills/wiki-health/scripts/health.py`
- Test: `tests/skills/test_health_checks.py`

- [ ] **Step 1: 写失败测试 — 文件冲突检测 + 不覆盖已有页面但创建缺失页面（纯函数）**

在测试文件末尾追加：

```python
def test_repair_structure_reports_file_conflict_for_required_dir() -> None:
  kb_root = "viking://resources/my-kb/"
  graph_uri = f"{kb_root}graph/"  # 必要目录，但被同名文件占用
  required_file_uris = required_wiki_pages(kb_root)
  mkdir_calls: list[str] = []

  class ConflictClient(FakeClient):
    def mkdir(self, uri: str, description: str | None = None) -> None:
      mkdir_calls.append(uri)
      self.stats[uri] = {"isDir": True}

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  client = ConflictClient(
    texts={
      required_file_uris[0]: "# 索引\n\n## 资料来源\n",
      required_file_uris[1]: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      required_file_uris[2]: "# 操作日志\n\n记录\n",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs if rel != "graph/"},
      # graph/ 被同名文件占用，不是目录（key 必须带尾斜杠以匹配 repair_structure 生成的 uri）
      graph_uri: {"isDir": False},
      **{uri: {"isDir": False} for uri in required_file_uris},
    },
    listings={},
  )

  result = module.repair_structure(client, kb_root)

  assert graph_uri in result["skipped_conflicts"]
  assert graph_uri not in mkdir_calls
  assert result["structure_repaired"] is True


def test_repair_structure_does_not_overwrite_existing_page_but_creates_missing() -> None:
  kb_root = "viking://resources/my-kb/"
  overview_uri = f"{kb_root}wiki/overview.md"
  log_uri = f"{kb_root}wiki/log.md"
  index_uri = f"{kb_root}wiki/index.md"
  writes: list[dict[str, object]] = []

  class StructureClient(FakeClient):
    def mkdir(self, uri: str, description: str | None = None) -> None:
      self.stats[uri] = {"isDir": True}

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      writes.append({"uri": uri, "text": text, "create": create, "wait": wait})
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  client = StructureClient(
    texts={
      index_uri: "# 索引\n\n## 资料来源\n",
      overview_uri: "# 概览\n\n这是人工编写的非空概览内容，不应被覆盖。",
      # log.md 不在 texts 中——缺失
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      index_uri: {"isDir": False},
      overview_uri: {"isDir": False},
      # log.md 不在 stats 中——缺失
    },
    listings={},
  )

  result = module.repair_structure(client, kb_root)

  # log.md 被创建
  written_uris = [w["uri"] for w in writes]
  assert log_uri in written_uris or any(log_uri in str(w["uri"]) for w in writes)
  # overview.md 没被覆盖
  assert overview_uri not in written_uris
  assert "这是人工编写的非空概览内容" in client.texts[overview_uri]
```

注意：以上两个测试直接调用 `module.repair_structure(client, kb_root)`，不经过 `main()`。`--repair-structure` 参数的 main 级集成测试放在 Task 10。

- [ ] **Step 2: 运行测试确认失败**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_repair_structure_reports_file_conflict_for_required_dir tests/skills/test_health_checks.py::test_repair_structure_does_not_overwrite_existing_page_but_creates_missing -v
```
Expected: FAIL — `AttributeError: module has no attribute 'repair_structure'`

- [ ] **Step 3: 实现 build_initial_key_page_content + repair_structure**

在 health.py 的 `build_repair_recommendations` 之后，添加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_repair_structure_reports_file_conflict_for_required_dir tests/skills/test_health_checks.py::test_repair_structure_does_not_overwrite_existing_page_but_creates_missing -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/wiki-health/scripts/health.py tests/skills/test_health_checks.py
git commit -m "feat(wiki-health): add repair_structure with conflict detection"
```

---

## Task 8: repair-index refactor

**Files:**
- Modify: `skills/wiki-health/scripts/health.py`

- [ ] **Step 1: 实现 repair_index 函数（从 main 中抽取）**

在 `repair_structure` 之后，添加：

```python
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
```

- [ ] **Step 2: 运行现有测试确认无回归**

```bash
python3 -m pytest tests/skills/test_health_checks.py tests/skills/test_index_rebuild.py -v
```
Expected: PASS（repair_index 已定义但尚未被 main 调用，现有测试不受影响）

- [ ] **Step 3: Commit**

```bash
git add skills/wiki-health/scripts/health.py
git commit -m "refactor(wiki-health): extract repair_index function"
```

---

## Task 9: repair-log（方案 A）

**Files:**
- Modify: `skills/wiki-health/scripts/health.py`
- Test: `tests/skills/test_health_checks.py`

- [ ] **Step 1: 写失败测试 — bundle log.md + log.md 缺失先创建（纯函数）**

在测试文件末尾追加：

```python
def test_repair_log_writes_to_resolved_log_bundle_child() -> None:
  kb_root = "viking://resources/my-kb/"
  log_dir = f"{kb_root}wiki/log.md"
  log_child = f"{log_dir}/log.md"
  source_page = f"{kb_root}wiki/sources/a.md/a.md"
  required_file_uris = required_wiki_pages(kb_root)
  writes: list[dict[str, object]] = []

  class LogRepairClient(FakeClient):
    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      writes.append({"uri": uri, "text": text, "create": create, "wait": wait})
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  client = LogRepairClient(
    texts={
      required_file_uris[0]: "# 索引\n\n## 资料来源\n- [[sources/a.md]] - A\n",
      required_file_uris[1]: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      log_child: "# 操作日志\n\n无关内容\n",
      source_page: "# A\n\n这是来源 A 的正文内容，长度足够通过页面有效性判断。",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      **{uri: {"isDir": False} for uri in required_file_uris if uri != f"{kb_root}wiki/log.md"},
      log_dir: {"isDir": True},
      log_child: {"isDir": False},
      f"{kb_root}wiki/sources/a.md": {"isDir": True},
      source_page: {"isDir": False},
    },
    listings={
      (f"{log_dir}/", False): [{"uri": log_child, "isDir": False}],
      (f"{kb_root}wiki/sources/", True): [{"uri": source_page, "isDir": False}],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": required_file_uris[0], "isDir": False},
        {"uri": required_file_uris[1], "isDir": False},
        {"uri": log_child, "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/", False): [
        {"uri": required_file_uris[0], "isDir": False},
        {"uri": required_file_uris[1], "isDir": False},
        {"uri": log_dir, "isDir": True},
      ],
      (f"{kb_root}raw/", False): [],
    },
  )

  result = module.repair_log(client, kb_root)

  assert result["type"] == "repair_log"
  assert result["log_repaired"] is True
  log_writes = [w for w in writes if "health-reconcile" in str(w["text"])]
  assert len(log_writes) >= 1
  assert log_writes[0]["uri"] == log_child
  assert "health-reconcile" in log_writes[0]["text"]
  assert "已补录 source 页面" in log_writes[0]["text"]
  assert "wiki/sources/a.md" in log_writes[0]["text"]


def test_repair_log_creates_missing_log_then_appends() -> None:
  kb_root = "viking://resources/my-kb/"
  source_page = f"{kb_root}wiki/sources/a.md/a.md"
  index_uri = f"{kb_root}wiki/index.md"
  overview_uri = f"{kb_root}wiki/overview.md"
  log_uri = f"{kb_root}wiki/log.md"
  writes: list[dict[str, object]] = []

  class LogCreateClient(FakeClient):
    def mkdir(self, uri: str, description: str | None = None) -> None:
      self.stats[uri] = {"isDir": True}

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      writes.append({"uri": uri, "text": text, "create": create, "wait": wait})
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  client = LogCreateClient(
    texts={
      index_uri: "# 索引\n\n## 资料来源\n- [[sources/a.md]] - A\n",
      overview_uri: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      source_page: "# A\n\n这是来源 A 的正文内容，长度足够通过页面有效性判断。",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      index_uri: {"isDir": False},
      overview_uri: {"isDir": False},
      f"{kb_root}wiki/sources/a.md": {"isDir": True},
      source_page: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/sources/", True): [{"uri": source_page, "isDir": False}],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": index_uri, "isDir": False},
        {"uri": overview_uri, "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/", False): [
        {"uri": index_uri, "isDir": False},
        {"uri": overview_uri, "isDir": False},
      ],
      (f"{kb_root}raw/", False): [],
    },
  )

  result = module.repair_log(client, kb_root)

  assert result["type"] == "repair_log"
  assert result["created_initial_log"] is True
  assert result["log_repaired"] is True

  # 验证先创建初始 log，再追加 health-reconcile 补录行
  assert any(w["text"] == "# 操作日志\n\n" for w in writes)
  health_writes = [w for w in writes if "health-reconcile" in str(w["text"])]
  assert len(health_writes) >= 1
  assert "# 操作日志" in str(health_writes[0]["text"])
  assert "health-reconcile" in str(health_writes[0]["text"])
```

注意：以上测试直接调用 `module.repair_log(client, kb_root)`，不经过 `main()`。`--repair-log` 参数的 main 级集成测试放在 Task 10。

- [ ] **Step 2: 运行测试确认失败**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_repair_log_writes_to_resolved_log_bundle_child tests/skills/test_health_checks.py::test_repair_log_creates_missing_log_then_appends -v
```
Expected: FAIL — `AttributeError: module has no attribute 'repair_log'`

- [ ] **Step 3: 实现 repair_log（方案 A：先创建 log 再 coverage）**

在 `repair_index` 之后，添加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python3 -m pytest tests/skills/test_health_checks.py::test_repair_log_writes_to_resolved_log_bundle_child tests/skills/test_health_checks.py::test_repair_log_creates_missing_log_then_appends -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/wiki-health/scripts/health.py tests/skills/test_health_checks.py
git commit -m "feat(wiki-health): add repair_log with 方案 A (create missing log first)"
```

---

## Task 10: parse_args + main() repair flow + update existing tests

**Files:**
- Modify: `skills/wiki-health/scripts/health.py`（parse_args + main）
- Modify: `tests/skills/test_health_checks.py`（更新旧测试断言 + 新增 repair-all 顺序测试）

- [ ] **Step 1: 更新两个旧 repair-index 测试断言**

1a. 在 `test_main_repair_index_only_writes_index_once` 中，将：

```python
  assert report["repair"]["index_rebuilt"] is True
  assert report["repair"]["index_uri"] == index_uri
  assert report["repair"]["index_write_uri"] == index_write_uri
  assert writes == [{
    "uri": index_write_uri,
    "text": writes[0]["text"],
    "create": False,
    "wait": True,
  }]
  assert json.loads(json.dumps(report))["repair"]["index_write_uri"] == index_write_uri
```

替换为：

```python
  actions = report["repair"]["actions"]
  assert len(actions) == 1
  action = actions[0]
  assert action["type"] == "repair_index"
  assert action["index_rebuilt"] is True
  assert action["index_uri"] == index_uri
  assert action["index_write_uri"] == index_write_uri
  assert writes == [{
    "uri": index_write_uri,
    "text": writes[0]["text"],
    "create": False,
    "wait": True,
  }]
  assert json.loads(json.dumps(report))["repair"]["actions"][0]["index_write_uri"] == index_write_uri
```

1b. 在 `test_main_repair_index_keeps_nested_source_bundle_link_without_broken_target` 中，将：

```python
  assert report["repair"]["index_rebuilt"] is True
```

替换为：

```python
  actions = report["repair"]["actions"]
  assert len(actions) == 1
  assert actions[0]["type"] == "repair_index"
  assert actions[0]["index_rebuilt"] is True
```

- [ ] **Step 2: 写 main 级集成测试 — repair-structure + repair-log + repair-all 顺序**

在测试文件末尾追加：

```python
def test_main_repair_structure_creates_missing_dir(monkeypatch: pytest.MonkeyPatch) -> None:
  kb_root = "viking://resources/my-kb/"
  index_uri = f"{kb_root}wiki/index.md"
  overview_uri = f"{kb_root}wiki/overview.md"
  log_uri = f"{kb_root}wiki/log.md"
  source_page = f"{kb_root}wiki/sources/a.md/a.md"
  calls: list[str] = []
  printed: list[dict[str, object]] = []

  class StructureMainClient(FakeClient):
    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc, tb):
      return False

    def mkdir(self, uri: str, description: str | None = None) -> None:
      calls.append(f"mkdir:{uri}")
      self.stats[uri] = {"isDir": True}

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      calls.append(f"write:{uri}")
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  client = StructureMainClient(
    texts={
      index_uri: "# 索引\n\n## 资料来源\n- [[sources/a.md]] - A\n",
      overview_uri: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      log_uri: "# 操作日志\n\n记录\n",
      source_page: "# A\n\n这是来源 A 的正文内容，长度足够通过页面有效性判断。",
    },
    stats={
      # graph/ 缺失——repair_structure 应创建它
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs if rel != "graph/"},
      index_uri: {"isDir": False},
      overview_uri: {"isDir": False},
      log_uri: {"isDir": False},
      f"{kb_root}wiki/sources/a.md": {"isDir": True},
      source_page: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/sources/", True): [{"uri": source_page, "isDir": False}],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": index_uri, "isDir": False},
        {"uri": overview_uri, "isDir": False},
        {"uri": log_uri, "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/", False): [
        {"uri": index_uri, "isDir": False},
        {"uri": overview_uri, "isDir": False},
        {"uri": log_uri, "isDir": False},
        {"uri": f"{kb_root}wiki/sources", "isDir": True},
        {"uri": f"{kb_root}wiki/entities", "isDir": True},
        {"uri": f"{kb_root}wiki/concepts", "isDir": True},
        {"uri": f"{kb_root}wiki/syntheses", "isDir": True},
      ],
      (f"{kb_root}raw/", False): [],
    },
  )

  monkeypatch.setattr(module.OVFSConfig, "load", staticmethod(lambda config_path=None, profile=None: object()))
  monkeypatch.setattr(module, "OVFSClient", lambda config: client)
  monkeypatch.setattr(module, "build_kb_root", lambda kb_name: kb_root)
  monkeypatch.setattr(module, "print_json", lambda data, pretty=False: printed.append(data))
  monkeypatch.setattr(module.sys, "argv", ["health.py", "--kb-name", "my-kb", "--repair-structure"])

  exit_code = module.main()

  assert exit_code in (0, 1)
  report = printed[0]
  assert "repair" in report
  structure_action = [a for a in report["repair"]["actions"] if a["type"] == "repair_structure"][0]
  assert f"{kb_root}graph/" in structure_action["created_dirs"]
  assert any(f"mkdir:{kb_root}graph/" in c for c in calls)


def test_main_repair_log_appends_health_reconcile(monkeypatch: pytest.MonkeyPatch) -> None:
  kb_root = "viking://resources/my-kb/"
  log_child = f"{kb_root}wiki/log.md/log.md"
  source_page = f"{kb_root}wiki/sources/a.md/a.md"
  index_child = f"{kb_root}wiki/index.md/index.md"
  overview_child = f"{kb_root}wiki/overview.md/overview.md"
  writes: list[dict[str, object]] = []
  printed: list[dict[str, object]] = []

  class LogMainClient(FakeClient):
    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc, tb):
      return False

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      writes.append({"uri": uri, "text": text, "create": create, "wait": wait})
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  client = LogMainClient(
    texts={
      index_child: "# 索引\n\n## 资料来源\n- [[sources/a.md]] - A\n",
      overview_child: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      log_child: "# 操作日志\n\n无关内容\n",
      source_page: "# A\n\n这是来源 A 的正文内容，长度足够通过页面有效性判断。",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      f"{kb_root}wiki/index.md": {"isDir": True},
      f"{kb_root}wiki/overview.md": {"isDir": True},
      f"{kb_root}wiki/log.md": {"isDir": True},
      index_child: {"isDir": False},
      overview_child: {"isDir": False},
      log_child: {"isDir": False},
      f"{kb_root}wiki/sources/a.md": {"isDir": True},
      source_page: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/index.md/", False): [{"uri": index_child, "isDir": False}],
      (f"{kb_root}wiki/overview.md/", False): [{"uri": overview_child, "isDir": False}],
      (f"{kb_root}wiki/log.md/", False): [{"uri": log_child, "isDir": False}],
      (f"{kb_root}wiki/sources/", True): [{"uri": source_page, "isDir": False}],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": index_child, "isDir": False},
        {"uri": overview_child, "isDir": False},
        {"uri": log_child, "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/", False): [
        {"uri": f"{kb_root}wiki/index.md", "isDir": True},
        {"uri": f"{kb_root}wiki/overview.md", "isDir": True},
        {"uri": f"{kb_root}wiki/log.md", "isDir": True},
        {"uri": f"{kb_root}wiki/sources", "isDir": True},
        {"uri": f"{kb_root}wiki/entities", "isDir": True},
        {"uri": f"{kb_root}wiki/concepts", "isDir": True},
        {"uri": f"{kb_root}wiki/syntheses", "isDir": True},
      ],
      (f"{kb_root}raw/", False): [],
    },
  )

  monkeypatch.setattr(module.OVFSConfig, "load", staticmethod(lambda config_path=None, profile=None: object()))
  monkeypatch.setattr(module, "OVFSClient", lambda config: client)
  monkeypatch.setattr(module, "build_kb_root", lambda kb_name: kb_root)
  monkeypatch.setattr(module, "print_json", lambda data, pretty=False: printed.append(data))
  monkeypatch.setattr(module.sys, "argv", ["health.py", "--kb-name", "my-kb", "--repair-log"])

  exit_code = module.main()

  assert exit_code in (0, 1)
  report = printed[0]
  log_action = [a for a in report["repair"]["actions"] if a["type"] == "repair_log"][0]
  assert log_action["log_repaired"] is True

  log_writes = [w for w in writes if "health-reconcile" in str(w["text"])]
  assert len(log_writes) >= 1
  assert log_writes[0]["uri"] == log_child
  assert "wiki/sources/a.md" in log_writes[0]["text"]


def test_main_repair_all_runs_structure_then_index_then_log(monkeypatch: pytest.MonkeyPatch) -> None:
  kb_root = "viking://resources/my-kb/"
  log_child = f"{kb_root}wiki/log.md/log.md"
  source_page = f"{kb_root}wiki/sources/a.md/a.md"
  index_child = f"{kb_root}wiki/index.md/index.md"
  overview_child = f"{kb_root}wiki/overview.md/overview.md"
  calls: list[str] = []
  printed: list[dict[str, object]] = []

  class AllRepairClient(FakeClient):
    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc, tb):
      return False

    def mkdir(self, uri: str, description: str | None = None) -> None:
      calls.append("mkdir")
      self.stats[uri] = {"isDir": True}

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}
      if uri == index_child:
        calls.append("write_index")
      elif uri == log_child or "log.md" in uri:
        calls.append("write_log")
      else:
        calls.append("write_other")

  client = AllRepairClient(
    texts={
      index_child: "# 索引\n\n## 资料来源\n- [[sources/a.md]] - A\n",
      overview_child: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      log_child: "# 操作日志\n\n无关内容\n",
      source_page: "# A\n\n这是来源 A 的正文内容，长度足够通过页面有效性判断。",
    },
    stats={
      # graph/ 缺失——repair_structure 会触发 mkdir
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs if rel != "graph/"},
      f"{kb_root}wiki/index.md": {"isDir": True},
      f"{kb_root}wiki/overview.md": {"isDir": True},
      f"{kb_root}wiki/log.md": {"isDir": True},
      index_child: {"isDir": False},
      overview_child: {"isDir": False},
      log_child: {"isDir": False},
      f"{kb_root}wiki/sources/a.md": {"isDir": True},
      source_page: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/index.md/", False): [{"uri": index_child, "isDir": False}],
      (f"{kb_root}wiki/overview.md/", False): [{"uri": overview_child, "isDir": False}],
      (f"{kb_root}wiki/log.md/", False): [{"uri": log_child, "isDir": False}],
      (f"{kb_root}wiki/sources/", True): [{"uri": source_page, "isDir": False}],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": index_child, "isDir": False},
        {"uri": overview_child, "isDir": False},
        {"uri": log_child, "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/", False): [
        {"uri": f"{kb_root}wiki/index.md", "isDir": True},
        {"uri": f"{kb_root}wiki/overview.md", "isDir": True},
        {"uri": f"{kb_root}wiki/log.md", "isDir": True},
        {"uri": f"{kb_root}wiki/sources", "isDir": True},
        {"uri": f"{kb_root}wiki/entities", "isDir": True},
        {"uri": f"{kb_root}wiki/concepts", "isDir": True},
        {"uri": f"{kb_root}wiki/syntheses", "isDir": True},
      ],
      (f"{kb_root}raw/", False): [],
    },
  )

  monkeypatch.setattr(module.OVFSConfig, "load", staticmethod(lambda config_path=None, profile=None: object()))
  monkeypatch.setattr(module, "OVFSClient", lambda config: client)
  monkeypatch.setattr(module, "build_kb_root", lambda kb_name: kb_root)
  monkeypatch.setattr(module, "print_json", lambda data, pretty=False: printed.append(data))
  monkeypatch.setattr(module.sys, "argv", ["health.py", "--kb-name", "my-kb", "--repair-all"])

  exit_code = module.main()

  assert exit_code in (0, 1)
  report = printed[0]
  types = [a["type"] for a in report["repair"]["actions"]]
  assert types == ["repair_structure", "repair_index", "repair_log"]

  # 验证真实副作用层面顺序：structure mkdir < index write < log write
  mkdir_idx = calls.index("mkdir")
  write_index_idx = calls.index("write_index")
  write_log_idx = calls.index("write_log")
  assert mkdir_idx < write_index_idx
  assert write_index_idx < write_log_idx
```

- [ ] **Step 3: 实现 parse_args 新增参数**

在 `parse_args` 函数中，在现有 `--repair-index` 之后添加：

```python
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
```

- [ ] **Step 4: 重写 main() 函数**

将整个 `main()` 函数（当前从 `def main() -> int:` 到文件末尾的 `sys.exit(main())`）替换为：

```python
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
```

- [ ] **Step 5: 运行全部测试**

```bash
python3 -m pytest tests/skills/test_health_checks.py tests/skills/test_index_rebuild.py -v
```
Expected: PASS — 所有现有测试（含更新后的 repair-index 测试）+ 所有新测试

- [ ] **Step 6: Commit**

```bash
git add skills/wiki-health/scripts/health.py tests/skills/test_health_checks.py
git commit -m "feat(wiki-health): add repair-structure/log/all args, refactor main flow, update tests"
```

---

## Task 11: SKILL.md + README.md

**Files:**
- Modify: `skills/wiki-health/SKILL.md`
- Modify: `README.md`（可选）

- [ ] **Step 1: 更新 SKILL.md**

将 `skills/wiki-health/SKILL.md` 的全部内容替换为：

```markdown
---
name: wiki-health
description: 当用户要求对 KB 执行 wiki-health（检查远端 wiki 结构完整性）时使用；中文触发描述优先。
---

# Wiki Health

## 触发场景（自然语言）

当用户表达以下意图时使用：

- "对 my-kb 执行 wiki-health"
- "执行 wiki-health"
- "检查结构是否完整"
- "ingest 后再做一次健康检查"
- "检查控制台直接改动造成的知识库漂移"
- "检查 index 和真实页面是否一致"
- "检查 raw 里有没有未 ingest 的资料"
- "帮我安全修复 wiki-health 能修的问题"
- "补录 log，但不要伪造真实操作时间"
- "执行 wiki-health repair-all"

## 职责边界（不要做什么）

- 默认只检查，不写远端
- 用户明确要求时可以执行安全修复（--repair-*）
- 不调用 LLM，不做总结与润色
- 不删除、不移动远端页面
- 不自动 ingest raw
- 不自动生成 overview 语义总结
- `index.md` 可以重建
- `log.md` 只能追加 `health-reconcile` 补录行
- `health-reconcile` 补录不代表原始操作时间
- 如果 `log.md` 缺失，`--repair-log` 会先创建初始 log，再补录已有 source/synthesis 页面
- 不执行 ingest/query/lint/graph

## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

### 基础检查

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" --kb-name <kb-name> --pretty
```

### 重建 index

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --repair-index \
  --pretty
```

### 修复缺失结构

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --repair-structure \
  --pretty
```

### 补录 log

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --repair-log \
  --pretty
```

### 执行全部安全修复

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --repair-all \
  --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

可选参数：`--config <path>`、`--profile <name>`。

## 强约束

- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
```

- [ ] **Step 2: 运行全部测试确认无回归**

```bash
python3 -m pytest tests/skills/test_health_checks.py tests/skills/test_index_rebuild.py -v
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add skills/wiki-health/SKILL.md
git commit -m "docs(wiki-health): update SKILL.md with reconcile/repair capabilities"
```

---

## 最终验证

- [ ] **Step 1: 运行全部 health + index 测试**

```bash
python3 -m pytest tests/skills/test_health_checks.py tests/skills/test_index_rebuild.py -v
```
Expected: ALL PASS

- [ ] **Step 2: 对真实 esf KB 执行 health 检查（只读）**

```bash
bash skills/wiki-health/scripts/run.sh --kb-name esf --pretty
```
Expected: JSON 输出，`status` 为 `ok`，包含 `repair_recommendations`、`raw_source_candidates`、`unexpected_wiki_root_entries` 等新字段，不写远端

- [ ] **Step 3: 确认默认 health 不写远端**

检查 Step 2 的输出中没有 `repair` 字段（因为没有传任何 `--repair-*` 参数）

- [ ] **Step 4: 确认 git 状态干净**

```bash
git status
git log --oneline -12
```
Expected: 所有变更已提交，工作区干净
