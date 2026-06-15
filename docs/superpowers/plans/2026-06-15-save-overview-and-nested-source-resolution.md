# Save Overview And Nested Source Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `wiki-save` 与 legacy `wiki-query --save` 在 `overview.md` 中写入与 ingest 同风格的标题+时间戳 block，并让 shared `wiki_index.py` 正确 resolve 嵌套目录型 source bundle，消除 `wiki-health` 对 `sources/readme.md` 一类页面的持续误报。

**Architecture:** 保持改动最小：overview 写法只调整 `wiki-save` 与 legacy `wiki-query --save` 的 synthesis overview block 生成与 upsert 逻辑，不动 ingest 的 `overview.md` 行为。嵌套 source bundle 问题分两层修复：第一层在四份完全一致的 shared `wiki_index.py` 中修 health / repair / index rebuild 使用的 resolver；第二层在 `skills/wiki-query/scripts/query.py` 中同步修本地 resolver，保证 query index 模式也能读到 nested bundle 正文。

**Tech Stack:** Python 3、OpenViking OVFSClient、pytest、shared `wiki_index.py` helper、正则表达式

---

## File Structure

**Modify:**
- `skills/wiki-save/scripts/save.py`
- `skills/wiki-query/scripts/query.py`
- `skills/wiki-health/scripts/wiki_index.py`
- `skills/wiki-ingest/scripts/wiki_index.py`
- `skills/wiki-query/scripts/wiki_index.py`
- `skills/wiki-save/scripts/wiki_index.py`
- `tests/skills/test_query_retrieval_mode.py`
- `tests/skills/test_save_updates.py`
- `tests/skills/test_query_save_legacy_semantics.py`
- `tests/skills/test_index_rebuild.py`
- `tests/skills/test_health_checks.py`

**Responsibilities:**
- `skills/wiki-save/scripts/save.py`: 生成 synthesis overview block，并把旧 comment block 迁移为标题+时间戳 block。
- `skills/wiki-query/scripts/query.py`: legacy `--save` 复用与 `wiki-save` 一致的 overview block 语义。
- `skills/wiki-query/scripts/query.py`: 同时修本地 canonical resolver，保证 query 检索读取也能命中嵌套 source bundle 的正文。
- `skills/*/scripts/wiki_index.py`: 为 `sources/readme.md/<nested-dir>/*.md` 这种嵌套 bundle 选择可读正文文件，避免扫描得到页面、resolver 却打不开。
- `tests/skills/test_query_retrieval_mode.py`: 锁定 query 通过 index 读取 `[[sources/readme.md]]` 时，能 resolve 到嵌套 bundle 正文。
- `tests/skills/test_save_updates.py`: 锁定 `wiki-save` 新 overview block 格式。
- `tests/skills/test_query_save_legacy_semantics.py`: 锁定 legacy `wiki-query --save` 迁移旧 comment block 到新格式。
- `tests/skills/test_index_rebuild.py`: 锁定 shared helper 对嵌套 source bundle 的 canonical 解析与 write target 选择。
- `tests/skills/test_health_checks.py`: 锁定 `wiki-health` 对嵌套 source bundle 不再误报 broken target。

## Implementation Notes

- 只改 `wiki-save` 与 legacy `wiki-query --save` 的 overview 行为；不要修改 ingest 的 `append_overview_note()` 输出格式。
- 新 overview block 必须使用标题+时间戳形式，不再写 `<!-- synthesis:...:start -->` / `<!-- synthesis:...:end -->` comment block。
- `upsert_overview_synthesis_block()` 必须兼容迁移旧 comment block：同一 synthesis 再次保存时，旧 comment block 要被新 block 替换，而不是双写。
- `wiki-save --overview-note` 不能绕过标题+时间戳 block；它只能作为标题下方正文补充，不能替代标题行。
- shared `wiki_index.py` 四份文件必须继续字节级一致。
- 嵌套 source bundle 的修复使用方案 A：resolver 支持递归寻找正文 md，而不是把这类 bundle 排除出 index。
- 递归寻找正文 md 时，不能把 `.abstract.md` / `.overview.md` / `.relations.json` 当正文，也不能把裸 `abstract.md` 当正文。
- 对 `readme.md/llm-wiki-openviking_用户使用版/{摘要_*.md,相关实体_*.md,关键内容.md}` 这类结构，canonical resolver 应优先返回 `关键内容.md`，避免把摘要或相关实体碎片当正文。
- overview 中重复保存同一 synthesis 时，替换逻辑必须保守，不能吞掉后续手工备注、`##` 标题或其他无关 block。
- 不要修改 `common.py`、`ovfs.py`、README 主流程、`wiki-health` CLI 结构、现有 profile/config 文件。
- 运行 pytest 前，先进入项目实际 venv 或确认当前环境已安装 `openai` 等测试依赖；否则先安装依赖再跑，不要把依赖缺失误判为本次改动失败。

### Task 1: 统一 synthesis overview block 为标题+时间戳格式

**Files:**
- Modify: `skills/wiki-save/scripts/save.py`
- Modify: `skills/wiki-query/scripts/query.py`
- Modify: `tests/skills/test_save_updates.py`
- Modify: `tests/skills/test_query_save_legacy_semantics.py`

- [ ] **Step 1: 先写 `wiki-save` 失败测试，锁定 overview 不再写 comment block**

在 `tests/skills/test_save_updates.py` 的 `test_overview_should_write_synthesis_block()` 里，把 `FakeClient.writeCalls` 改为记录完整写入内容，并补这些断言：

```python
def test_overview_should_write_synthesis_block(monkeypatch, tmp_path: Path, capsys) -> None:
  answerPath = tmp_path / "answer.md"
  answerPath.write_text("答案", encoding="utf-8")

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
      return {"isDir": False}

    def ls(self, uri: str, recursive: bool = False):
      return []

    def read_text(self, uri: str) -> str:
      if uri.endswith("index.md"):
        return "# 索引\n"
      if uri.endswith("overview.md"):
        return "# 概览\n"
      return "# 操作日志\n"

    def write_text(self, uri: str, content: str, create: bool, wait: bool) -> None:
      self.writeCalls.append((uri, content, create, wait))

  fakeClient = FakeClient(None)
  monkeypatch.setattr(
    sys,
    "argv",
    ["save.py", "--kb-name", "kb", "--answer-file", str(answerPath), "--question", "q", "--title", "t"],
  )
  monkeypatch.setattr(module, "OVFSClient", lambda _config: fakeClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())

  code = module.main()
  output = json.loads(capsys.readouterr().out)
  overviewWrite = next(
    content for uri, content, _create, _wait in fakeClient.writeCalls if uri == "viking://resources/kb/wiki/overview.md"
  )

  assert code == 0
  assert output["status"] == "ok"
  assert "<!-- synthesis:" not in overviewWrite
  assert "### t (" in overviewWrite
  assert "- [[syntheses/t.md]] - t" in overviewWrite
```

再补一个 `--overview-note` 场景，锁定自定义说明不会绕过标题：

```python
def test_save_overview_note_keeps_heading_block(monkeypatch, tmp_path: Path, capsys) -> None:
  answerPath = tmp_path / "answer.md"
  answerPath.write_text("答案", encoding="utf-8")

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
      return {"isDir": False}

    def ls(self, uri: str, recursive: bool = False):
      return []

    def read_text(self, uri: str) -> str:
      if uri.endswith("index.md"):
        return "# 索引\n"
      if uri.endswith("overview.md"):
        return "# 概览\n"
      return "# 操作日志\n"

    def write_text(self, uri: str, content: str, create: bool, wait: bool) -> None:
      self.writeCalls.append((uri, content, create, wait))

  fakeClient = FakeClient(None)
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "save.py",
      "--kb-name",
      "kb",
      "--answer-file",
      str(answerPath),
      "--question",
      "q",
      "--title",
      "t",
      "--overview-note",
      "这是自定义概览说明",
    ],
  )
  monkeypatch.setattr(module, "OVFSClient", lambda _config: fakeClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())

  code = module.main()
  output = json.loads(capsys.readouterr().out)
  overviewWrite = next(
    content for uri, content, _create, _wait in fakeClient.writeCalls if uri == "viking://resources/kb/wiki/overview.md"
  )

  assert code == 0
  assert output["status"] == "ok"
  assert "### t (" in overviewWrite
  assert "这是自定义概览说明" in overviewWrite
  assert "- [[syntheses/t.md]] - t" in overviewWrite
  assert "<!-- synthesis:" not in overviewWrite
```

再补一个重复保存同一 slug 的测试，锁定 `--overview-note` 也不会双写 block：

```python
def test_save_overview_note_reuses_existing_block(monkeypatch, tmp_path: Path, capsys) -> None:
  answerPath = tmp_path / "answer.md"
  answerPath.write_text("答案", encoding="utf-8")

  class FakeClient:
    def __init__(self, _config) -> None:
      self.writeCalls: list[tuple[str, str, bool, bool]] = []

    def __enter__(self):
      return self

    def __exit__(self, excType, exc, tb) -> None:
      return None

    def stat(self, uri: str):
      return {"isDir": False}

    def ls(self, uri: str, recursive: bool = False):
      return []

    def read_text(self, uri: str) -> str:
      if uri.endswith("index.md"):
        return "# 索引\n"
      if uri.endswith("overview.md"):
        return "# 概览\n\n### t (2026-06-15T00:00:00Z)\n\n这是旧说明\n\n- [[syntheses/t.md]] - t\n"
      return "# 操作日志\n"

    def write_text(self, uri: str, content: str, create: bool, wait: bool) -> None:
      self.writeCalls.append((uri, content, create, wait))

  fakeClient = FakeClient(None)
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "save.py",
      "--kb-name",
      "kb",
      "--answer-file",
      str(answerPath),
      "--question",
      "q",
      "--title",
      "t",
      "--overview-note",
      "这是新说明",
      "--on-conflict",
      "update",
    ],
  )
  monkeypatch.setattr(module, "OVFSClient", lambda _config: fakeClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())

  code = module.main()
  output = json.loads(capsys.readouterr().out)
  overviewWrite = next(
    content for uri, content, _create, _wait in fakeClient.writeCalls if uri == "viking://resources/kb/wiki/overview.md"
  )

  assert code == 0
  assert output["status"] == "ok"
  assert overviewWrite.count("### t (") == 1
  assert overviewWrite.count("[[syntheses/t.md]]") == 1
  assert "这是新说明" in overviewWrite
```

再补一个 `wiki-save` 旧 comment block 迁移测试，与 legacy `wiki-query --save` 对称：

```python
def test_save_replaces_legacy_comment_block_with_timestamp_heading(monkeypatch, tmp_path: Path, capsys) -> None:
  answerPath = tmp_path / "answer.md"
  answerPath.write_text("答案", encoding="utf-8")

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
      return {"isDir": False}

    def ls(self, uri: str, recursive: bool = False):
      return []

    def read_text(self, uri: str) -> str:
      if uri.endswith("index.md"):
        return "# 索引\n"
      if uri.endswith("overview.md"):
        return "# 概览\n\n<!-- synthesis:syntheses/t.md:start -->\n- [[syntheses/t.md]] - 旧标题\n<!-- synthesis:syntheses/t.md:end -->\n"
      return "# 操作日志\n"

    def write_text(self, uri: str, content: str, create: bool, wait: bool) -> None:
      self.writeCalls.append((uri, content, create, wait))

  fakeClient = FakeClient(None)
  monkeypatch.setattr(
    sys,
    "argv",
    ["save.py", "--kb-name", "kb", "--answer-file", str(answerPath), "--question", "q", "--title", "t"],
  )
  monkeypatch.setattr(module, "OVFSClient", lambda _config: fakeClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())

  code = module.main()
  output = json.loads(capsys.readouterr().out)
  overviewWrite = next(
    content for uri, content, _create, _wait in fakeClient.writeCalls if uri == "viking://resources/kb/wiki/overview.md"
  )

  assert code == 0
  assert output["status"] == "ok"
  assert "<!-- synthesis:" not in overviewWrite
  assert "### t (" in overviewWrite
  assert "- [[syntheses/t.md]] - t" in overviewWrite
```

- [ ] **Step 2: 运行 save 定向测试并确认失败**

Run: `python3 -m pytest tests/skills/test_save_updates.py::test_overview_should_write_synthesis_block -q`
Expected: FAIL，当前 overview 内容仍包含 `<!-- synthesis:` comment block，且没有 `### t (`。

- [ ] **Step 3: 先写 legacy `wiki-query --save` 失败测试，锁定旧 comment block 迁移**

在 `tests/skills/test_query_save_legacy_semantics.py` 的 `test_legacy_save_updates_index_overview_log_and_returns_deprecated_fields()` 里补充 overview 断言：

```python
  writtenOverview = next(content for uri, content, _create in fakeClient.writeCalls if uri == "viking://resources/kb/wiki/overview.md")
  assert "<!-- synthesis:syntheses/标题.md:start -->" not in writtenOverview
  assert "### 新标题 (" in writtenOverview
  assert "- [[syntheses/标题.md]] - 新标题" in writtenOverview
```

再新增一个迁移旧 block 的测试：

```python
def test_legacy_save_replaces_legacy_comment_block_with_timestamp_heading(monkeypatch, capsys) -> None:
  class FakeClient(FakeOVFSClient):
    def read_text(self, uri: str) -> str:
      if uri.endswith("wiki/overview.md"):
        return "# 概览\n\n<!-- synthesis:syntheses/标题.md:start -->\n- [[syntheses/标题.md]] - 旧标题\n<!-- synthesis:syntheses/标题.md:end -->\n"
      return super().read_text(uri)

  fakeClient = FakeClient(None)
  monkeypatch.setattr(sys, "argv", ["query.py", "--kb-name", "kb", "--question", "q", "--save", "--slug", "标题"])
  monkeypatch.setattr(queryModule, "OVFSClient", lambda _config: fakeClient)
  monkeypatch.setattr(queryModule.OVFSConfig, "load", lambda config_path=None, profile=None: object())
  monkeypatch.setattr(queryModule, "read_local_schema", lambda: "schema")
  monkeypatch.setattr(queryModule, "select_relevant_pages", lambda client, kb_root, question, top_k: [{"uri": "u1", "content": "c", "score": "1"}])
  monkeypatch.setattr(
    queryModule,
    "call_llm",
    lambda prompt, *, api_key, base_url, model: {"answer_markdown": "当前答案", "used_pages": ["u1"], "synthesis_title": "新标题"},
  )
  monkeypatch.setattr(queryModule, "resolve_openai_settings", lambda args: {"api_key": "k", "base_url": None, "model": "m"})
  monkeypatch.setattr(queryModule, "write_temp_json_file", lambda data, pretty: Path("/tmp/payload.json"))

  code = queryModule.main()
  output = json.loads(capsys.readouterr().out)
  writtenOverview = next(content for uri, content, _create in fakeClient.writeCalls if uri == "viking://resources/kb/wiki/overview.md")

  assert code == 0
  assert output["overview_updated"] is True
  assert "<!-- synthesis:syntheses/标题.md:start -->" not in writtenOverview
  assert "### 新标题 (" in writtenOverview
  assert "- [[syntheses/标题.md]] - 新标题" in writtenOverview
```

再补一个重复保存保留手工备注的测试：

```python
def test_legacy_save_replaces_heading_block_without_swallowing_manual_note(monkeypatch, capsys) -> None:
  class FakeClient(FakeOVFSClient):
    def read_text(self, uri: str) -> str:
      if uri.endswith("wiki/overview.md"):
        return "# 概览\n\n### 旧标题 (2026-06-15T00:00:00Z)\n\n- [[syntheses/标题.md]] - 旧标题\n\n手工备注\n"
      return super().read_text(uri)

  fakeClient = FakeClient(None)
  monkeypatch.setattr(sys, "argv", ["query.py", "--kb-name", "kb", "--question", "q", "--save", "--slug", "标题"])
  monkeypatch.setattr(queryModule, "OVFSClient", lambda _config: fakeClient)
  monkeypatch.setattr(queryModule.OVFSConfig, "load", lambda config_path=None, profile=None: object())
  monkeypatch.setattr(queryModule, "read_local_schema", lambda: "schema")
  monkeypatch.setattr(queryModule, "select_relevant_pages", lambda client, kb_root, question, top_k: [{"uri": "u1", "content": "c", "score": "1"}])
  monkeypatch.setattr(
    queryModule,
    "call_llm",
    lambda prompt, *, api_key, base_url, model: {"answer_markdown": "当前答案", "used_pages": ["u1"], "synthesis_title": "新标题"},
  )
  monkeypatch.setattr(queryModule, "resolve_openai_settings", lambda args: {"api_key": "k", "base_url": None, "model": "m"})
  monkeypatch.setattr(queryModule, "write_temp_json_file", lambda data, pretty: Path("/tmp/payload.json"))

  code = queryModule.main()
  output = json.loads(capsys.readouterr().out)
  writtenOverview = next(content for uri, content, _create in fakeClient.writeCalls if uri == "viking://resources/kb/wiki/overview.md")

  assert code == 0
  assert output["overview_updated"] is True
  assert "### 新标题 (" in writtenOverview
  assert "- [[syntheses/标题.md]] - 新标题" in writtenOverview
  assert "手工备注" in writtenOverview
```

同时修改现有 `test_query_and_save_helper_outputs_are_consistent()`，固定时间函数，避免改完 `build_overview_note()` 后时间戳不一致导致 `assert queryNote == saveNote` 失败：

```python
def test_query_and_save_helper_outputs_are_consistent(monkeypatch) -> None:
  monkeypatch.setattr(queryModule, "now_iso", lambda: "2026-06-15T00:00:00Z")
  monkeypatch.setattr(saveModule, "nowIso", lambda: "2026-06-15T00:00:00Z")

  indexText = "# 索引\n\n## 综合结论\n- [[syntheses/existing.md]] - 旧标题\n"
  linkPath = "syntheses/existing.md"
  title = "新标题"
  question = "问题示例"
  answerMarkdown = "回答示例"
  usedPages = ["viking://resources/demo/wiki/sources/a.md"]

  queryIndex = queryModule.upsert_index_link_bullet(indexText, "syntheses", linkPath, title)
  saveIndex = saveModule.upsert_index_link_bullet(indexText, "## 综合结论", linkPath, title)
  assert queryIndex == saveIndex

  queryMarkdown = queryModule.render_synthesis_markdown(title, question, answerMarkdown, usedPages)
  saveMarkdown = saveModule.render_synthesis_markdown(title, question, answerMarkdown, usedPages)
  assert queryMarkdown == saveMarkdown

  queryNote = queryModule.build_overview_note(linkPath, title)
  saveNote = saveModule.build_overview_note(linkPath, title)
  assert queryNote == saveNote

  overviewText = "# 概览\n"
  queryOverview = queryModule.upsert_overview_synthesis_block(overviewText, linkPath, queryNote)
  saveOverview = saveModule.upsert_overview_synthesis_block(overviewText, linkPath, saveNote)
  assert queryOverview == saveOverview
```

- [ ] **Step 4: 运行 legacy save 定向测试并确认失败**

Run: `python3 -m pytest tests/skills/test_query_save_legacy_semantics.py::test_legacy_save_replaces_legacy_comment_block_with_timestamp_heading -q`
Expected: FAIL，当前 overview 仍保留 comment block。

- [ ] **Step 5: 在 `wiki-save` 新增最小 block 解析 helper，并把 `--overview-note` 约束为标题下正文**

在 `skills/wiki-save/scripts/save.py` 中新增：

```python
def build_overview_note(linkPath: str, title: str, body: str | None = None) -> str:
  bullet = f"- [[{linkPath}]] - {title}"
  if body and body.strip():
    return f"### {title} ({nowIso()})\n\n{body.strip()}\n\n{bullet}"
  return f"### {title} ({nowIso()})\n\n{bullet}"


def find_synthesis_overview_block_range(overviewText: str, linkPath: str) -> tuple[int, int] | None:
  startTag = f"<!-- synthesis:{linkPath}:start -->"
  endTag = f"<!-- synthesis:{linkPath}:end -->"
  legacyPattern = re.compile(
    rf"{re.escape(startTag)}\n.*?\n{re.escape(endTag)}",
    re.DOTALL,
  )
  legacyMatch = legacyPattern.search(overviewText)
  if legacyMatch:
    return legacyMatch.start(), legacyMatch.end()

  lines = overviewText.splitlines(keepends=True)
  offset = 0
  currentHeadingStart: int | None = None
  currentBlockStart: int | None = None
  currentBlockEnd: int | None = None
  bulletLine = f"- [[{linkPath}]] - "

  for line in lines:
    lineStart = offset
    offset += len(line)
    if re.match(r"^#{1,6} ", line):
      if currentBlockStart is not None and currentBlockEnd is not None:
        return currentBlockStart, currentBlockEnd
      currentHeadingStart = lineStart
      currentBlockStart = None
      currentBlockEnd = None
      continue
    if currentHeadingStart is not None and bulletLine in line:
      currentBlockStart = currentHeadingStart
      currentBlockEnd = offset

  if currentBlockStart is not None and currentBlockEnd is not None:
    return currentBlockStart, currentBlockEnd

  return None
```

然后把 `upsert_overview_synthesis_block()` 改成：

```python
def upsert_overview_synthesis_block(overviewText: str, linkPath: str, note: str) -> str:
  normalizedNote = note.strip()
  blockRange = find_synthesis_overview_block_range(overviewText, linkPath)

  if blockRange:
    start, end = blockRange
    return (overviewText[:start].rstrip() + "\n\n" + normalizedNote + overviewText[end:]).rstrip() + "\n"

  return overviewText.rstrip() + "\n\n" + normalizedNote + "\n"
```

- [ ] **Step 6: 在 `wiki-save` 主流程中让 `--overview-note` 只作为正文补充**

把 `skills/wiki-save/scripts/save.py` 主流程里的 overview note 构造改成：

```python
      overviewBody = args.overview_note.strip() if args.overview_note and args.overview_note.strip() else None
      overviewNote = build_overview_note(linkPath, normalizedInput["title"], body=overviewBody)
      newOverviewText = upsert_overview_synthesis_block(overviewText, linkPath, overviewNote)
```

- [ ] **Step 7: 在 legacy `wiki-query --save` 做同样的 overview block 调整**

把 `skills/wiki-query/scripts/query.py` 中 `build_overview_note()`、`find_synthesis_overview_block_range()`、`upsert_overview_synthesis_block()` 改为与 `wiki-save` 完全一致的实现：

```python
def build_overview_note(link_path: str, title: str, body: str | None = None) -> str:
    bullet = f"- [[{link_path}]] - {title}"
    if body and body.strip():
        return f"### {title} ({now_iso()})\n\n{body.strip()}\n\n{bullet}"
    return f"### {title} ({now_iso()})\n\n{bullet}"


def find_synthesis_overview_block_range(overview_text: str, link_path: str) -> tuple[int, int] | None:
    start_tag = f"<!-- synthesis:{link_path}:start -->"
    end_tag = f"<!-- synthesis:{link_path}:end -->"
    legacy_pattern = re.compile(
        rf"{re.escape(start_tag)}\n.*?\n{re.escape(end_tag)}",
        re.DOTALL,
    )
    legacy_match = legacy_pattern.search(overview_text)
    if legacy_match:
        return legacy_match.start(), legacy_match.end()

    lines = overview_text.splitlines(keepends=True)
    offset = 0
    current_heading_start: int | None = None
    current_block_start: int | None = None
    current_block_end: int | None = None
    bullet_line = f"- [[{link_path}]] - "

    for line in lines:
        line_start = offset
        offset += len(line)
        if re.match(r"^#{1,6} ", line):
            if current_block_start is not None and current_block_end is not None:
                return current_block_start, current_block_end
            current_heading_start = line_start
            current_block_start = None
            current_block_end = None
            continue
        if current_heading_start is not None and bullet_line in line:
            current_block_start = current_heading_start
            current_block_end = offset

    if current_block_start is not None and current_block_end is not None:
        return current_block_start, current_block_end

    return None


def upsert_overview_synthesis_block(overview_text: str, link_path: str, note: str) -> str:
    normalized_note = note.strip()
    block_range = find_synthesis_overview_block_range(overview_text, link_path)

    if block_range:
        start, end = block_range
        return (overview_text[:start].rstrip() + "\n\n" + normalized_note + overview_text[end:]).rstrip() + "\n"

    return overview_text.rstrip() + "\n\n" + normalized_note + "\n"
```

- [ ] **Step 8: 运行 save/query 相关测试并确认通过**

Run: `python3 -m pytest tests/skills/test_save_updates.py tests/skills/test_query_save_legacy_semantics.py -q`
Expected: PASS，overview 写入不再含 `<!-- synthesis:`，旧 comment block 会被新 block 迁移替换，重复保存后手工备注仍保留，`--overview-note` 不会绕过标题行。

- [ ] **Step 9: Commit**

```bash
git add skills/wiki-save/scripts/save.py skills/wiki-query/scripts/query.py tests/skills/test_save_updates.py tests/skills/test_query_save_legacy_semantics.py
git commit -m "feat: 统一 synthesis 概览写法"
```

### Task 2: 支持嵌套 source bundle 的 canonical 解析

**Files:**
- Modify: `skills/wiki-health/scripts/wiki_index.py`
- Modify: `skills/wiki-ingest/scripts/wiki_index.py`
- Modify: `skills/wiki-query/scripts/wiki_index.py`
- Modify: `skills/wiki-save/scripts/wiki_index.py`
- Modify: `skills/wiki-query/scripts/query.py`
- Modify: `tests/skills/test_index_rebuild.py`
- Modify: `tests/skills/test_health_checks.py`
- Modify: `tests/skills/test_query_retrieval_mode.py`

- [ ] **Step 1: 先写 shared helper 失败测试，锁定嵌套 bundle 的 canonical 解析**

在 `tests/skills/test_index_rebuild.py` 增加：

```python
def test_resolve_canonical_markdown_uri_prefers_nested_primary_content_file() -> None:
  kbRoot = "viking://resources/demo/"
  bundleUri = f"{kbRoot}wiki/sources/readme.md"
  nestedDirUri = f"{bundleUri}/llm-wiki-openviking_用户使用版"
  summaryUri = f"{nestedDirUri}/摘要_ca49982d.md"
  relatedUri = f"{nestedDirUri}/相关实体_3more_18dd58ba.md"
  primaryUri = f"{nestedDirUri}/关键内容.md"
  client = FakeClient(
    stats={
      bundleUri: {"isDir": True},
      nestedDirUri: {"isDir": True},
      summaryUri: {"isDir": False},
      relatedUri: {"isDir": False},
      primaryUri: {"isDir": False},
    },
    listings={
      (f"{bundleUri}/", False): [
        {"uri": nestedDirUri, "isDir": True},
      ],
      (f"{bundleUri}/", True): [
        {"uri": nestedDirUri, "isDir": True},
        {"uri": summaryUri, "isDir": False},
        {"uri": relatedUri, "isDir": False},
        {"uri": primaryUri, "isDir": False},
      ],
    },
  )

  assert module.resolve_canonical_markdown_uri(client, bundleUri) == primaryUri
```

再补一个 write target 测试，锁定不会把这类 bundle 回退成 `readme.md/readme.md`：

```python
def test_resolve_markdown_write_target_uri_prefers_nested_primary_content_file() -> None:
  kbRoot = "viking://resources/demo/"
  bundleUri = f"{kbRoot}wiki/sources/readme.md"
  nestedDirUri = f"{bundleUri}/llm-wiki-openviking_用户使用版"
  primaryUri = f"{nestedDirUri}/关键内容.md"
  client = FakeClient(
    stats={
      bundleUri: {"isDir": True},
      nestedDirUri: {"isDir": True},
      primaryUri: {"isDir": False},
    },
    listings={
      (f"{bundleUri}/", False): [
        {"uri": nestedDirUri, "isDir": True},
      ],
      (f"{bundleUri}/", True): [
        {"uri": nestedDirUri, "isDir": True},
        {"uri": primaryUri, "isDir": False},
      ],
    },
  )

  assert module.resolve_markdown_write_target_uri(client, bundleUri) == (primaryUri, False)
```

- [ ] **Step 2: 再写 health 失败测试，锁定 `sources/readme.md` 不再被判 broken**

在 `tests/skills/test_health_checks.py` 增加：

```python
def test_check_index_targets_accepts_nested_source_bundle() -> None:
  kb_root = "viking://resources/my-kb/"
  index_uri = f"{kb_root}wiki/index.md"
  bundle_uri = f"{kb_root}wiki/sources/readme.md"
  nested_dir_uri = f"{bundle_uri}/llm-wiki-openviking_用户使用版"
  primary_uri = f"{nested_dir_uri}/关键内容.md"
  client = FakeClient(
    texts={
      index_uri: "# 索引\n\n## 资料来源\n- [[sources/readme.md]] - README\n",
      primary_uri: "# README\n\n正文内容足够长，用于通过有效页面判断。\n",
    },
    stats={
      index_uri: {"isDir": False},
      bundle_uri: {"isDir": True},
      nested_dir_uri: {"isDir": True},
      primary_uri: {"isDir": False},
    },
    listings={
      (f"{bundle_uri}/", False): [
        {"uri": nested_dir_uri, "isDir": True},
      ],
      (f"{bundle_uri}/", True): [
        {"uri": nested_dir_uri, "isDir": True},
        {"uri": primary_uri, "isDir": False},
      ],
    },
  )

  linked, broken = check_index_targets(client, kb_root)

  assert linked == ["sources/readme.md"]
  assert broken == []
```

再补一个 query 检索测试，锁定 index 里的 `[[sources/readme.md]]` 能读到嵌套正文：

```python
def test_select_relevant_pages_reads_nested_source_bundle_from_index(monkeypatch) -> None:
  kbRoot = "viking://resources/kb/"
  bundleUri = kbRoot + "wiki/sources/readme.md"
  nestedDirUri = bundleUri + "/llm-wiki-openviking_用户使用版"
  primaryUri = nestedDirUri + "/关键内容.md"
  pages = {
    primaryUri: "这是嵌套来源 bundle 的关键内容，包含知识资源与记忆资源差异。",
  }
  client = FakeClient(pages)

  monkeypatch.setattr(module, "read_if_exists", lambda c, uri, default="": "## 资料来源\n- [[sources/readme.md]]\n")

  def fakeStat(uri: str):
    stats = {
      bundleUri: {"isDir": True},
      nestedDirUri: {"isDir": True},
      primaryUri: {"isDir": False},
    }
    if uri not in stats:
      raise module.OVFSHTTPError("404")
    return stats[uri]

  def fakeLs(uri: str, recursive: bool = False):
    if uri == bundleUri + "/" and not recursive:
      return [{"uri": nestedDirUri, "isDir": True}]
    if uri == bundleUri + "/" and recursive:
      return [
        {"uri": nestedDirUri, "isDir": True},
        {"uri": primaryUri, "isDir": False},
      ]
    return []

  client.stat = fakeStat
  client.ls = fakeLs
  module.select_relevant_pages.retrieval_mode = "index"
  module.select_relevant_pages.candidate_multiplier = 2
  module.select_relevant_pages.max_page_chars = 200

  selectedPages, debug = module.select_relevant_pages(client, kbRoot, "知识资源差异", top_k=1)

  assert selectedPages[0]["uri"] == primaryUri
  assert debug["fallback_scan_used"] is False
```

再补一个测试，锁定 bundle 顶层有 `.overview.md` / `.abstract.md` 时 query 不会误选它们：

```python
def test_select_relevant_pages_skips_derived_files_in_nested_bundle(monkeypatch) -> None:
  kbRoot = "viking://resources/kb/"
  bundleUri = kbRoot + "wiki/sources/readme.md"
  nestedDirUri = bundleUri + "/llm-wiki-openviking_用户使用版"
  primaryUri = nestedDirUri + "/关键内容.md"
  overviewDerivedUri = bundleUri + "/.overview.md"
  abstractDerivedUri = bundleUri + "/.abstract.md"
  pages = {
    primaryUri: "这是嵌套来源 bundle 的关键内容。",
    overviewDerivedUri: "这是 derived overview，不应被当作正文。",
    abstractDerivedUri: "这是 derived abstract，不应被当作正文。",
  }
  client = FakeClient(pages)

  monkeypatch.setattr(module, "read_if_exists", lambda c, uri, default="": "## 资料来源\n- [[sources/readme.md]]\n")

  def fakeStat(uri: str):
    stats = {
      bundleUri: {"isDir": True},
      nestedDirUri: {"isDir": True},
      primaryUri: {"isDir": False},
      overviewDerivedUri: {"isDir": False},
      abstractDerivedUri: {"isDir": False},
    }
    if uri not in stats:
      raise module.OVFSHTTPError("404")
    return stats[uri]

  def fakeLs(uri: str, recursive: bool = False):
    if uri == bundleUri + "/" and not recursive:
      return [
        {"uri": overviewDerivedUri, "isDir": False},
        {"uri": abstractDerivedUri, "isDir": False},
        {"uri": nestedDirUri, "isDir": True},
      ]
    if uri == bundleUri + "/" and recursive:
      return [
        {"uri": overviewDerivedUri, "isDir": False},
        {"uri": abstractDerivedUri, "isDir": False},
        {"uri": nestedDirUri, "isDir": True},
        {"uri": primaryUri, "isDir": False},
      ]
    return []

  client.stat = fakeStat
  client.ls = fakeLs
  module.select_relevant_pages.retrieval_mode = "index"
  module.select_relevant_pages.candidate_multiplier = 2
  module.select_relevant_pages.max_page_chars = 200

  selectedPages, debug = module.select_relevant_pages(client, kbRoot, "关键内容", top_k=1)

  assert selectedPages[0]["uri"] == primaryUri
  assert all(".overview.md" not in p["uri"] for p in selectedPages)
  assert all(".abstract.md" not in p["uri"] for p in selectedPages)
```

- [ ] **Step 3: 运行 helper/health/query 定向测试并确认失败**

Run: `python3 -m pytest tests/skills/test_index_rebuild.py tests/skills/test_health_checks.py tests/skills/test_query_retrieval_mode.py -q -k "nested_source_bundle or nested_primary_content_file or nested_source_bundle_from_index or skips_derived_files_in_nested_bundle"`
Expected: FAIL，当前 shared helper 和 `wiki-query` 本地 resolver 都不会下钻到 `readme.md/<nested-dir>/关键内容.md`，或仍会把 `.overview.md` 当正文。

- [ ] **Step 4: 在 shared `wiki_index.py` 增加递归正文发现 helper，并优先选择主内容文件**

在四份 `skills/*/scripts/wiki_index.py` 中新增这些常量与函数：

```python
BUNDLE_METADATA_FILE_NAMES = {"abstract.md"}
NESTED_CONTENT_PRIMARY_FILE_NAMES = ("关键内容.md", "content.md", "index.md", "README.md", "readme.md")
NESTED_CONTENT_DEFERRED_PREFIXES = ("摘要_", "相关实体_")


def list_recursive_content_children(client: Any, uri: str, extensions: tuple[str, ...] = (".md",)) -> list[str]:
  targetUri = uri.rstrip("/") + "/"
  try:
    items = client.ls(targetUri, recursive=True)
  except OVFSHTTPError as exc:
    message = str(exc).lower()
    if "404" in message or "not found" in message:
      return []
    raise

  candidates: list[str] = []
  for item in items:
    childUri = extract_uri_from_ls_item(item)
    if not childUri:
      continue
    name = PurePosixPath(childUri.rstrip("/")).name
    if name in WIKI_DERIVED_FILE_NAMES or name in BUNDLE_METADATA_FILE_NAMES:
      continue
    if not name.endswith(extensions):
      continue
    childIsDir = _extract_child_is_dir_hint(item)
    if childIsDir is None:
      childStat = get_uri_stat(client, childUri)
      childIsDir = bool(childStat and _is_dir_stat(childStat))
    if childIsDir:
      continue
    candidates.append(childUri)

  return candidates


def choose_recursive_content_child(candidates: list[str]) -> str | None:
  if not candidates:
    return None

  def score(uri: str) -> tuple[int, list[Any], str]:
    name = PurePosixPath(uri).name
    if name in NESTED_CONTENT_PRIMARY_FILE_NAMES:
      return (0, _natural_sort_key(name), uri)
    if any(name.startswith(prefix) for prefix in NESTED_CONTENT_DEFERRED_PREFIXES):
      return (2, _natural_sort_key(name), uri)
    return (1, _natural_sort_key(name), uri)

  return sorted(candidates, key=score)[0]
```

- [ ] **Step 5: 在 `resolve_canonical_markdown_uri()` 与 `resolve_markdown_write_target_uri()` 接入递归 fallback**

把 shared helper 中这两段逻辑改成：

```python
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

  recursiveChild = choose_recursive_content_child(list_recursive_content_children(client, uri, extensions=(".md",)))
  if recursiveChild:
    return recursiveChild

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

  recursiveChild = choose_recursive_content_child(list_recursive_content_children(client, uri, extensions=(".md",)))
  if recursiveChild:
    return recursiveChild, False

  return sameNameUri, True
```

- [ ] **Step 6: 在 `wiki-query` 本地 resolver 同步接入嵌套 bundle fallback，并统一目录判断 hint**

把 `skills/wiki-query/scripts/query.py` 中的本地 `find_direct_content_child()` 与 `resolve_canonical_markdown_uri()` 一并改成与 shared helper 一致的目录判断思路，并新增本地 helper：

```python
DERIVED_OR_METADATA_FILE_NAMES = {
    ".abstract.md",
    ".overview.md",
    ".relations.json",
    "abstract.md",
}


def is_dir_stat(stat: dict[str, Any]) -> bool:
    if isinstance(stat.get("isDir"), bool):
        return stat["isDir"]
    if isinstance(stat.get("is_dir"), bool):
        return stat["is_dir"]
    return str(stat.get("type", "")).lower() in {"dir", "directory", "folder"}


def extract_child_is_dir_hint(item: Any) -> bool | None:
    if not isinstance(item, dict):
        return None
    if isinstance(item.get("isDir"), bool):
        return item["isDir"]
    if isinstance(item.get("is_dir"), bool):
        return item["is_dir"]
    if str(item.get("type", "")).lower() in {"dir", "directory", "folder"}:
        return True
    return None


def list_recursive_content_children(client: OVFSClient, uri: str, extensions: tuple[str, ...] = (".md",)) -> list[str]:
    target_uri = uri.rstrip("/") + "/"
    try:
        items = client.ls(target_uri, recursive=True)
    except OVFSHTTPError as exc:
        message = str(exc).lower()
        if "404" in message or "not found" in message:
            return []
        raise

    candidates: list[str] = []
    for item in items:
        child_uri = extract_uri_from_ls_item(item)
        if not child_uri:
            continue
        name = PurePosixPath(child_uri.rstrip("/")).name
        if name in DERIVED_OR_METADATA_FILE_NAMES:
            continue
        if not name.endswith(extensions):
            continue
        child_is_dir = extract_child_is_dir_hint(item)
        if child_is_dir is None:
            child_stat = get_uri_stat(client, child_uri)
            child_is_dir = bool(child_stat and is_dir_stat(child_stat))
        if child_is_dir:
            continue
        candidates.append(child_uri)

    return candidates


def find_direct_content_child(client: OVFSClient, uri: str, extensions: tuple[str, ...] = (".md",)) -> str | None:
    if not uri.endswith("/"):
        uri = uri.rstrip("/") + "/"
    try:
        children = client.ls(uri, recursive=False)
    except OVFSHTTPError as exc:
        message = str(exc).lower()
        if "404" in message or "not found" in message:
            return None
        raise

    candidates: list[str] = []

    for child in children:
        child_uri = extract_uri_from_ls_item(child)
        if not child_uri:
            continue

        name = PurePosixPath(child_uri).name
        if name in DERIVED_OR_METADATA_FILE_NAMES:
            continue
        if not name.endswith(extensions):
            continue

        child_is_dir = extract_child_is_dir_hint(child)
        if child_is_dir is None:
            child_stat = get_uri_stat(client, child_uri)
            child_is_dir = bool(child_stat and is_dir_stat(child_stat))
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


def choose_recursive_content_child(candidates: list[str]) -> str | None:
    if not candidates:
        return None

    def score(uri: str) -> tuple[int, str, str]:
        name = PurePosixPath(uri).name
        if name in {"关键内容.md", "content.md", "index.md", "README.md", "readme.md"}:
            return (0, name.lower(), uri)
        if name.startswith("摘要_") or name.startswith("相关实体_"):
            return (2, name.lower(), uri)
        return (1, name.lower(), uri)

    return sorted(candidates, key=score)[0]


def resolve_canonical_markdown_uri(client: OVFSClient, uri: str) -> str | None:
    stat = get_uri_stat(client, uri)
    if not stat:
        return None

    if not is_dir_stat(stat):
        return uri

    direct_child = find_direct_content_child(client, uri, extensions=(".md",))
    if direct_child:
        return direct_child

    basename = PurePosixPath(uri.rstrip("/")).name
    if basename:
        nested_uri = uri.rstrip("/") + f"/{basename}"
        nested_stat = get_uri_stat(client, nested_uri)
        if nested_stat and not is_dir_stat(nested_stat):
            return nested_uri

    recursive_child = choose_recursive_content_child(list_recursive_content_children(client, uri, extensions=(".md",)))
    if recursive_child:
        return recursive_child

    return None
```

关键变更点：
- `find_direct_content_child()` 跳过 `DERIVED_OR_METADATA_FILE_NAMES`（包含 `.overview.md` / `.abstract.md` / `.relations.json` / `abstract.md`），与 shared helper 一致
- 新增 `is_dir_stat()`，兼容 `isDir` / `is_dir` / `type=dir`
- 所有原先使用 `stat.get("isDir", False)` 的地方都改为 `is_dir_stat(stat)`


- [ ] **Step 7: 扩展 repair-index 测试，锁定 nested source bundle 在 repair 路径也不再 broken**

在 `tests/skills/test_health_checks.py` 新增：

```python
def test_main_repair_index_keeps_nested_source_bundle_link_without_broken_target(monkeypatch: pytest.MonkeyPatch) -> None:
  kb_root = "viking://resources/my-kb/"
  index_uri = f"{kb_root}wiki/index.md"
  index_write_uri = f"{kb_root}wiki/index.md/index.md"
  overview_uri = f"{kb_root}wiki/overview.md"
  log_uri = f"{kb_root}wiki/log.md"
  bundle_uri = f"{kb_root}wiki/sources/readme.md"
  nested_dir_uri = f"{bundle_uri}/llm-wiki-openviking_用户使用版"
  primary_uri = f"{nested_dir_uri}/关键内容.md"
  required_file_uris = required_wiki_pages(kb_root)
  writes: list[dict[str, object]] = []
  printed: list[dict[str, object]] = []

  class RepairClient(FakeClient):
    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc, tb):
      return False

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      writes.append({"uri": uri, "text": text, "create": create, "wait": wait})
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  repair_client = RepairClient(
    texts={
      index_write_uri: "# 索引\n\n## 资料来源\n- [[sources/readme.md]] - README\n",
      overview_uri: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      log_uri: "# 操作日志\n\n记录\n",
      primary_uri: "# README\n\n正文内容足够长，用于通过有效页面判断。\n",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      **{uri: {"isDir": False} for uri in required_file_uris if uri != index_uri},
      index_uri: {"isDir": True},
      index_write_uri: {"isDir": False},
      bundle_uri: {"isDir": True},
      nested_dir_uri: {"isDir": True},
      primary_uri: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/index.md/", False): [{"uri": index_write_uri, "isDir": False}],
      (f"{kb_root}wiki/", True): [
        {"uri": index_write_uri, "isDir": False},
        {"uri": overview_uri, "isDir": False},
        {"uri": log_uri, "isDir": False},
        {"uri": nested_dir_uri, "isDir": True},
        {"uri": primary_uri, "isDir": False},
      ],
      (f"{kb_root}wiki/sources/", True): [
        {"uri": nested_dir_uri, "isDir": True},
        {"uri": primary_uri, "isDir": False},
      ],
      (f"{bundle_uri}/", False): [{"uri": nested_dir_uri, "isDir": True}],
      (f"{bundle_uri}/", True): [
        {"uri": nested_dir_uri, "isDir": True},
        {"uri": primary_uri, "isDir": False},
      ],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
    },
  )

  monkeypatch.setattr(module.OVFSConfig, "load", staticmethod(lambda config_path=None, profile=None: object()))
  monkeypatch.setattr(module, "OVFSClient", lambda config: repair_client)
  monkeypatch.setattr(module, "build_kb_root", lambda kb_name: kb_root)
  monkeypatch.setattr(module, "print_json", lambda data, pretty=False: printed.append(data))
  monkeypatch.setattr(module.sys, "argv", ["health.py", "--kb-name", "my-kb", "--repair-index"])

  exit_code = module.main()

  assert exit_code in (0, 1)
  report = printed[0]
  assert report["repair"]["index_rebuilt"] is True
  assert report["details"]["broken_index_targets"] == []
  assert "[[sources/readme.md]]" in writes[0]["text"]
```

- [ ] **Step 8: 运行 helper/health/query 相关测试并确认通过**

Run: `python3 -m pytest tests/skills/test_index_rebuild.py tests/skills/test_health_checks.py tests/skills/test_query_retrieval_mode.py -q`
Expected: PASS，`sources/readme.md` 这类嵌套 bundle 不再被判 broken，query index 模式能读到 `关键内容.md`，且既有 `abstract.md` / 非 404 `ls` / repair 测试不回退。

- [ ] **Step 9: 检查四份 shared `wiki_index.py` 字节级一致**

Run:

```bash
cmp -s skills/wiki-health/scripts/wiki_index.py skills/wiki-ingest/scripts/wiki_index.py
cmp -s skills/wiki-health/scripts/wiki_index.py skills/wiki-query/scripts/wiki_index.py
cmp -s skills/wiki-health/scripts/wiki_index.py skills/wiki-save/scripts/wiki_index.py
```

Expected: 三条命令都返回 exit 0，无输出。

- [ ] **Step 10: Commit**

```bash
git add skills/wiki-health/scripts/wiki_index.py skills/wiki-ingest/scripts/wiki_index.py skills/wiki-query/scripts/wiki_index.py skills/wiki-save/scripts/wiki_index.py skills/wiki-query/scripts/query.py tests/skills/test_index_rebuild.py tests/skills/test_health_checks.py tests/skills/test_query_retrieval_mode.py
git commit -m "fix: 支持嵌套来源 bundle 解析"
```

### Task 3: 跑回归并验证真实 `esf` 行为

**Files:**
- Verify: `skills/wiki-save/scripts/save.py`
- Verify: `skills/wiki-query/scripts/query.py`
- Verify: `skills/wiki-health/scripts/wiki_index.py`
- Verify: `tests/skills/test_save_updates.py`
- Verify: `tests/skills/test_query_save_legacy_semantics.py`
- Verify: `tests/skills/test_index_rebuild.py`
- Verify: `tests/skills/test_health_checks.py`
- Verify: `tests/skills/test_query_retrieval_mode.py`

- [ ] **Step 1: 跑本地定向测试**

Run: `python3 -m pytest tests/skills/test_save_updates.py tests/skills/test_query_save_legacy_semantics.py tests/skills/test_index_rebuild.py tests/skills/test_health_checks.py tests/skills/test_query_retrieval_mode.py -q`
Expected: PASS，overview block、query nested source 读取、nested source bundle health/repair 三类新回归都通过。

- [ ] **Step 2: 跑全量技能测试**

Run: `python3 -m pytest tests/skills -q`
Expected: PASS，允许保留现有 `urllib3/LibreSSL` warning。

- [ ] **Step 3: 如果要用安装态 skill 做真实验证，先确认安装态已同步当前实现**

Run: `diff -rq "skills/wiki-save" "/Users/sumshine/.config/opencode/skills/wiki-save" && diff -rq "skills/wiki-query" "/Users/sumshine/.config/opencode/skills/wiki-query" && diff -rq "skills/wiki-health" "/Users/sumshine/.config/opencode/skills/wiki-health"`
Expected: 无输出；如果有输出，先把对应 skill 的 `SKILL.md` 与 `scripts/*.py` 最小同步，再继续真实验证。

- [ ] **Step 4: 对真实 `esf` 跑只读 health，确认 `sources/readme.md` 不再 broken**

Run: `bash ~/.config/opencode/skills/wiki-health/scripts/run.sh --kb-name esf --profile ESF --pretty`
Expected: `details.broken_index_targets` 不再包含 `viking://resources/esf/wiki/sources/readme.md`。

- [ ] **Step 5: 对真实 `esf` 做一次 save 路径验证，确认 overview 不再写 comment block**

先用 `wiki-query` 生成 payload：

```bash
bash ~/.config/opencode/skills/wiki-query/scripts/run.sh \
  --kb-name esf \
  --profile ESF \
  --question "请概括 llm-wiki-openviking 中知识资源与记忆资源的差异" \
  --pretty
```

再用返回的 `save_payload_path` 执行保存：

```bash
bash ~/.config/opencode/skills/wiki-save/scripts/run.sh \
  --payload-file <save_payload_path> \
  --pretty
```

Expected: 对应 synthesis 写入成功，且 `viking://resources/esf/wiki/overview.md/overview.md` 中该 synthesis 的 block 形如：

```md
### <标题> (<timestamp>)

- [[syntheses/<slug>.md]] - <标题>
```

并且不再包含：

```md
<!-- synthesis:syntheses/<slug>.md:start -->
```

- [ ] **Step 6: 记录真实验证结果，不再新增 commit**

Expected: 本任务只做验证，不引入新的代码改动；若真实验证暴露新问题，另开新计划处理，不在本任务尾部追加含糊 commit。

## Self-Review

- Spec coverage: 已覆盖两个用户确认的目标：`wiki-save` 与 legacy `wiki-query --save` 的 overview 写法改成标题+时间戳 block；`sources/readme.md` 类嵌套 bundle 按方案 A 修 resolver，不再让 health/repair 持续误报 broken。
- Placeholder scan: 计划中没有 `TODO`、`TBD`、`implement later`、`similar to Task N` 这类占位；每个代码步骤都给了具体函数替换或新增测试代码。
- Type consistency: 计划统一使用现有函数名 `build_overview_note()`、`upsert_overview_synthesis_block()`、`resolve_canonical_markdown_uri()`、`resolve_markdown_write_target_uri()`、`rebuild_index_text()`，没有混入新旧命名冲突。
