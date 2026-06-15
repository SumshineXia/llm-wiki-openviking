# wiki-bootstrap 异步初始化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `wiki-bootstrap` 的基础页面创建从默认同步等待 OpenViking 语义处理改为默认异步返回，避免 KB 初始化因后端 overview/embedding 超时而在客户端报 `ReadTimeout`。

**Architecture:** 仅修改 `skills/wiki-bootstrap/scripts/bootstrap.py` 的本地初始化链路，不改 `ovfs.py`。在 bootstrap 内新增一个只服务当前脚本的文本文件创建 helper，默认以 `wait=False` 写入基础页面，并通过新的 `--wait-for-indexing` CLI 开关保留显式同步等待模式；同时补充测试和 skill 文档说明。

**Tech Stack:** Python 3, argparse, pytest

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `skills/wiki-bootstrap/scripts/bootstrap.py` | 修改 | 新增 bootstrap 专用异步写入 helper、CLI 开关、等待策略下传 |
| `skills/wiki-bootstrap/SKILL.md` | 修改 | 补充 `--wait-for-indexing` 用法和默认异步行为说明 |
| `tests/skills/test_bootstrap_cli.py` | 修改 | 锁定默认 `wait=False`、显式 `wait=True`、CLI 参数解析行为 |

## Implementation Notes

- 范围只限 `wiki-bootstrap`，不要顺手修改 `wiki-query`、`wiki-health`、`wiki-save`、`wiki-ingest`。
- 不要修改 `skills/wiki-bootstrap/scripts/ovfs.py`、`common.py`、README 或其他 skill。
- 必须保持最小必要修改，不新增无关 result 字段、不做额外重构。
- 用户已明确要求：**不要执行 `git commit`、`git commit --amend`、`git push`。**
- 所有新增测试必须先失败，再实现最小代码让其通过。
- 如果实现中发现现有测试基线与计划不符，停止并返回 `BLOCKED`，不要自行扩大 scope。

---

### Task 1: 先写失败测试，锁定 bootstrap 默认异步行为

**Files:**
- Modify: `tests/skills/test_bootstrap_cli.py`
- Test: `tests/skills/test_bootstrap_cli.py`

- [ ] **Step 1: 在模块导出绑定处补充待测试函数引用**

在 `tests/skills/test_bootstrap_cli.py` 顶部已有绑定：

```python
plan_bootstrap_paths = module.plan_bootstrap_paths
build_initial_file_content = module.build_initial_file_content
parse_args = module.parse_args
```

替换为：

```python
plan_bootstrap_paths = module.plan_bootstrap_paths
build_initial_file_content = module.build_initial_file_content
ensure_bootstrap_text_file = module.ensure_bootstrap_text_file
apply_bootstrap = module.apply_bootstrap
parse_args = module.parse_args
```

预期：当前实现还没有 `ensure_bootstrap_text_file`，这一步是为了让后续测试在导入阶段直接暴露缺失行为。

- [ ] **Step 2: 在文件末尾追加 3 个失败测试**

在 `tests/skills/test_bootstrap_cli.py` 文件末尾追加：

```python


def test_ensure_bootstrap_text_file_defaults_to_async_wait_false() -> None:
  class FakeClient:
    def __init__(self) -> None:
      self.write_calls = []

    def exists(self, uri: str) -> bool:
      return False

    def write_text(self, uri: str, content: str, create: bool = False, wait: bool = True):
      self.write_calls.append(
        {
          "uri": uri,
          "content": content,
          "create": create,
          "wait": wait,
        }
      )

  client = FakeClient()
  uri = "viking://resources/demo/wiki/index.md"
  content = "# 索引\n\n"

  ensure_bootstrap_text_file(client, uri, content)

  assert client.write_calls == [
    {
      "uri": uri,
      "content": content,
      "create": True,
      "wait": False,
    }
  ]


def test_apply_bootstrap_passes_wait_for_indexing_true_to_page_writes(monkeypatch) -> None:
  dir_calls = []
  file_calls = []

  class FakeClient:
    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc, tb):
      return None

  def fake_ovfs_client(config):
    return FakeClient()

  def fake_ensure_dir(client, uri):
    dir_calls.append(uri)

  def fake_ensure_bootstrap_text_file(client, uri, content, *, waitForIndexing):
    file_calls.append(
      {
        "uri": uri,
        "content": content,
        "waitForIndexing": waitForIndexing,
      }
    )

  monkeypatch.setattr(module, "OVFSClient", fake_ovfs_client)
  monkeypatch.setattr(module, "ensure_dir", fake_ensure_dir)
  monkeypatch.setattr(module, "ensure_bootstrap_text_file", fake_ensure_bootstrap_text_file)

  plan = {
    "dirs": ["viking://resources/demo/raw/"],
    "files": [
      "viking://resources/demo/wiki/index.md",
      "viking://resources/demo/wiki/overview.md",
    ],
  }

  apply_bootstrap(plan, config=object(), waitForIndexing=True)

  assert dir_calls == ["viking://resources/demo/raw/"]
  assert [item["uri"] for item in file_calls] == plan["files"]
  assert all(item["waitForIndexing"] is True for item in file_calls)


def test_parse_args_supports_wait_for_indexing(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "bootstrap.py",
      "--kb-name",
      "team-a/project-x/wiki-kb",
      "--wait-for-indexing",
    ],
  )

  args = parse_args()

  assert args.wait_for_indexing is True
```

- [ ] **Step 3: 运行测试，确认红灯且失败原因正确**

Run: `pytest tests/skills/test_bootstrap_cli.py -q`

Expected:
- 至少出现 1 个 FAIL 或 import 阶段错误
- 失败原因应与 `module.ensure_bootstrap_text_file` 缺失、`apply_bootstrap()` 不接受 `waitForIndexing`、或 `parse_args()` 不识别 `--wait-for-indexing` 有关
- 不能是语法错误、拼写错误、缩进错误

---

### Task 2: 在 `bootstrap.py` 实现最小异步写入逻辑

**Files:**
- Modify: `skills/wiki-bootstrap/scripts/bootstrap.py`

- [ ] **Step 1: 调整 import，去掉对 `ensure_text_file` 的依赖**

当前 import：

```python
from ovfs import OVFSClient, OVFSConfig, ensure_dir, ensure_text_file
```

替换为：

```python
from ovfs import OVFSClient, OVFSConfig, ensure_dir
```

- [ ] **Step 2: 在 `build_initial_file_content()` 后新增 bootstrap 专用 helper**

在 `skills/wiki-bootstrap/scripts/bootstrap.py` 的 `build_initial_file_content()` 函数后、`apply_bootstrap()` 前插入：

```python
def ensure_bootstrap_text_file(
  client: OVFSClient,
  uri: str,
  content: str,
  *,
  waitForIndexing: bool = False,
) -> None:
  if client.exists(uri):
    return
  client.write_text(uri, content, create=True, wait=waitForIndexing)
```

注意：
- 不要把这个 helper 放到 `ovfs.py`
- 不要新增 docstring
- `waitForIndexing` 名称在本文件内保持一致，不要同时再引入第二个同义参数名

- [ ] **Step 3: 修改 `apply_bootstrap()`，显式下传等待策略**

当前函数：

```python
def apply_bootstrap(plan: dict[str, list[str]], config: OVFSConfig) -> None:
  with OVFSClient(config) as client:
    for dirUri in plan["dirs"]:
      ensure_dir(client, dirUri)

    for fileUri in plan["files"]:
      ensure_text_file(client, fileUri, build_initial_file_content(fileUri))
```

替换为：

```python
def apply_bootstrap(
  plan: dict[str, list[str]],
  config: OVFSConfig,
  waitForIndexing: bool = False,
) -> None:
  with OVFSClient(config) as client:
    for dirUri in plan["dirs"]:
      ensure_dir(client, dirUri)

    for fileUri in plan["files"]:
      ensure_bootstrap_text_file(
        client,
        fileUri,
        build_initial_file_content(fileUri),
        waitForIndexing=waitForIndexing,
      )
```

- [ ] **Step 4: 在 `parse_args()` 中新增 CLI 开关**

在 `--dry-run` 参数之后、`--pretty` 之前插入：

```python
  parser.add_argument(
    "--wait-for-indexing",
    action="store_true",
    help="等待 OpenViking 在每个基础页面写入后完成语义处理；默认异步返回。",
  )
```

- [ ] **Step 5: 在 `main()` 中将 CLI 选项传入 `apply_bootstrap()`**

当前调用：

```python
    apply_bootstrap(plan, config)
```

替换为：

```python
    apply_bootstrap(plan, config, waitForIndexing=bool(args.wait_for_indexing))
```

- [ ] **Step 6: 运行目标测试，确认绿灯**

Run: `pytest tests/skills/test_bootstrap_cli.py -q`

Expected:
- 所有测试 PASS
- 没有新增失败测试
- 输出中不应再出现 `unrecognized arguments: --wait-for-indexing` 或缺少 `ensure_bootstrap_text_file` 的错误

---

### Task 3: 更新 skill 文档，明确默认异步与显式同步模式

**Files:**
- Modify: `skills/wiki-bootstrap/SKILL.md`

- [ ] **Step 1: 更新执行方式章节中的命令示例和参数说明**

将现有执行方式片段：

```markdown
```bash
bash ~/.config/opencode/skills/wiki-bootstrap/scripts/run.sh --kb-name <kb-name> --pretty
```

可选参数：`--config <path>`、`--profile <name>`。

仅预览（不写入）：

```bash
bash ~/.config/opencode/skills/wiki-bootstrap/scripts/run.sh --kb-name <kb-name> --dry-run --pretty
```
```

替换为：

```markdown
```bash
bash ~/.config/opencode/skills/wiki-bootstrap/scripts/run.sh --kb-name <kb-name> --pretty
```

默认行为：基础目录和根页面创建请求会尽快返回，不等待 OpenViking 对页面完成语义处理。

如需显式等待索引完成：

```bash
bash ~/.config/opencode/skills/wiki-bootstrap/scripts/run.sh --kb-name <kb-name> --wait-for-indexing --pretty
```

可选参数：`--config <path>`、`--profile <name>`、`--wait-for-indexing`。

仅预览（不写入）：

```bash
bash ~/.config/opencode/skills/wiki-bootstrap/scripts/run.sh --kb-name <kb-name> --dry-run --pretty
```
```

注意：不要改动 skill 的职责边界、强约束、标题或 front matter。

- [ ] **Step 2: 运行文档相关测试基线**

Run: `pytest tests/skills/test_bootstrap_cli.py -q`

Expected:
- 仍然全部 PASS
- 文档修改不影响现有 Python 测试导入

---

### Task 4: 做最小验证，不提交代码

**Files:**
- Modify: `skills/wiki-bootstrap/scripts/bootstrap.py`
- Modify: `skills/wiki-bootstrap/SKILL.md`
- Modify: `tests/skills/test_bootstrap_cli.py`

- [ ] **Step 1: 运行一次精确的 CLI dry-run 验证**

Run: `python3 skills/wiki-bootstrap/scripts/bootstrap.py --kb-name team-a/project-x/wiki-kb --dry-run --pretty`

Expected:
- 输出 JSON 中 `kb_name` 为 `team-a/project-x/wiki-kb`
- `dry_run` 为 `true`
- `plan.dirs` 与 `plan.files` 结构保持不变
- 不要求在 dry-run 输出中新增任何字段

- [ ] **Step 2: 运行一次 AST 语法校验**

Run: `python3 -c "import ast; ast.parse(open('skills/wiki-bootstrap/scripts/bootstrap.py', encoding='utf-8').read()); print('OK')"`

Expected: `OK`

- [ ] **Step 3: 汇总结果但不要提交代码**

执行完成后：
- 保持工作树修改为未提交状态
- 不要运行任何 `git commit` / `git commit --amend` / `git push`
- 如果使用 subagent，最终回报必须使用以下格式：

```text
STATUS: OK | BLOCKED | NEEDS_CONTEXT
SUMMARY:
- ...
TESTS:
- `pytest tests/skills/test_bootstrap_cli.py -q`
- `python3 skills/wiki-bootstrap/scripts/bootstrap.py --kb-name team-a/project-x/wiki-kb --dry-run --pretty`
- `python3 -c "import ast; ast.parse(open('skills/wiki-bootstrap/scripts/bootstrap.py', encoding='utf-8').read()); print('OK')"`
SELF_REVIEW:
- ...
FILES:
- skills/wiki-bootstrap/scripts/bootstrap.py
- skills/wiki-bootstrap/SKILL.md
- tests/skills/test_bootstrap_cli.py
CONCERNS:
- ...
```

---

## Self-Review Checklist

- Spec coverage: 计划只覆盖 `wiki-bootstrap` 默认异步初始化、可选 `--wait-for-indexing`、测试与文档，无其他 skill 改动。
- Placeholder scan: 无 `TBD`、`TODO`、"类似前面任务"、"补充适当错误处理" 之类占位说法。
- Type consistency: `waitForIndexing` 在测试、helper、`apply_bootstrap()`、`main()` 中保持同名；CLI 名称固定为 `--wait-for-indexing`。
