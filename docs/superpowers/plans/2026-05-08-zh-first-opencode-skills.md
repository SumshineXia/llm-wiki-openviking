# llm-wiki-openviking 中文优先改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `llm-wiki-openviking` 改造成中文优先知识库工具，保证中文自然触发、中文页面生成、中文可读输出，同时保持 CLI 参数、目录结构、JSON 字段与远端资源逻辑不变。

**Architecture:** 在不改架构前提下，按“触发层 -> 规则层 -> 生成层 -> 展示层 -> 校验层”最小改造。核心策略是中文默认写入（不做自动迁移），并对英文旧 heading 仅做防御性识别。通过新增/更新测试锁定中文输出与接口不变约束，避免回归。

**Tech Stack:** Python 3, pytest, Markdown skills docs, OpenViking OVFS scripts

---

### Task 1: 建立中文常量与 section 兼容工具（ingest/query 共用策略）

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py`
- Modify: `skills/wiki-query/scripts/query.py`
- Test: `tests/skills/test_zh_language_defaults.py` (new)

- [ ] **Step 1: 写失败测试，锁定 section 兼容规则（不迁移、避免重复）**

```python
# tests/skills/test_zh_language_defaults.py
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


def load_module(relative_parts: list[str], name: str):
  module_path = Path(__file__).resolve().parents[2].joinpath(*relative_parts)
  sys.path.insert(0, str(module_path.parent))
  spec = spec_from_file_location(name, module_path)
  assert spec is not None and spec.loader is not None
  module = module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_ingest_uses_existing_english_section_without_creating_chinese_duplicate() -> None:
  ingest = load_module(["skills", "wiki-ingest", "scripts", "ingest.py"], "wiki_ingest")
  index_text = "# Index\n\n## Sources\n"
  updated = ingest.update_index_text(
    index_text=index_text,
    source_slug="demo",
    source_title="演示资料",
    entity_pages=[],
    concept_pages=[],
  )
  assert "## Sources" in updated
  assert "## 资料来源" not in updated


def test_query_append_synthesis_uses_existing_english_section_without_duplicate() -> None:
  query = load_module(["skills", "wiki-query", "scripts", "query.py"], "wiki_query")
  updated = query.append_unique_bullet(
    "# Index\n\n## Syntheses\n",
    "## 综合结论",
    "- [[syntheses/a.md]] - A",
  )
  assert "## Syntheses" in updated
  assert "## 综合结论" not in updated
```

- [ ] **Step 2: 运行测试确认失败（当前无兼容函数）**

Run: `pytest tests/skills/test_zh_language_defaults.py -v`
Expected: FAIL，报 `AttributeError` 或断言失败（当前实现没有按 key 兼容 section）。

- [ ] **Step 3: 在 ingest.py 加入中文常量与兼容函数**

```python
# skills/wiki-ingest/scripts/ingest.py
INDEX_TITLE = "# 索引\n"
OVERVIEW_TITLE = "# 概览\n"
LOG_TITLE = "# 操作日志\n"

INDEX_SECTIONS = {
  "sources": "## 资料来源",
  "entities": "## 实体",
  "concepts": "## 概念",
  "syntheses": "## 综合结论",
}

LEGACY_INDEX_SECTIONS = {
  "sources": ["## Sources"],
  "entities": ["## Entities"],
  "concepts": ["## Concepts"],
  "syntheses": ["## Syntheses"],
}


def get_section_heading_by_key(index_text: str, section_key: str) -> tuple[str, str]:
  preferred_heading = INDEX_SECTIONS[section_key]
  if preferred_heading in index_text:
    return index_text, preferred_heading

  for legacy_heading in LEGACY_INDEX_SECTIONS.get(section_key, []):
    if legacy_heading in index_text:
      return index_text, legacy_heading

  normalized = index_text.rstrip()
  if normalized:
    normalized += "\n\n"
  normalized += preferred_heading + "\n\n"
  return normalized, preferred_heading
```

- [ ] **Step 4: 在 query.py 同步加入同名常量与兼容函数**

```python
# skills/wiki-query/scripts/query.py
INDEX_TITLE = "# 索引\n"
OVERVIEW_TITLE = "# 概览\n"
LOG_TITLE = "# 操作日志\n"

INDEX_SECTIONS = {
  "sources": "## 资料来源",
  "entities": "## 实体",
  "concepts": "## 概念",
  "syntheses": "## 综合结论",
}

LEGACY_INDEX_SECTIONS = {
  "sources": ["## Sources"],
  "entities": ["## Entities"],
  "concepts": ["## Concepts"],
  "syntheses": ["## Syntheses"],
}


def get_section_heading_by_key(index_text: str, section_key: str) -> tuple[str, str]:
  preferred_heading = INDEX_SECTIONS[section_key]
  if preferred_heading in index_text:
    return index_text, preferred_heading

  for legacy_heading in LEGACY_INDEX_SECTIONS.get(section_key, []):
    if legacy_heading in index_text:
      return index_text, legacy_heading

  normalized = index_text.rstrip()
  if normalized:
    normalized += "\n\n"
  normalized += preferred_heading + "\n\n"
  return normalized, preferred_heading
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/skills/test_zh_language_defaults.py -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add tests/skills/test_zh_language_defaults.py skills/wiki-ingest/scripts/ingest.py skills/wiki-query/scripts/query.py
git commit -m "test: add zh section compatibility guards for index headings"
```

### Task 2: 中文化 bootstrap 根页面模板（新库默认中文）

**Files:**
- Modify: `skills/wiki-bootstrap/scripts/bootstrap.py`
- Test: `tests/skills/test_bootstrap_cli.py`

- [ ] **Step 1: 写失败测试，锁定根页面中文模板**

```python
# tests/skills/test_bootstrap_cli.py
build_initial_file_content = module.build_initial_file_content


def test_build_initial_file_content_is_chinese_for_root_pages() -> None:
  index_text = build_initial_file_content("viking://resources/a/wiki/index.md")
  assert "# 索引" in index_text
  assert "## 资料来源" in index_text
  assert "## 实体" in index_text
  assert "## 概念" in index_text
  assert "## 综合结论" in index_text

  overview_text = build_initial_file_content("viking://resources/a/wiki/overview.md")
  assert overview_text.startswith("# 概览")

  log_text = build_initial_file_content("viking://resources/a/wiki/log.md")
  assert log_text.startswith("# 操作日志")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/skills/test_bootstrap_cli.py::test_build_initial_file_content_is_chinese_for_root_pages -v`
Expected: FAIL（当前返回 `# Index/#Overview/#Log`）。

- [ ] **Step 3: 修改 bootstrap 初始模板为中文结构**

```python
# skills/wiki-bootstrap/scripts/bootstrap.py
def build_initial_file_content(file_uri: str) -> str:
  if file_uri.endswith("wiki/index.md"):
    return (
      "# 索引\n\n"
      "- [概览](./overview.md)\n"
      "- [操作日志](./log.md)\n\n"
      "## 资料来源\n\n"
      "## 实体\n\n"
      "## 概念\n\n"
      "## 综合结论\n"
    )
  if file_uri.endswith("wiki/overview.md"):
    return "# 概览\n\n"
  if file_uri.endswith("wiki/log.md"):
    return "# 操作日志\n\n"
  return ""
```

- [ ] **Step 4: 运行文件级测试**

Run: `pytest tests/skills/test_bootstrap_cli.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add skills/wiki-bootstrap/scripts/bootstrap.py tests/skills/test_bootstrap_cli.py
git commit -m "feat: default bootstrap wiki root pages to chinese"
```

### Task 3: 中文化 schema 与语言规则（ingest/query 双份）

**Files:**
- Modify: `skills/wiki-ingest/references/wiki_schema.md`
- Modify: `skills/wiki-query/references/wiki_schema.md`
- Test: `tests/skills/test_ingest_schema_loading.py`

- [ ] **Step 1: 写失败测试，锁定 schema 中文语言规则存在**

```python
# tests/skills/test_ingest_schema_loading.py
def test_ingest_schema_contains_zh_language_rules() -> None:
  module = load_ingest_module()
  schema = module.read_local_schema()
  assert "简体中文" in schema
  assert "JSON 字段名保持英文" in schema
  assert "文件路径和目录名保持英文" in schema
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/skills/test_ingest_schema_loading.py::test_ingest_schema_contains_zh_language_rules -v`
Expected: FAIL（当前 schema 英文）。

- [ ] **Step 3: 重写 ingest wiki_schema.md 为中文结构 + 不翻译约束**

```md
# Wiki 结构规范

## 语言规则
- 默认使用简体中文生成页面标题和正文。
- 除必要术语、代码标识符、API 名、库名、命令参数外，不使用英文句子。
- JSON 字段名保持英文，不翻译。
- 文件路径和目录名保持英文，不翻译。
```

- [ ] **Step 4: 同步重写 query wiki_schema.md（保持字段结构一致）**

```md
# Wiki 结构规范

## 页面类型
- 资料来源页面
- 实体页面
- 概念页面
- 综合结论页面
```

- [ ] **Step 5: 运行 schema 相关测试**

Run: `pytest tests/skills/test_ingest_schema_loading.py -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add skills/wiki-ingest/references/wiki_schema.md skills/wiki-query/references/wiki_schema.md tests/skills/test_ingest_schema_loading.py
git commit -m "docs: localize wiki schema and add zh language constraints"
```

### Task 4: 中文化 ingest prompt/system message 与中文默认日志

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py`
- Test: `tests/skills/test_zh_language_defaults.py`

- [ ] **Step 1: 写失败测试，锁定 ingest prompt 中文硬约束**

```python
# tests/skills/test_zh_language_defaults.py
def test_ingest_prompt_requires_simplified_chinese() -> None:
  ingest = load_module(["skills", "wiki-ingest", "scripts", "ingest.py"], "wiki_ingest_prompt")
  prompt = ingest.build_llm_prompt(
    schema_text="schema",
    source_uri="viking://resources/demo/raw/a.md",
    source_text="english source",
    context={
      "index_text": "# 索引\n",
      "overview_text": "# 概览\n",
      "log_text": "# 操作日志\n",
      "entity_pages": [],
      "concept_pages": [],
      "source_pages": [],
    },
    source_slug="a",
  )
  assert "简体中文" in prompt
  assert "标题必须使用简体中文" in prompt
  assert "正文必须使用简体中文" in prompt
  assert "JSON 字段名必须保持英文" in prompt
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/skills/test_zh_language_defaults.py::test_ingest_prompt_requires_simplified_chinese -v`
Expected: FAIL。

- [ ] **Step 3: 修改 ingest prompt 与 system message 为中文约束**

```python
# skills/wiki-ingest/scripts/ingest.py
"role": "system",
"content": "你是一个严谨的中文知识库构建助手。只输出合法 JSON，不要输出额外解释。",
```

```python
# skills/wiki-ingest/scripts/ingest.py
return f"""
你正在为一个远端 OpenViking 知识库生成 wiki 内容。

语言要求：
- 所有 markdown 页面标题必须使用简体中文。
- 所有 markdown 正文必须使用简体中文。
- 必要的技术术语、代码名、API 名、路径、命令、库名可以保留英文。
- 如果原始资料是英文，不要直接生成英文 wiki 页面，要提炼为中文内容。
- JSON 字段名必须保持英文，不要翻译。
...省略其余原结构...
""".strip()
```

- [ ] **Step 4: 把 ingest 默认日志 fallback 改为中文**

```python
# skills/wiki-ingest/scripts/ingest.py
new_log_text = append_log_entry(
  context["log_text"],
  log_note or f"已将资料 {source_slug} 整理为 wiki/sources/{source_slug}.md",
)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/skills/test_zh_language_defaults.py -k ingest -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add skills/wiki-ingest/scripts/ingest.py tests/skills/test_zh_language_defaults.py
git commit -m "feat: enforce chinese output in ingest prompt and log fallback"
```

### Task 5: 中文化 ingest index/overview 写入与 section key 路由

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py`
- Test: `tests/skills/test_zh_language_defaults.py`

- [ ] **Step 1: 写失败测试，锁定 overview 标题为“最近更新”**

```python
def test_append_overview_note_uses_chinese_recent_section() -> None:
  ingest = load_module(["skills", "wiki-ingest", "scripts", "ingest.py"], "wiki_ingest_overview")
  updated = ingest.append_overview_note("# 概览\n", "新增了一条摘要", "来源A")
  assert "## 最近更新" in updated
  assert "## Recent Additions" not in updated
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/skills/test_zh_language_defaults.py::test_append_overview_note_uses_chinese_recent_section -v`
Expected: FAIL。

- [ ] **Step 3: 修改 update_index_text 使用 section key + 兼容 heading**

```python
def update_index_text(...):
  updated = index_text
  updated, sources_heading = get_section_heading_by_key(updated, "sources")
  updated, entities_heading = get_section_heading_by_key(updated, "entities")
  updated, concepts_heading = get_section_heading_by_key(updated, "concepts")
  updated, _ = get_section_heading_by_key(updated, "syntheses")

  source_bullet = f"- [[sources/{source_slug}.md]] - {source_title}"
  updated = append_unique_bullet(updated, sources_heading, source_bullet)
  ...
```

- [ ] **Step 4: 修改 append_overview_note section 为中文**

```python
section_heading = "## 最近更新"
```

- [ ] **Step 5: 运行 ingest 相关中文测试**

Run: `pytest tests/skills/test_zh_language_defaults.py -k "ingest or overview" -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add skills/wiki-ingest/scripts/ingest.py tests/skills/test_zh_language_defaults.py
git commit -m "feat: localize ingest index and overview sections with legacy heading compatibility"
```

### Task 6: 中文化 query prompt/system/template/index/log，并增强中文分词

**Files:**
- Modify: `skills/wiki-query/scripts/query.py`
- Modify: `tests/skills/test_query_args.py`
- Test: `tests/skills/test_zh_language_defaults.py` (new/updated)

- [ ] **Step 1: 写失败测试，锁定 query prompt 中文规则与 synthesis 模板中文小节**

```python
def test_query_prompt_requires_chinese_answering() -> None:
  query = load_module(["skills", "wiki-query", "scripts", "query.py"], "wiki_query_prompt")
  prompt = query.build_llm_prompt("schema", "这个知识库讲了什么", "# 概览", [])
  assert "默认用简体中文回答" in prompt
  assert "上下文不足，用中文说明缺失了什么" in prompt


def test_render_synthesis_markdown_uses_chinese_sections() -> None:
  query = load_module(["skills", "wiki-query", "scripts", "query.py"], "wiki_query_template")
  text = query.render_synthesis_markdown("标题", "问题", "回答", ["viking://resources/a/wiki/index.md"])
  assert "## 问题" in text
  assert "## 回答" in text
  assert "## 使用的页面" in text
```

- [ ] **Step 2: 写失败测试，锁定中文分词至少产出 2-gram**

```python
def test_tokenize_generates_chinese_bigrams() -> None:
  query = load_module(["skills", "wiki-query", "scripts", "query.py"], "wiki_query_tokenize")
  tokens = query.tokenize("知识库主要目标是什么")
  assert "知识" in tokens
  assert "主要" in tokens
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/skills/test_zh_language_defaults.py -k "query or tokenize" -v`
Expected: FAIL。

- [ ] **Step 4: 修改 query prompt 与 system message 为中文硬约束**

```python
"role": "system",
"content": "你是一个严谨的中文知识库问答助手。只输出合法 JSON，不要输出额外解释。",
```

```python
Rules:
- 默认用简体中文回答。
- 不要因为资料页面中有英文就直接输出英文答案。
- 技术术语、代码、路径、命令、API 名可以保留英文。
- 如果知识库上下文不足，用中文说明缺失了什么。
- JSON 字段名保持英文。
```

- [ ] **Step 5: 修改 synthesis 模板、index section、日志 fallback 为中文**

```python
def render_synthesis_markdown(...):
  used_section = "\n".join(f"- {uri}" for uri in used_pages) if used_pages else "- 无"
  return f"""# {title}

## 问题

{question}

## 回答

{answer_markdown}

## 使用的页面

{used_section}
"""
```

```python
index_text, synth_heading = get_section_heading_by_key(index_text, "syntheses")
new_index_text = append_unique_bullet(index_text, synth_heading, bullet)
new_log_text = append_log_entry(log_text, f"已保存综合结论 {synthesis_slug} 到 wiki/syntheses/{synthesis_slug}.md")
```

- [ ] **Step 6: 修改 tokenize 为英文词 + 中文原串 + 中文 2-gram + 中文停用词**

```python
CHINESE_STOPWORDS = {
  "这个", "那个", "什么", "如何", "怎么", "请问", "一下", "里面", "相关", "主要",
}


def tokenize(text: str) -> Set[str]:
  normalized = text.lower()
  tokens: Set[str] = set(re.findall(r"[a-z0-9_]+", normalized))

  for span in re.findall(r"[\u4e00-\u9fff]+", normalized):
    if len(span) >= 2:
      tokens.add(span)
      for i in range(0, len(span) - 1):
        tokens.add(span[i:i + 2])

  return {
    token for token in tokens
    if len(token) >= 2 and token not in STOPWORDS and token not in CHINESE_STOPWORDS
  }
```

- [ ] **Step 7: 运行 query 相关测试**

Run: `pytest tests/skills/test_query_args.py tests/skills/test_zh_language_defaults.py -k "query or tokenize or synthesis" -v`
Expected: PASS。

- [ ] **Step 8: 提交**

```bash
git add skills/wiki-query/scripts/query.py tests/skills/test_query_args.py tests/skills/test_zh_language_defaults.py
git commit -m "feat: localize query outputs and improve chinese tokenization"
```

### Task 7: 中文化 graph HTML 界面（仅 UI 文案，不改 graph.json 字段）

**Files:**
- Modify: `skills/wiki-graph/scripts/graph.py`
- Test: `tests/skills/test_graph_output.py`
- Test: `tests/skills/test_zh_language_defaults.py` (new/updated)

- [ ] **Step 1: 写失败测试，锁定 graph html 中文 UI 文案**

```python
def test_graph_html_uses_chinese_labels() -> None:
  graph = load_module(["skills", "wiki-graph", "scripts", "graph.py"], "wiki_graph")
  html = graph.render_graph_html({"nodes": [], "edges": []}, "viking://resources/a/")
  assert '<html lang="zh-CN">' in html
  assert "知识图谱" in html
  assert "搜索页面标题或路径" in html
  assert "未选择页面" in html
  assert "入链" in html
  assert "出链" in html
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/skills/test_zh_language_defaults.py::test_graph_html_uses_chinese_labels -v`
Expected: FAIL。

- [ ] **Step 3: 修改 graph.html 模板文案为中文，并保留 category 原值**

```python
# skills/wiki-graph/scripts/graph.py
<html lang="zh-CN">
<title>知识图谱</title>
<h1>知识图谱</h1>
placeholder="搜索页面标题或路径..."
...
<h2>未选择页面</h2>
...
<strong>入链:</strong>
<strong>出链:</strong>
```

```python
// 分类显示文案映射（显示中文，数据值不变）
const categoryLabelMap = {
  sources: "资料来源",
  entities: "实体",
  concepts: "概念",
  syntheses: "综合结论",
  root: "根页面",
};
```

- [ ] **Step 4: 运行 graph 相关测试**

Run: `pytest tests/skills/test_graph_output.py tests/skills/test_zh_language_defaults.py -k graph -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add skills/wiki-graph/scripts/graph.py tests/skills/test_graph_output.py tests/skills/test_zh_language_defaults.py
git commit -m "feat: localize wiki graph html ui labels to chinese"
```

### Task 8: 中文化 health/lint 可读消息（保持 JSON key 不变）

**Files:**
- Modify: `skills/wiki-health/scripts/health.py`
- Modify: `skills/wiki-lint/scripts/lint.py`
- Test: `tests/skills/test_health_checks.py`
- Test: `tests/skills/test_zh_language_defaults.py` (new/updated)

- [ ] **Step 1: 写失败测试，锁定 JSON key 不变 + value 中文**

```python
def test_health_lint_json_keys_remain_english() -> None:
  # 静态约束：函数输出 dict 必须继续使用 status/warnings/errors/details
  # 这里通过源码关键字约束，防止误改 key
  health = load_module(["skills", "wiki-health", "scripts", "health.py"], "wiki_health")
  lint = load_module(["skills", "wiki-lint", "scripts", "lint.py"], "wiki_lint")
  health_source = Path(health.__file__).read_text(encoding="utf-8")
  lint_source = Path(lint.__file__).read_text(encoding="utf-8")
  assert '"warnings"' in health_source and '"errors"' in health_source and '"details"' in health_source
  assert '"warnings"' in lint_source and '"errors"' in lint_source and '"details"' in lint_source
```

- [ ] **Step 2: 运行测试确认失败（当前无中文 value 断言可后续补）**

Run: `pytest tests/skills/test_zh_language_defaults.py::test_health_lint_json_keys_remain_english -v`
Expected: 先 PASS（key 存在），随后补充 value 中文断言后应 FAIL。

- [ ] **Step 3: 增加 value 中文断言并触发失败**

```python
def test_health_and_lint_human_messages_use_chinese() -> None:
  health_path = Path(__file__).resolve().parents[2] / "skills" / "wiki-health" / "scripts" / "health.py"
  lint_path = Path(__file__).resolve().parents[2] / "skills" / "wiki-lint" / "scripts" / "lint.py"
  assert "缺少必要目录" in health_path.read_text(encoding="utf-8")
  assert "内部链接失效" in lint_path.read_text(encoding="utf-8")
```

- [ ] **Step 4: 修改 health/lint 的可读文案为中文，不修改 key 名**

```python
# skills/wiki-health/scripts/health.py
errors.append(f"缺少必要目录: {len(missing_dirs)}")
errors.append(f"缺少必要根页面: {len(missing_files)}")
warnings.append("wiki/sources/ 下还没有资料来源页面")
```

```python
# skills/wiki-lint/scripts/lint.py
errors.append(f"内部链接失效: {len(broken_links)}")
warnings.append(f"孤儿页面: {len(orphan_pages)}")
warnings.append(f"空页面或近似空页面: {len(stub_pages)}")
```

- [ ] **Step 5: 运行 health/lint 测试**

Run: `pytest tests/skills/test_health_checks.py tests/skills/test_lint_orphan_detection.py tests/skills/test_lint_link_extraction.py tests/skills/test_zh_language_defaults.py -k "health or lint" -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add skills/wiki-health/scripts/health.py skills/wiki-lint/scripts/lint.py tests/skills/test_health_checks.py tests/skills/test_zh_language_defaults.py
git commit -m "feat: localize health and lint messages while preserving json keys"
```

### Task 9: 中文化 SKILL.md 触发描述与 README 用户流

**Files:**
- Modify: `skills/wiki-bootstrap/SKILL.md`
- Modify: `skills/wiki-upload-source/SKILL.md`
- Modify: `skills/wiki-ingest/SKILL.md`
- Modify: `skills/wiki-query/SKILL.md`
- Modify: `skills/wiki-health/SKILL.md`
- Modify: `skills/wiki-lint/SKILL.md`
- Modify: `skills/wiki-graph/SKILL.md`
- Modify: `README.md`
- Test: `tests/skills/test_readme_user_flow.py`
- Test: `tests/skills/test_skill_docs_no_legacy_command.py`

- [ ] **Step 1: 写失败测试，锁定 README 中文优先说明存在**

```python
# tests/skills/test_readme_user_flow.py
def test_readme_mentions_chinese_first_generation() -> None:
  readme_path = Path(__file__).resolve().parents[2] / "README.md"
  text = readme_path.read_text(encoding="utf-8")
  assert "页面标题和正文默认生成中文" in text
  assert "技术术语、路径、命令、API 名保留英文" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/skills/test_readme_user_flow.py::test_readme_mentions_chinese_first_generation -v`
Expected: FAIL。

- [ ] **Step 3: 修改 7 个 SKILL.md 的 description 与触发示例为中文优先**

```yaml
# 示例：skills/wiki-ingest/SKILL.md
description: 当用户要求把 raw/ 下原始资料整理成中文 wiki 页面时使用。适用于“把这个资料写入知识库”“对 raw/demo.md 执行 ingest”“生成资料来源/实体/概念页面”“更新索引、概览、操作日志”等请求。
```

```yaml
# 示例：skills/wiki-query/SKILL.md
description: 当用户要求基于远端知识库进行中文问答时使用。适用于“基于 my-kb 回答这个问题”“查一下知识库里怎么说”“把答案保存为综合结论”等请求。
```

- [ ] **Step 4: 修改 README 增加中文优先规则与中文自然语言示例**

```md
## 中文优先约定
- 页面标题和正文默认生成中文。
- 技术术语、代码、路径、命令参数、API 名可保留英文。
- 保持 CLI 参数、目录结构、JSON 字段名不变。

## 常见自然语言用法
- 把这个资料整理进知识库。
- 查一下知识库里有没有讲这个。
- 把这个回答沉淀成综合结论。
- 检查一下知识库有没有断链或孤儿页。
```

- [ ] **Step 5: 运行文档相关测试**

Run: `pytest tests/skills/test_readme_user_flow.py tests/skills/test_skill_docs_no_legacy_command.py -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add README.md skills/wiki-bootstrap/SKILL.md skills/wiki-upload-source/SKILL.md skills/wiki-ingest/SKILL.md skills/wiki-query/SKILL.md skills/wiki-health/SKILL.md skills/wiki-lint/SKILL.md skills/wiki-graph/SKILL.md tests/skills/test_readme_user_flow.py
git commit -m "docs: make skill triggers and readme chinese-first"
```

### Task 10: 全量回归与验收

**Files:**
- Modify: `tests/skills/test_zh_language_defaults.py` (如有补充)
- Test: `tests/skills/*.py`

- [ ] **Step 1: 运行新增中文化核心测试集**

Run: `pytest tests/skills/test_zh_language_defaults.py -v`
Expected: PASS。

- [ ] **Step 2: 运行 skills 全量测试**

Run: `pytest tests/skills -q`
Expected: 全部 PASS。

- [ ] **Step 3: 运行仓库全量测试**

Run: `pytest -q`
Expected: 全部 PASS。

- [ ] **Step 4: 手工验收关键点（命令级）**

Run:
```bash
bash ~/.config/opencode/skills/wiki-bootstrap/scripts/run.sh --kb-name my-kb --dry-run --pretty
bash ~/.config/opencode/skills/wiki-ingest/scripts/run.sh --kb-name my-kb --source-uri viking://resources/my-kb/raw/demo.md --dry-run --pretty
bash ~/.config/opencode/skills/wiki-query/scripts/run.sh --kb-name my-kb --question "这个知识库主要讲了什么？" --pretty
bash ~/.config/opencode/skills/wiki-graph/scripts/run.sh --kb-name my-kb --dry-run --pretty
bash ~/.config/opencode/skills/wiki-health/scripts/run.sh --kb-name my-kb --pretty
bash ~/.config/opencode/skills/wiki-lint/scripts/run.sh --kb-name my-kb --pretty
```

Expected:
- 根页面标题与 section 中文。
- ingest/query prompt 与产出中文优先。
- synthesis 模板中文小节。
- graph HTML 界面中文。
- health/lint 结果中的 key 仍为英文，value 为中文。

- [ ] **Step 5: 最终提交**

```bash
git add tests/skills/test_zh_language_defaults.py
git commit -m "test: add end-to-end chinese-first acceptance checks"
```

---

## Scope Guardrails（严格边界）

- 不做自动迁移英文 index heading。
- 不新增 `wiki-migrate-zh` skill（后续独立需求再做）。
- 不改 CLI 参数名。
- 不改远端目录结构（`raw/`, `wiki/sources/`, `wiki/entities/`, `wiki/concepts/`, `wiki/syntheses/`）。
- 不改 JSON key（`status`, `warnings`, `errors`, `details`, `answer_markdown` 等）。
- 不破坏 OVFS 远端读写逻辑。

## Spec Coverage Self-Review

- 中文自然语言触发：Task 9。
- 页面标题中文：Task 2 + Task 4 + Task 6。
- 页面正文中文：Task 3 + Task 4 + Task 6。
- 非必要英文限制：Task 3 + Task 4 + Task 6。
- 参数/目录/字段不变：Task 8 + Guardrails。
- 不破坏远端逻辑：所有任务仅改文案、prompt、section 选择与分词，不改 OVFS 协议流程。

## Placeholder Scan Self-Review

- 无 TBD/TODO。
- 每个任务都包含具体文件、测试命令、提交命令。
- 每个代码步骤都给出可落地片段。

## Type/接口一致性 Self-Review

- `get_section_heading_by_key` 在 ingest/query 使用同签名。
- `tokenize` 仍返回 `Set[str]`。
- `result` JSON key 未改名。
- `build_synthesis_target`/`render_synthesis_markdown` 对外调用签名不变。
