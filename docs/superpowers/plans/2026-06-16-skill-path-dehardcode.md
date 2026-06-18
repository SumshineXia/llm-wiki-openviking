# Skill 脚本路径去硬编码 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将所有 active skill 文档和 README 中的固定安装路径 `~/.config/opencode/skills/...` 替换为基于当前 skill 目录的相对定位方式，使 skills 可安装在任意目录。

**Architecture:** `run.sh` 已通过 `BASH_SOURCE[0]` 实现自身相对定位，无需改动。需改动的是 SKILL.md 文档中的调用示例（改用 `<THIS_SKILL_DIR>` 占位符）、README 中的安装说明和调试命令（改用 `$OPENCODE_SKILLS_DIR` 变量），以及对应的测试断言（从"要求出现固定路径"反转为"禁止出现固定路径"）。

**Tech Stack:** Python pytest, Bash, Markdown

---

## 禁止事项

- 不要修改 `skills/wiki-*/scripts/run.sh`
- 不要修改 `skills/wiki-*/scripts/*.py`
- 不要改 CLI 参数名
- 不要改 JSON 字段名
- 不要改 OpenViking 配置加载逻辑
- 不要把 `<THIS_SKILL_DIR>` 写成任何真实绝对路径
- 不要重新引入 `~/.config/opencode/skills/...`
- 不要修改 `docs/superpowers/plans/**`
- 不要修改 `.opencode/workflow-runs/**` 历史运行产物
- 不要修改仓库外 `~/.opencode/workflows/**`
- 不要修改 `~/.config/llm-wiki-openviking/config.json` 相关说明（保留该路径不动）

## 统一约定

### SKILL.md 统一口径段落

每个 SKILL.md 的"执行方式"部分都使用以下统一口径替换旧文案：

```
必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：
```

第一段命令之后紧跟警告行：

```
不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。
```

### 需要修改的文件清单

| 文件 | 改动类型 |
|------|----------|
| `tests/skills/test_skill_docs_no_legacy_command.py` | 重写测试断言 |
| `tests/skills/test_readme_user_flow.py` | 删除/新增/修改测试断言 |
| `skills/wiki-graph/SKILL.md` | 替换执行方式 |
| `skills/wiki-lint/SKILL.md` | 替换执行方式 |
| `skills/wiki-upload-source/SKILL.md` | 替换执行方式 |
| `skills/wiki-bootstrap/SKILL.md` | 替换执行方式 |
| `skills/wiki-health/SKILL.md` | 替换执行方式 |
| `skills/wiki-ingest/SKILL.md` | 替换执行方式 |
| `skills/wiki-profile/SKILL.md` | 替换执行方式 |
| `skills/wiki-save/SKILL.md` | 替换执行方式 |
| `skills/wiki-query/SKILL.md` | 替换执行方式 + 跨 skill 调用路径 |
| `README.md` | 安装说明 + 调试命令 + FAQ |

---

## Task 1: 更新测试断言（TDD — 先让测试表达目标状态）

**Files:**
- Modify: `tests/skills/test_skill_docs_no_legacy_command.py` (全文重写)
- Modify: `tests/skills/test_readme_user_flow.py:16-19` (删除旧函数，新增替代函数)
- Modify: `tests/skills/test_readme_user_flow.py:34-37` (修改断言)
- Modify: `tests/skills/test_readme_user_flow.py:40-45` (修改断言)

- [ ] **Step 1: 重写 `tests/skills/test_skill_docs_no_legacy_command.py`**

将整个文件替换为以下内容：

```python
from pathlib import Path


def get_skill_names() -> list[str]:
  return sorted(path.name for path in Path("skills").glob("wiki-*") if (path / "SKILL.md").exists())


def test_skill_docs_do_not_use_legacy_project_scripts_command():
  for skill_name in get_skill_names():
    skill_doc_path = Path("skills") / skill_name / "SKILL.md"
    content = skill_doc_path.read_text(encoding="utf-8")
    assert "python3 -m scripts." not in content


def test_skill_docs_reference_run_sh_entrypoint():
  for skill_name in get_skill_names():
    skill_doc_path = Path("skills") / skill_name / "SKILL.md"
    content = skill_doc_path.read_text(encoding="utf-8")
    assert "run.sh" in content


def test_skill_docs_do_not_use_skills_relative_path_command():
  for skill_name in get_skill_names():
    skill_doc_path = Path("skills") / skill_name / "SKILL.md"
    content = skill_doc_path.read_text(encoding="utf-8")
    assert "./skills/" not in content


def test_skill_docs_do_not_reference_fixed_opencode_skill_install_path():
  for skill_name in get_skill_names():
    skill_doc_path = Path("skills") / skill_name / "SKILL.md"
    content = skill_doc_path.read_text(encoding="utf-8")
    assert "~/.config/opencode/skills/" not in content
    assert "$HOME/.config/opencode/skills/" not in content


def test_skill_docs_reference_current_skill_dir_placeholder():
  for skill_name in get_skill_names():
    skill_doc_path = Path("skills") / skill_name / "SKILL.md"
    content = skill_doc_path.read_text(encoding="utf-8")
    assert "<THIS_SKILL_DIR>" in content
    assert 'bash "<THIS_SKILL_DIR>/scripts/run.sh"' in content


def test_query_doc_references_sibling_wiki_save_without_fixed_root():
  content = (Path("skills") / "wiki-query" / "SKILL.md").read_text(encoding="utf-8")
  assert '../wiki-save/scripts/run.sh' in content
  assert "~/.config/opencode/skills/wiki-save" not in content
```

- [ ] **Step 2: 修改 `tests/skills/test_readme_user_flow.py` — 删除旧函数，新增替代函数**

删除 `testReadmeContainsSkillInstallPath` 函数（当前第 16-19 行）：

```python
def testReadmeContainsSkillInstallPath() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "~/.config/opencode/skills" in readmeText
```

在同一位置新增替代函数：

```python
def testReadmeContainsConfigurableSkillsDirPlaceholder() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "OPENCODE_SKILLS_DIR" in readmeText
  assert "~/.config/opencode/skills" not in readmeText
```

- [ ] **Step 3: 修改 `testReadmeContainsWikiHealthRunScriptPath` 断言**

将：

```python
def testReadmeContainsWikiHealthRunScriptPath() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "~/.config/opencode/skills/wiki-health/scripts/run.sh" in readmeText
```

改为：

```python
def testReadmeContainsWikiHealthRunScriptPath() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert '$OPENCODE_SKILLS_DIR/wiki-health/scripts/run.sh' in readmeText
```

- [ ] **Step 4: 修改 `test_readme_contains_off_repo_debug_command` 断言**

将：

```python
def test_readme_contains_off_repo_debug_command() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "cd /tmp" in readmeText
  assert "~/.config/opencode/skills/wiki-health/scripts/run.sh" in readmeText
  assert "--kb-name" in readmeText
```

改为：

```python
def test_readme_contains_off_repo_debug_command() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "cd /tmp" in readmeText
  assert '$OPENCODE_SKILLS_DIR/wiki-health/scripts/run.sh' in readmeText
  assert "--kb-name" in readmeText
```

- [ ] **Step 5: 运行测试，确认全部失败**

Run: `python3 -m pytest tests/skills/test_skill_docs_no_legacy_command.py tests/skills/test_readme_user_flow.py -q`

Expected: FAIL — 因为文档尚未更新，至少禁止旧路径、要求 `<THIS_SKILL_DIR>`、要求 `OPENCODE_SKILLS_DIR` 的相关断言会失败。

- [ ] **Step 6: Commit**

```bash
git add tests/skills/test_skill_docs_no_legacy_command.py tests/skills/test_readme_user_flow.py
git commit -m "test: 反转 skill 文档路径断言，要求去硬编码"
```

---

## Task 2: 更新简单 SKILL.md（wiki-graph, wiki-lint, wiki-upload-source）

这三个 skill 各只有一处命令块需要替换。

**Files:**
- Modify: `skills/wiki-graph/SKILL.md:23-31`
- Modify: `skills/wiki-lint/SKILL.md:23-31`
- Modify: `skills/wiki-upload-source/SKILL.md:23-35`

- [ ] **Step 1: 替换 `skills/wiki-graph/SKILL.md` 执行方式**

将以下旧内容：

```markdown
## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-graph/scripts/run.sh --kb-name <kb-name> --pretty
```

可选参数：`--config <path>`、`--profile <name>`。
```

替换为：

```markdown
## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" --kb-name <kb-name> --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

可选参数：`--config <path>`、`--profile <name>`。
```

- [ ] **Step 2: 替换 `skills/wiki-lint/SKILL.md` 执行方式**

将以下旧内容：

```markdown
## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-lint/scripts/run.sh --kb-name <kb-name> --pretty
```

可选参数：`--config <path>`、`--profile <name>`。
```

替换为：

```markdown
## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" --kb-name <kb-name> --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

可选参数：`--config <path>`、`--profile <name>`。
```

- [ ] **Step 3: 替换 `skills/wiki-upload-source/SKILL.md` 执行方式**

将以下旧内容：

```markdown
## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-upload-source/scripts/run.sh \
  --kb-name <kb-name> \
  --file <local-file-path> \
  --to raw/<target-file-name>.md \
  --pretty
```

可选参数：`--config <path>`、`--profile <name>`。
```

替换为：

```markdown
## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --file <local-file-path> \
  --to raw/<target-file-name>.md \
  --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

可选参数：`--config <path>`、`--profile <name>`。
```

- [ ] **Step 4: 运行 skill 文档测试，确认这 3 个 skill 的断言通过**

Run: `python3 -m pytest tests/skills/test_skill_docs_no_legacy_command.py -q`

Expected: 部分通过（wiki-graph, wiki-lint, wiki-upload-source 的断言满足），其余 skill 仍失败。

- [ ] **Step 5: Commit**

```bash
git add skills/wiki-graph/SKILL.md skills/wiki-lint/SKILL.md skills/wiki-upload-source/SKILL.md
git commit -m "docs: 去 wiki-graph/wiki-lint/wiki-upload-source 脚本路径硬编码"
```

---

## Task 3: 更新多命令 SKILL.md（wiki-bootstrap, wiki-health, wiki-ingest）

这三个 skill 各有多处命令块。

**Files:**
- Modify: `skills/wiki-bootstrap/SKILL.md:23-45`
- Modify: `skills/wiki-health/SKILL.md:24-44`
- Modify: `skills/wiki-ingest/SKILL.md:23-32` 和 `skills/wiki-ingest/SKILL.md:52-60`

- [ ] **Step 1: 替换 `skills/wiki-bootstrap/SKILL.md` 执行方式**

将以下旧内容（从 `## 执行方式` 到 dry-run 命令块结束）：

```markdown
## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-bootstrap/scripts/run.sh --kb-name <kb-name> --pretty
```

默认行为是基础目录和根页面创建请求会尽快返回，不等待 OpenViking 对页面完成语义处理。

显式等待索引完成：

```bash
bash ~/.config/opencode/skills/wiki-bootstrap/scripts/run.sh --kb-name <kb-name> --wait-for-indexing --pretty
```

可选参数：`--config <path>`、`--profile <name>`、`--wait-for-indexing`。

仅预览（不写入）：

```bash
bash ~/.config/opencode/skills/wiki-bootstrap/scripts/run.sh --kb-name <kb-name> --dry-run --pretty
```
```

替换为：

```markdown
## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" --kb-name <kb-name> --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

默认行为是基础目录和根页面创建请求会尽快返回，不等待 OpenViking 对页面完成语义处理。

显式等待索引完成：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" --kb-name <kb-name> --wait-for-indexing --pretty
```

可选参数：`--config <path>`、`--profile <name>`、`--wait-for-indexing`。

仅预览（不写入）：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" --kb-name <kb-name> --dry-run --pretty
```
```

- [ ] **Step 2: 替换 `skills/wiki-health/SKILL.md` 执行方式**

将以下旧内容（从 `## 执行方式` 到 repair-index 命令块结束）：

```markdown
## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-health/scripts/run.sh --kb-name <kb-name> --pretty
```

可选参数：`--config <path>`、`--profile <name>`。

当用户明确要求"修复 index / 重建 index / repair index"时，可运行：

```bash
bash ~/.config/opencode/skills/wiki-health/scripts/run.sh \
  --kb-name <kb-name> \
  --profile <profile> \
  --repair-index \
  --pretty
```
```

替换为：

```markdown
## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" --kb-name <kb-name> --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

可选参数：`--config <path>`、`--profile <name>`。

当用户明确要求"修复 index / 重建 index / repair index"时，可运行：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --profile <profile> \
  --repair-index \
  --pretty
```
```

- [ ] **Step 3: 替换 `skills/wiki-ingest/SKILL.md` — 第一处命令块**

将以下旧内容（从 `## 执行方式` 到第一个命令块结束）：

```markdown
## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-ingest/scripts/run.sh \
  --kb-name <kb-name> \
  --source-uri <full-raw-source-uri> \
  --pretty
```
```

替换为：

```markdown
## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --source-uri <full-raw-source-uri> \
  --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。
```

- [ ] **Step 4: 替换 `skills/wiki-ingest/SKILL.md` — dry-run 命令块**

将以下旧内容：

```markdown
仅预览（不写入）：

```bash
bash ~/.config/opencode/skills/wiki-ingest/scripts/run.sh \
  --kb-name <kb-name> \
  --source-uri <full-raw-source-uri> \
  --dry-run \
  --pretty
```
```

替换为：

```markdown
仅预览（不写入）：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --source-uri <full-raw-source-uri> \
  --dry-run \
  --pretty
```
```

- [ ] **Step 5: 运行 skill 文档测试**

Run: `python3 -m pytest tests/skills/test_skill_docs_no_legacy_command.py -q`

Expected: wiki-bootstrap, wiki-health, wiki-ingest 的断言也通过。wiki-profile, wiki-save, wiki-query 仍失败。

- [ ] **Step 6: Commit**

```bash
git add skills/wiki-bootstrap/SKILL.md skills/wiki-health/SKILL.md skills/wiki-ingest/SKILL.md
git commit -m "docs: 去 wiki-bootstrap/wiki-health/wiki-ingest 脚本路径硬编码"
```

---

## Task 4: 更新剩余 SKILL.md（wiki-profile, wiki-save, wiki-query）

**Files:**
- Modify: `skills/wiki-profile/SKILL.md:15-26`
- Modify: `skills/wiki-save/SKILL.md:22-40`
- Modify: `skills/wiki-query/SKILL.md:23-45` 和 `skills/wiki-query/SKILL.md:51`

- [ ] **Step 1: 替换 `skills/wiki-profile/SKILL.md` 执行方式**

将以下旧内容：

```markdown
## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh list --pretty
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh current --pretty
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh use <profile>
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh show <profile> --pretty
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh bind <profile> --dir .
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh unbind --dir .
```
```

替换为：

```markdown
## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" list --pretty
bash "<THIS_SKILL_DIR>/scripts/run.sh" current --pretty
bash "<THIS_SKILL_DIR>/scripts/run.sh" use <profile>
bash "<THIS_SKILL_DIR>/scripts/run.sh" show <profile> --pretty
bash "<THIS_SKILL_DIR>/scripts/run.sh" bind <profile> --dir .
bash "<THIS_SKILL_DIR>/scripts/run.sh" unbind --dir .
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。
```

- [ ] **Step 2: 替换 `skills/wiki-save/SKILL.md` 执行方式**

将以下旧内容（从 `## 执行方式` 到文件末尾）：

```markdown
## 执行方式

```bash
bash ~/.config/opencode/skills/wiki-save/scripts/run.sh \
  --payload-file <payload.json> \
  --pretty
```

或使用显式参数模式：

```bash
bash ~/.config/opencode/skills/wiki-save/scripts/run.sh \
  --kb-name <kb-name> \
  --answer-file <answer.md> \
  --question "<question>" \
  --title "<title>" \
  --used-page "viking://resources/<kb>/wiki/sources/x.md" \
  --pretty
```
```

替换为：

```markdown
## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --payload-file <payload.json> \
  --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

或使用显式参数模式：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --answer-file <answer.md> \
  --question "<question>" \
  --title "<title>" \
  --used-page "viking://resources/<kb>/wiki/sources/x.md" \
  --pretty
```
```

- [ ] **Step 3: 替换 `skills/wiki-query/SKILL.md` 执行方式**

将以下旧内容（从 `## 执行方式` 到 legacy save 命令块结束）：

```markdown
## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-query/scripts/run.sh \
  --kb-name <kb-name> \
  --question "<your question>" \
  --pretty
```

可选参数：`--config <path>`、`--profile <name>`。

兼容模式（legacy，仅兼容保留，不建议交互式场景使用）：

```bash
bash ~/.config/opencode/skills/wiki-query/scripts/run.sh \
  --kb-name <kb-name> \
  --question "<your question>" \
  --save \
  --slug <optional-slug> \
  --pretty
```
```

替换为：

```markdown
## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --question "<your question>" \
  --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

可选参数：`--config <path>`、`--profile <name>`。

兼容模式（legacy，仅兼容保留，不建议交互式场景使用）：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --question "<your question>" \
  --save \
  --slug <optional-slug> \
  --pretty
```
```

- [ ] **Step 4: 替换 `skills/wiki-query/SKILL.md` 跨 skill 调用路径**

将第 51 行旧内容：

```markdown
- 若用户同意保存，必须调用：`bash ~/.config/opencode/skills/wiki-save/scripts/run.sh --payload-file <save_payload_path>`
```

替换为：

```markdown
- 若用户同意保存，必须调用同级 `wiki-save` skill 的脚本。前提是 `wiki-query` 与 `wiki-save` 已作为 llm-wiki skills 同批安装在同一个 skills 父目录下。先将当前 `wiki-query` skill 根目录记为 `<THIS_SKILL_DIR>`，再调用：`bash "<THIS_SKILL_DIR>/../wiki-save/scripts/run.sh" --payload-file <save_payload_path> --pretty`
```

- [ ] **Step 5: 运行全部 skill 文档测试**

Run: `python3 -m pytest tests/skills/test_skill_docs_no_legacy_command.py -q`

Expected: PASS — 全部 7 个测试通过（9 个 skill 的路径断言 + wiki-query 跨 skill 断言全部满足）。

- [ ] **Step 6: Commit**

```bash
git add skills/wiki-profile/SKILL.md skills/wiki-save/SKILL.md skills/wiki-query/SKILL.md
git commit -m "docs: 去 wiki-profile/wiki-save/wiki-query 脚本路径硬编码"
```

---

## Task 5: 更新 README.md

README 有 4 个区域需要修改：安装说明（第 26-38 行）、profile 命令示例（第 75-79 行）、FAQ Q1（第 150 行）、调试命令（第 174-198 行）。

**Files:**
- Modify: `README.md:26-38`
- Modify: `README.md:75-79`
- Modify: `README.md:150`
- Modify: `README.md:174-198`

- [ ] **Step 1: 替换安装说明（第 26-38 行）**

将以下旧内容：

```markdown
把本仓库的 `skills/` 子目录复制到本机 `~/.config/opencode/skills/`（目录名保持不变）：

- `skills/wiki-bootstrap` -> `~/.config/opencode/skills/wiki-bootstrap`
- `skills/wiki-health` -> `~/.config/opencode/skills/wiki-health`
- `skills/wiki-ingest` -> `~/.config/opencode/skills/wiki-ingest`
- `skills/wiki-query` -> `~/.config/opencode/skills/wiki-query`
- `skills/wiki-upload-source` -> `~/.config/opencode/skills/wiki-upload-source`
- `skills/wiki-save` -> `~/.config/opencode/skills/wiki-save`
- `skills/wiki-lint` -> `~/.config/opencode/skills/wiki-lint`
- `skills/wiki-graph` -> `~/.config/opencode/skills/wiki-graph`
- `skills/wiki-profile` -> `~/.config/opencode/skills/wiki-profile`

如果你只想用部分能力，也可以只复制对应 skill。
```

替换为：

```markdown
把本仓库的 `skills/wiki-*` 目录复制到你的 OpenCode 实际加载 skills 的目录中。该目录可能是默认目录，也可能是你自定义的目录；llm-wiki 不依赖固定安装路径，只要求每个 skill 内部保持如下相对结构：

```text
wiki-xxx/
  SKILL.md
  scripts/
    run.sh
    xxx.py
```

建议同批安装以下 skills，尤其是 `wiki-query` 与 `wiki-save` 需要位于同一个 skills 父目录下，才能通过相对路径完成"query -> 确认 -> wiki-save"流程：

- `skills/wiki-bootstrap`
- `skills/wiki-health`
- `skills/wiki-ingest`
- `skills/wiki-query`
- `skills/wiki-upload-source`
- `skills/wiki-save`
- `skills/wiki-lint`
- `skills/wiki-graph`
- `skills/wiki-profile`

如果你只想用部分能力，也可以只复制对应 skill。
```

注意：`skills/wiki-upload-source` 和 `skills/wiki-save` 字样必须保留，否则 `testReadmeContainsWikiUploadSourceAndWikiSaveInstallEntries` 测试会失败。

- [ ] **Step 2: 替换 profile 命令示例（第 75-79 行）**

将以下旧内容：

```markdown
```bash
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh list --pretty
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh use <profile>
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh current --pretty
```
```

替换为：

```markdown
```bash
export OPENCODE_SKILLS_DIR="<你的 OpenCode skills 目录>"

bash "$OPENCODE_SKILLS_DIR/wiki-profile/scripts/run.sh" list --pretty
bash "$OPENCODE_SKILLS_DIR/wiki-profile/scripts/run.sh" use <profile>
bash "$OPENCODE_SKILLS_DIR/wiki-profile/scripts/run.sh" current --pretty
```
```

- [ ] **Step 3: 替换 FAQ Q1（第 150 行）**

将以下旧内容：

```markdown
不用。只要 `~/.config/opencode/skills` 和 `~/.config/llm-wiki-openviking/config.json` 配置正确，就可以在任意目录用 OpenCode。
```

替换为：

```markdown
不用。只要 llm-wiki skills 已安装到 OpenCode 实际加载的 skills 目录中，并且 `~/.config/llm-wiki-openviking/config.json` 配置正确，就可以在任意目录用 OpenCode。
```

注意：`~/.config/llm-wiki-openviking/config.json` 是 llm-wiki 配置文件默认路径，不属于这次 skill 安装路径问题，不要误删。

- [ ] **Step 4: 替换"脱离项目目录验证"段落（第 174-181 行）**

将以下旧内容：

```markdown
可以先离开项目目录，再手动执行 `wiki-health` 的脚本验证配置与调用链：

```bash
cd /tmp
bash ~/.config/opencode/skills/wiki-health/scripts/run.sh --kb-name team-a/project-x --pretty
```
```

替换为：

```markdown
可以先离开项目目录，再手动执行 `wiki-health` 的脚本验证配置与调用链：

```bash
cd /tmp
export OPENCODE_SKILLS_DIR="<你的 OpenCode skills 目录>"
bash "$OPENCODE_SKILLS_DIR/wiki-health/scripts/run.sh" --kb-name team-a/project-x --pretty
```
```

- [ ] **Step 5: 替换 debug 手动命令段落（第 185-198 行）**

将以下旧内容：

```markdown
当你怀疑 skill 调用链有问题时，可以手动执行每个 skill 目录里的 `scripts/run.sh` 做排查。

示例（按你的实际路径替换）：

```bash
bash ~/.config/opencode/skills/wiki-health/scripts/run.sh --kb-name my-kb
bash ~/.config/opencode/skills/wiki-ingest/scripts/run.sh --kb-name my-kb --source-uri raw/demo.md
bash ~/.config/opencode/skills/wiki-query/scripts/run.sh --kb-name my-kb --question "解释这个知识库的核心主题"
bash ~/.config/opencode/skills/wiki-save/scripts/run.sh --payload-file /tmp/wiki-query-save.json
bash ~/.config/opencode/skills/wiki-lint/scripts/run.sh --kb-name my-kb
bash ~/.config/opencode/skills/wiki-graph/scripts/run.sh --kb-name my-kb
```
```

替换为：

```markdown
当你怀疑 skill 调用链有问题时，可以手动执行每个 skill 目录里的 `scripts/run.sh` 做排查。

示例（按你的实际路径替换）：

```bash
export OPENCODE_SKILLS_DIR="<你的 OpenCode skills 目录>"

bash "$OPENCODE_SKILLS_DIR/wiki-health/scripts/run.sh" --kb-name my-kb
bash "$OPENCODE_SKILLS_DIR/wiki-ingest/scripts/run.sh" --kb-name my-kb --source-uri raw/demo.md
bash "$OPENCODE_SKILLS_DIR/wiki-query/scripts/run.sh" --kb-name my-kb --question "解释这个知识库的核心主题"
bash "$OPENCODE_SKILLS_DIR/wiki-save/scripts/run.sh" --payload-file /tmp/wiki-query-save.json
bash "$OPENCODE_SKILLS_DIR/wiki-lint/scripts/run.sh" --kb-name my-kb
bash "$OPENCODE_SKILLS_DIR/wiki-graph/scripts/run.sh" --kb-name my-kb
```
```

- [ ] **Step 6: 运行 README 测试**

Run: `python3 -m pytest tests/skills/test_readme_user_flow.py -q`

Expected: PASS — 全部 README 测试通过。

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs: 去 README 脚本路径硬编码，改用 OPENCODE_SKILLS_DIR 变量"
```

---

## Task 6: 全量验证与交付

- [ ] **Step 1: 运行全部相关测试**

Run: `python3 -m pytest tests/skills/test_run_sh_invocation.py tests/skills/test_skill_docs_no_legacy_command.py tests/skills/test_readme_user_flow.py -q`

Expected: 全部 PASS。

- [ ] **Step 2: Active surface grep 验证**

Run: `grep -rn '~/.config/opencode/skills' skills/ README.md tests/ .opencode/ --exclude-dir='workflow-runs' --exclude='*.log' --exclude-dir='node_modules' 2>/dev/null`

Expected: 无输出（零命中）。

Run: `grep -rn '\$HOME/.config/opencode/skills' skills/ README.md tests/ .opencode/ --exclude-dir='workflow-runs' --exclude='*.log' --exclude-dir='node_modules' 2>/dev/null`

Expected: 无输出（零命中）。

- [ ] **Step 3: 确认 run.sh 未被修改**

Run: `python3 -m pytest tests/skills/test_run_sh_invocation.py -q`

Expected: PASS — 全部 3 个测试通过，证明 run.sh 仍保持 BASH_SOURCE 相对定位。

- [ ] **Step 4: 确认未触碰禁止修改的文件**

Run: `git diff --name-only HEAD~5..HEAD`

如果没有严格按 5 个 commit 执行，则改用 `git diff --name-only` 和 `git diff --cached --name-only` 检查当前工作区，或与任务开始前的基准分支比较。

Expected: 输出的文件列表仅包含以下文件，不得出现 `run.sh`、`*.py`、`docs/superpowers/plans/**`、`.opencode/workflow-runs/**`：

```
README.md
skills/wiki-bootstrap/SKILL.md
skills/wiki-graph/SKILL.md
skills/wiki-health/SKILL.md
skills/wiki-ingest/SKILL.md
skills/wiki-lint/SKILL.md
skills/wiki-profile/SKILL.md
skills/wiki-query/SKILL.md
skills/wiki-save/SKILL.md
skills/wiki-upload-source/SKILL.md
tests/skills/test_readme_user_flow.py
tests/skills/test_skill_docs_no_legacy_command.py
```

- [ ] **Step 5: 准备交付说明**

交付说明中必须包含以下 follow-up 备注：

```text
本次已修复仓库内 active skill 文档、README 与测试中的固定 skills 安装路径。历史 workflow run 产物 `.opencode/workflow-runs/**` 以及仓库外 `~/.opencode/workflows/**` 如仍含 `$HOME/.config/opencode/skills/...`，属于既有运行记录或外部 workflow 定义，需要单独更新，未包含在本次仓库源码修复范围内。
```
