# wiki-ingest 异步写入实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 wiki-ingest 的多页面写入从默认同步等待 OpenViking semantic/embedding/indexing 改为默认异步写入，避免每页 `wait=True` 被串行放大导致超时。

**Architecture:** 仅修改 `ingest.py` 中 `write_page()` 的调用策略——新增 `wait_for_indexing` keyword-only 参数（默认 `False`），并在 `parse_args()` 中新增 `--wait-for-indexing` CLI 开关。`main()` 非 dry-run 写入块中的 6 个直接 `write_page()` 调用点（以及 entity/concept 循环产生的所有页面写入）全部显式传参。result JSON 新增两个诊断字段。不改动 `ovfs.py`、`common.py` 或其他 skill。

**Tech Stack:** Python 3.9+, pytest, argparse

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `skills/wiki-ingest/scripts/ingest.py` | 修改 | `write_page` 新增参数、`parse_args` 新增 CLI 开关、`main` 传入参数、result 新增字段 |
| `skills/wiki-ingest/SKILL.md` | 修改 | 文档补充 `--wait-for-indexing` 参数说明和异步写入行为说明 |
| `README.md` | 修改 | FAQ 补充异步索引行为说明 |
| `tests/skills/test_resolve_write_target.py` | 修改 | 新增 `write_page` 默认 `wait=False` 和显式 `wait=True` 两个测试 |
| `tests/skills/test_ingest_context_slimming.py` | 修改 | 现有测试追加断言 + 新增 CLI 参数测试 |
| `tests/skills/test_ingest_chunking.py` | 修改 | 扩展 `FakeOVFSClient` 和 `setup_main_monkeypatch`，新增 main 写入行为和输出字段测试 |

---

### Task 1: 修改 `write_page()` 签名

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py:1157-1159`

- [ ] **Step 1: 修改 `write_page()` 函数**

当前代码（`ingest.py:1157-1159`）：

```python
def write_page(client: OVFSClient, uri: str, markdown: str) -> None:
    target_uri, should_create = resolve_write_target_uri(client, uri)
    client.write_text(target_uri, markdown, create=should_create, wait=True)
```

替换为：

```python
def write_page(
    client: OVFSClient,
    uri: str,
    markdown: str,
    *,
    wait_for_indexing: bool = False,
) -> None:
    target_uri, should_create = resolve_write_target_uri(client, uri)
    client.write_text(
        target_uri,
        markdown,
        create=should_create,
        wait=wait_for_indexing,
    )
```

注意：不加 docstring，保持与原函数风格一致。

- [ ] **Step 2: 确认语法正确**

Run: `python3 -c "import ast; ast.parse(open('skills/wiki-ingest/scripts/ingest.py').read()); print('OK')"`

Expected: `OK`

---

### Task 2: 新增 `--wait-for-indexing` CLI 参数

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py:1180`（在 `--dry-run` 参数定义之后）

- [ ] **Step 1: 在 `parse_args()` 中新增参数**

在 `ingest.py` 的 `parse_args()` 函数中，找到 `--dry-run` 参数定义：

```python
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes back to OpenViking")
```

在该行之后、`--pretty` 之前，插入：

```python
    parser.add_argument(
        "--wait-for-indexing",
        action="store_true",
        help="Wait for OpenViking semantic indexing after each written page. Default is async writes for faster ingest.",
    )
```

- [ ] **Step 2: 确认语法正确**

Run: `python3 -c "import ast; ast.parse(open('skills/wiki-ingest/scripts/ingest.py').read()); print('OK')"`

Expected: `OK`

---

### Task 3: `main()` 写入阶段传入 `wait_for_indexing` 参数

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py:1342-1364`

- [ ] **Step 1: 在 `main()` 中写入阶段前新增局部变量，并修改所有 `write_page` 调用**

找到 `main()` 中的 `write_plan = {` 块（约 `ingest.py:1342`）。在该块之前，新增：

```python
            write_wait_for_indexing = bool(args.wait_for_indexing)
```

然后将 `ingest.py:1351-1364` 的非 dry-run 写入块（共 6 个直接调用点：1 个 source 页 + entity 循环 + concept 循环 + index + overview + log）：

```python
            if not args.dry_run:
                write_page(client, source_page_uri, source_page_markdown)

                for page in entity_pages:
                    uri = kb_root + f"wiki/entities/{page['slug']}.md"
                    write_page(client, uri, page["markdown"])

                for page in concept_pages:
                    uri = kb_root + f"wiki/concepts/{page['slug']}.md"
                    write_page(client, uri, page["markdown"])

                write_page(client, index_uri, new_index_text)
                write_page(client, overview_uri, new_overview_text)
                write_page(client, log_uri, new_log_text)
```

替换为：

```python
            if not args.dry_run:
                write_page(
                    client,
                    source_page_uri,
                    source_page_markdown,
                    wait_for_indexing=write_wait_for_indexing,
                )

                for page in entity_pages:
                    uri = kb_root + f"wiki/entities/{page['slug']}.md"
                    write_page(
                        client,
                        uri,
                        page["markdown"],
                        wait_for_indexing=write_wait_for_indexing,
                    )

                for page in concept_pages:
                    uri = kb_root + f"wiki/concepts/{page['slug']}.md"
                    write_page(
                        client,
                        uri,
                        page["markdown"],
                        wait_for_indexing=write_wait_for_indexing,
                    )

                write_page(
                    client,
                    index_uri,
                    new_index_text,
                    wait_for_indexing=write_wait_for_indexing,
                )
                write_page(
                    client,
                    overview_uri,
                    new_overview_text,
                    wait_for_indexing=write_wait_for_indexing,
                )
                write_page(
                    client,
                    log_uri,
                    new_log_text,
                    wait_for_indexing=write_wait_for_indexing,
                )
```

- [ ] **Step 2: 确认语法正确**

Run: `python3 -c "import ast; ast.parse(open('skills/wiki-ingest/scripts/ingest.py').read()); print('OK')"`

Expected: `OK`

---

### Task 4: result JSON 新增诊断字段

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py:1380`（`"dry_run": args.dry_run` 之后）

- [ ] **Step 1: 在 result dict 中新增字段**

找到 result dict 中的 `"dry_run"` 行（约 `ingest.py:1380`）：

```python
                "dry_run": args.dry_run,
```

在该行之后插入：

```python
                "write_wait_for_indexing": write_wait_for_indexing,
                "semantic_indexing_mode": "sync" if write_wait_for_indexing else "async",
```

注意：在 dry-run 模式下，这两个字段表示 planned write mode（"如果写入会使用哪种模式"），不代表已经发生实际写入或实际索引等待。

- [ ] **Step 2: 确认语法正确**

Run: `python3 -c "import ast; ast.parse(open('skills/wiki-ingest/scripts/ingest.py').read()); print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit 代码修改**

可选 commit 步骤。必须在 Task 11 全量测试通过后再提交；也可在所有任务完成后统一提交一次。

```bash
git add skills/wiki-ingest/scripts/ingest.py
git commit -m "feat(ingest): default to async writes, add --wait-for-indexing flag"
```

---

### Task 5: 新增 `write_page` wait 行为测试

**Files:**
- Modify: `tests/skills/test_resolve_write_target.py`

- [ ] **Step 1: 在文件末尾新增两个测试**

在 `tests/skills/test_resolve_write_target.py` 末尾（第 457 行之后）追加：

```python


# ===== write_page wait 行为测试 =====

def test_write_page_defaults_to_async_write_wait_false() -> None:
  target_uri = "viking://resources/my-kb/wiki/concepts/new-thing.md"
  write_text_calls = []

  client = DummyOVFS()

  def fake_write_text(uri, content, create=False, append=False, wait=False, timeout=None):
    write_text_calls.append(
      {
        "uri": uri,
        "content": content,
        "create": create,
        "wait": wait,
      }
    )
    return {}

  client.write_text = fake_write_text

  with patch.object(module, "get_uri_stat", return_value=None):
    write_page(client, target_uri, "# 新概念\n\n内容")

  assert len(write_text_calls) == 1
  assert write_text_calls[0]["uri"] == target_uri
  assert write_text_calls[0]["create"] is True
  assert write_text_calls[0]["wait"] is False


def test_write_page_can_wait_for_indexing() -> None:
  target_uri = "viking://resources/my-kb/wiki/concepts/new-thing.md"
  write_text_calls = []

  client = DummyOVFS()

  def fake_write_text(uri, content, create=False, append=False, wait=False, timeout=None):
    write_text_calls.append(
      {
        "uri": uri,
        "content": content,
        "create": create,
        "wait": wait,
      }
    )
    return {}

  client.write_text = fake_write_text

  with patch.object(module, "get_uri_stat", return_value=None):
    write_page(
      client,
      target_uri,
      "# 新概念\n\n内容",
      wait_for_indexing=True,
    )

  assert len(write_text_calls) == 1
  assert write_text_calls[0]["uri"] == target_uri
  assert write_text_calls[0]["create"] is True
  assert write_text_calls[0]["wait"] is True
```

- [ ] **Step 2: 运行测试验证通过**

Run: `python3 -m pytest tests/skills/test_resolve_write_target.py -v`

Expected: 所有测试 PASS（包括原有测试和两个新增测试）

---

### Task 6: 补充 CLI 参数测试

**Files:**
- Modify: `tests/skills/test_ingest_context_slimming.py`

- [ ] **Step 1: 修改现有默认值测试，追加断言**

找到 `test_parse_args_supports_context_slimming_defaults`（约 `test_ingest_context_slimming.py:157-166`）：

```python
def test_parse_args_supports_context_slimming_defaults(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    ["ingest.py", "--kb-name", "demo", "--source-uri", "viking://resources/demo/raw/a.md"],
  )
  args = module.parse_args()

  assert args.max_context_chars == 12000
  assert args.max_existing_page_names == 100
```

在最后一个 `assert` 之后追加一行：

```python
  assert args.wait_for_indexing is False
```

- [ ] **Step 2: 在文件末尾新增 `--wait-for-indexing` 测试**

在 `test_ingest_context_slimming.py` 末尾（第 185 行之后）追加：

```python


def test_parse_args_supports_wait_for_indexing(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "ingest.py",
      "--kb-name",
      "demo",
      "--source-uri",
      "viking://resources/demo/raw/a.md",
      "--wait-for-indexing",
    ],
  )
  args = module.parse_args()

  assert args.wait_for_indexing is True
```

- [ ] **Step 3: 运行测试验证通过**

Run: `python3 -m pytest tests/skills/test_ingest_context_slimming.py -v`

Expected: 所有测试 PASS

---

### Task 7: 扩展 FakeOVFSClient 和 setup_main_monkeypatch

**Files:**
- Modify: `tests/skills/test_ingest_chunking.py:21-94`

- [ ] **Step 1: 扩展 `FakeOVFSClient`**

找到 `FakeOVFSClient.__init__`（`test_ingest_chunking.py:22-29`）：

```python
  def __init__(self, source_text: str) -> None:
    self.source_uri = "viking://resources/demo/raw/long.md"
    self.texts = {
      self.source_uri: source_text,
      "viking://resources/demo/wiki/index.md": "# 索引\n\n## 实体\n\n## 概念\n",
      "viking://resources/demo/wiki/overview.md": "# 概览\n",
      "viking://resources/demo/wiki/log.md": "# 操作日志\n",
    }
```

替换为：

```python
  def __init__(self, source_text: str) -> None:
    self.source_uri = "viking://resources/demo/raw/long.md"
    self.texts = {
      self.source_uri: source_text,
      "viking://resources/demo/wiki/index.md": "# 索引\n\n## 实体\n\n## 概念\n",
      "viking://resources/demo/wiki/overview.md": "# 概览\n",
      "viking://resources/demo/wiki/log.md": "# 操作日志\n",
    }
    self.write_text_calls: list[dict[str, Any]] = []
```

同时在文件顶部找到 import 区域（`test_ingest_chunking.py:1-6`）：

```python
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys
```

在 `import json` 之后追加：

```python
from typing import Any
```

然后找到 `FakeOVFSClient.write_text`（`test_ingest_chunking.py:54-55`）：

```python
  def write_text(self, uri: str, markdown: str, create: bool, wait: bool) -> None:
    self.texts[uri] = markdown
```

替换为：

```python
  def write_text(self, uri: str, markdown: str, create: bool, wait: bool) -> None:
    self.write_text_calls.append(
      {
        "uri": uri,
        "markdown": markdown,
        "create": create,
        "wait": wait,
      }
    )
    self.texts[uri] = markdown
```

- [ ] **Step 2: 扩展 `setup_main_monkeypatch`，增加 `dry_run` 参数并返回 client**

找到 `setup_main_monkeypatch`（`test_ingest_chunking.py:58-94`）：

```python
def setup_main_monkeypatch(
  monkeypatch: pytest.MonkeyPatch,
  *,
  source_text: str,
  argv_extra: list[str],
  call_llm_impl,
) -> None:
  client = FakeOVFSClient(source_text)

  class DummyConfig:
    @staticmethod
    def load(config_path=None, profile=None):
      return object()

  monkeypatch.setattr(module, "OVFSConfig", DummyConfig)
  monkeypatch.setattr(module, "OVFSClient", lambda config: client)
  monkeypatch.setattr(module, "load_config", lambda config_path=None, profile=None: {})
  monkeypatch.setattr(
    module,
    "resolve_openai_settings",
    lambda args: {"api_key": "k", "base_url": None, "model": "m"},
  )
  monkeypatch.setattr(module, "read_local_schema", lambda: "# schema")
  monkeypatch.setattr(module, "call_llm", call_llm_impl)
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "ingest.py",
      "--kb-name",
      "demo",
      "--source-uri",
      "viking://resources/demo/raw/long.md",
      "--dry-run",
      *argv_extra,
    ],
  )
```

替换为：

```python
def setup_main_monkeypatch(
  monkeypatch: pytest.MonkeyPatch,
  *,
  source_text: str,
  argv_extra: list[str],
  call_llm_impl,
  dry_run: bool = True,
) -> FakeOVFSClient:
  client = FakeOVFSClient(source_text)

  class DummyConfig:
    @staticmethod
    def load(config_path=None, profile=None):
      return object()

  monkeypatch.setattr(module, "OVFSConfig", DummyConfig)
  monkeypatch.setattr(module, "OVFSClient", lambda config: client)
  monkeypatch.setattr(module, "load_config", lambda config_path=None, profile=None: {})
  monkeypatch.setattr(
    module,
    "resolve_openai_settings",
    lambda args: {"api_key": "k", "base_url": None, "model": "m"},
  )
  monkeypatch.setattr(module, "read_local_schema", lambda: "# schema")
  monkeypatch.setattr(module, "call_llm", call_llm_impl)

  argv = [
    "ingest.py",
    "--kb-name",
    "demo",
    "--source-uri",
    "viking://resources/demo/raw/long.md",
  ]
  if dry_run:
    argv.append("--dry-run")
  argv.extend(argv_extra)
  monkeypatch.setattr(sys, "argv", argv)

  return client
```

- [ ] **Step 3: 运行现有测试确认不退化**

Run: `python3 -m pytest tests/skills/test_ingest_chunking.py -v`

Expected: 所有已有测试 PASS（`setup_main_monkeypatch` 默认 `dry_run=True`，向后兼容）

---

### Task 8: 新增 main 写入行为和输出字段测试

**Files:**
- Modify: `tests/skills/test_ingest_chunking.py`（在文件末尾追加）

- [ ] **Step 1: 新增默认异步写入测试**

在 `test_ingest_chunking.py` 末尾追加：

```python


def test_main_default_write_wait_false_and_outputs_async_mode(
  monkeypatch: pytest.MonkeyPatch,
  capsys: pytest.CaptureFixture[str],
) -> None:
  source_text = "# T\nshort"

  def fake_call_llm(prompt: str, *, api_key, base_url, model):
    return {
      "source_title": "短文档",
      "source_page_markdown": "# 短文档\n\n正文",
      "entity_pages": [
        {"slug": "entity-a", "title": "实体A", "markdown": "# 实体A\n\n正文"}
      ],
      "concept_pages": [
        {"slug": "concept-a", "title": "概念A", "markdown": "# 概念A\n\n正文"}
      ],
      "overview_note": "新增短文档。",
      "log_note": "ingest 短文档。",
    }

  client = setup_main_monkeypatch(
    monkeypatch,
    source_text=source_text,
    argv_extra=[],
    call_llm_impl=fake_call_llm,
    dry_run=False,
  )

  exit_code = module.main()
  output = capsys.readouterr().out
  result = json.loads(output)

  assert exit_code == 0
  assert result["status"] == "ok"
  assert result["write_wait_for_indexing"] is False
  assert result["semantic_indexing_mode"] == "async"
  assert len(client.write_text_calls) > 0
  assert all(call["wait"] is False for call in client.write_text_calls)
```

- [ ] **Step 2: 新增显式同步写入测试**

继续在末尾追加：

```python


def test_main_wait_for_indexing_writes_with_wait_true_and_outputs_sync_mode(
  monkeypatch: pytest.MonkeyPatch,
  capsys: pytest.CaptureFixture[str],
) -> None:
  source_text = "# T\nshort"

  def fake_call_llm(prompt: str, *, api_key, base_url, model):
    return {
      "source_title": "短文档",
      "source_page_markdown": "# 短文档\n\n正文",
      "entity_pages": [
        {"slug": "entity-a", "title": "实体A", "markdown": "# 实体A\n\n正文"}
      ],
      "concept_pages": [
        {"slug": "concept-a", "title": "概念A", "markdown": "# 概念A\n\n正文"}
      ],
      "overview_note": "新增短文档。",
      "log_note": "ingest 短文档。",
    }

  client = setup_main_monkeypatch(
    monkeypatch,
    source_text=source_text,
    argv_extra=["--wait-for-indexing"],
    call_llm_impl=fake_call_llm,
    dry_run=False,
  )

  exit_code = module.main()
  output = capsys.readouterr().out
  result = json.loads(output)

  assert exit_code == 0
  assert result["status"] == "ok"
  assert result["write_wait_for_indexing"] is True
  assert result["semantic_indexing_mode"] == "sync"
  assert len(client.write_text_calls) > 0
  assert all(call["wait"] is True for call in client.write_text_calls)
```

- [ ] **Step 3: 运行测试验证通过**

Run: `python3 -m pytest tests/skills/test_ingest_chunking.py -v`

Expected: 所有测试 PASS（包括原有测试和 2 个新增 main 写入测试）

- [ ] **Step 4: Commit 测试修改**

可选 commit 步骤。必须在对应测试通过后再提交；也可在所有任务完成后统一提交一次。

```bash
git add tests/skills/test_resolve_write_target.py tests/skills/test_ingest_context_slimming.py tests/skills/test_ingest_chunking.py
git commit -m "test(ingest): add write_page wait behavior and CLI arg tests"
```

---

### Task 9: 更新 SKILL.md

**Files:**
- Modify: `skills/wiki-ingest/SKILL.md`

- [ ] **Step 1: 在可选参数列表中新增 `--wait-for-indexing`**

找到 `SKILL.md:34` 的可选参数行：

```text
可选参数：`--config <path>`、`--profile <name>`、`--max-context-chars <int>`、`--max-existing-page-names <int>`、`--long-doc-threshold <int>`、`--chunk-size <int>`、`--chunk-overlap <int>`、`--max-chunks <int>`、`--allow-partial-chunks`。
```

在末尾 `` `--allow-partial-chunks` `` 之后追加 `、\`--wait-for-indexing\``：

```text
可选参数：`--config <path>`、`--profile <name>`、`--max-context-chars <int>`、`--max-existing-page-names <int>`、`--long-doc-threshold <int>`、`--chunk-size <int>`、`--chunk-overlap <int>`、`--max-chunks <int>`、`--allow-partial-chunks`、`--wait-for-indexing`。
```

- [ ] **Step 2: 在参数说明区域新增 `--wait-for-indexing` 说明**

找到 `SKILL.md:42`（`--allow-partial-chunks` 说明之后）：

```text
- `--allow-partial-chunks`：仅允许跳过失败的 chunk summary（至少成功 1 块）；不允许 source truncation。
```

在该行之后追加：

```text
- `--wait-for-indexing`：写入每个 wiki 页面后等待 OpenViking semantic/embedding/indexing 完成；默认不等待，以避免多页面 ingest 被后台索引串行放大。
```

- [ ] **Step 3: 在"行为说明"部分补充异步写入说明**

找到 `SKILL.md:44` 的"行为说明："段落：

```text
行为说明：

- `index.md` / `overview.md` 仍会完整读取并用于确定性更新。
```

在"行为说明："之后、第一个 bullet 之前，插入：

```text
- wiki-ingest 默认使用异步写入：写入页面时不等待 OpenViking 的 semantic/embedding/indexing 后台处理完成。
- 默认模式下，页面内容、index.md、overview.md、log.md 会快速写入；但刚结束后的短时间内，语义 search/query 可能暂时搜不到新内容。
- 如需要 ingest 返回后立即尽量保证语义检索可用，可传 `--wait-for-indexing`，但该模式会恢复每页串行等待，可能明显变慢。
```

- [ ] **Step 4: 新增同步索引示例（在 dry-run 示例之后）**

找到 `SKILL.md:59` 的 dry-run 示例块之后，追加：

````markdown

同步索引模式（写入后等待语义索引完成，会较慢）：

```bash
bash ~/.config/opencode/skills/wiki-ingest/scripts/run.sh \
  --kb-name <kb-name> \
  --source-uri <full-raw-source-uri> \
  --wait-for-indexing \
  --pretty
```
````

- [ ] **Step 5: Commit**

可选 commit 步骤。必须在对应测试通过后再提交；也可在所有任务完成后统一提交一次。

```bash
git add skills/wiki-ingest/SKILL.md
git commit -m "docs(ingest): document async write default and --wait-for-indexing"
```

---

### Task 10: 更新 README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 `wiki-ingest` 典型说法附近补充说明**

找到 `README.md:113` 的 wiki-ingest 条目：

```text
3. `wiki-ingest`
   - 「把 `<kb>` 的 `raw/<source>.md` ingest 成 wiki 页面，并更新 index/overview/log」
```

在该行之后追加说明：

```text
   - 说明：`wiki-ingest` 默认快速异步写入，不等待 OpenViking 后台 semantic/embedding/indexing 完成；刚写完后可直接读取页面，但语义 search/query 可能需要等待后台处理完成。如必须 ingest 结束后立刻进行语义检索，可使用 `--wait-for-indexing`。
```

- [ ] **Step 2: 在 FAQ 补充 Q6**

找到 `README.md` 中 Q5 的内容结束处——即 `默认在远端：\`viking://resources/<kb>/wiki/graph/graph.json\` 与 \`viking://resources/<kb>/wiki/graph/graph.html\`。` 这一行之后。在该行之后、紧随其后的 `---` 分隔线之前插入 Q6：

```text

### Q6：为什么 wiki-ingest 结束后马上 query 可能搜不到新内容？

`wiki-ingest` 默认不等待 OpenViking 后台 semantic/embedding/indexing 完成，因此页面已经写入后，语义检索索引可能还在后台更新。稍等后台处理完成后再 query 即可；如果必须同步等待，可在 ingest 时加 `--wait-for-indexing`，但会明显变慢。
```

- [ ] **Step 3: Commit**

可选 commit 步骤。必须在对应测试通过后再提交；也可在所有任务完成后统一提交一次。

```bash
git add README.md
git commit -m "docs: add async write behavior FAQ for wiki-ingest"
```

---

### Task 11: 全量测试验证

**Files:**
- None

- [ ] **Step 1: 运行重点测试**

```bash
python3 -m pytest tests/skills/test_resolve_write_target.py -v
python3 -m pytest tests/skills/test_ingest_context_slimming.py -v
python3 -m pytest tests/skills/test_ingest_chunking.py -v
```

Expected: 全部 PASS

- [ ] **Step 2: 运行文档和共享脚本测试**

```bash
python3 -m pytest tests/skills/test_readme_user_flow.py -v
python3 -m pytest tests/skills/test_skill_docs_no_legacy_command.py -v
python3 -m pytest tests/skills/test_shared_script_consistency.py -v
```

Expected: 全部 PASS（`test_shared_script_consistency.py` 必须通过，确认未改动 `ovfs.py`/`common.py`）

- [ ] **Step 3: 运行其他 ingest 相关测试**

```bash
python3 -m pytest tests/skills/test_ingest_source_bundle.py -v
python3 -m pytest tests/skills/test_ingest_schema_loading.py -v
```

Expected: 全部 PASS

- [ ] **Step 4: 运行全量测试**

```bash
python3 -m pytest tests/skills -v
```

Expected: 全部 PASS
