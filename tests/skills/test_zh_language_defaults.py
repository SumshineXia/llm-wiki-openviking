from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


repoRoot = Path(__file__).resolve().parents[2]

ingestScriptsDir = repoRoot / "skills" / "wiki-ingest" / "scripts"
ingestModulePath = ingestScriptsDir / "ingest.py"
sys.path.insert(0, str(ingestScriptsDir))
ingestSpec = spec_from_file_location("wiki_ingest_script", ingestModulePath)
if ingestSpec is None or ingestSpec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-ingest/scripts/ingest.py")
ingestModule = module_from_spec(ingestSpec)
ingestSpec.loader.exec_module(ingestModule)

queryScriptsDir = repoRoot / "skills" / "wiki-query" / "scripts"
queryModulePath = queryScriptsDir / "query.py"
sys.path.insert(0, str(queryScriptsDir))
querySpec = spec_from_file_location("wiki_query_script", queryModulePath)
if querySpec is None or querySpec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-query/scripts/query.py")
queryModule = module_from_spec(querySpec)
querySpec.loader.exec_module(queryModule)

graphScriptsDir = repoRoot / "skills" / "wiki-graph" / "scripts"
graphModulePath = graphScriptsDir / "graph.py"
sys.path.insert(0, str(graphScriptsDir))
graphSpec = spec_from_file_location("wiki_graph_script", graphModulePath)
if graphSpec is None or graphSpec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-graph/scripts/graph.py")
graphModule = module_from_spec(graphSpec)
graphSpec.loader.exec_module(graphModule)

healthScriptsDir = repoRoot / "skills" / "wiki-health" / "scripts"
healthModulePath = healthScriptsDir / "health.py"
sys.path.insert(0, str(healthScriptsDir))
healthSpec = spec_from_file_location("wiki_health_script", healthModulePath)
if healthSpec is None or healthSpec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-health/scripts/health.py")
healthModule = module_from_spec(healthSpec)
healthSpec.loader.exec_module(healthModule)

lintScriptsDir = repoRoot / "skills" / "wiki-lint" / "scripts"
lintModulePath = lintScriptsDir / "lint.py"
sys.path.insert(0, str(lintScriptsDir))
lintSpec = spec_from_file_location("wiki_lint_script", lintModulePath)
if lintSpec is None or lintSpec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-lint/scripts/lint.py")
lintModule = module_from_spec(lintSpec)
lintSpec.loader.exec_module(lintModule)


def test_update_index_text_reuses_english_sources_section() -> None:
  indexText = "# Index\n\n## Sources\n"

  updated = ingestModule.update_index_text(
    indexText,
    "my-source",
    "My Source",
    [],
    [],
  )

  assert "## Sources" in updated
  assert "## 资料来源" not in updated
  assert updated.count("## Sources") == 1


def test_ingest_get_section_heading_by_key_prefers_legacy_heading_when_present() -> None:
  indexText = "# Index\n\n## Sources\n"
  heading, canonicalHeading = ingestModule.get_section_heading_by_key(indexText, "sources")

  assert heading == "## Sources"
  assert canonicalHeading == "## 资料来源"


def test_update_index_text_reuses_existing_legacy_headings_for_all_sections() -> None:
  indexText = "# Index\n\n## Sources\n\n## Entities\n\n## Concepts\n\n## Syntheses\n"

  updated = ingestModule.update_index_text(
    indexText,
    "my-source",
    "My Source",
    [{"slug": "alice", "title": "Alice"}],
    [{"slug": "ml", "title": "Machine Learning"}],
  )

  assert updated.count("## Sources") == 1
  assert updated.count("## Entities") == 1
  assert updated.count("## Concepts") == 1
  assert updated.count("## Syntheses") == 1
  assert "## 资料来源" not in updated
  assert "## 实体" not in updated
  assert "## 概念" not in updated
  assert "## 综合结论" not in updated


def test_append_unique_bullet_reuses_english_syntheses_section() -> None:
  indexText = "# Index\n\n## Syntheses\n"
  bullet = "- [[syntheses/a.md]] - answer"

  updated = queryModule.append_unique_bullet(indexText, "syntheses", bullet)

  assert "## Syntheses" in updated
  assert "## 综合结论" not in updated
  assert updated.count("## Syntheses") == 1
  assert bullet in updated


def test_query_get_section_heading_by_key_prefers_legacy_heading_when_present() -> None:
  indexText = "# Index\n\n## Syntheses\n"
  heading, canonicalHeading = queryModule.get_section_heading_by_key(indexText, "syntheses")

  assert heading == "## Syntheses"
  assert canonicalHeading == "## 综合结论"


def test_ingest_build_llm_prompt_enforces_simplified_chinese_rules() -> None:
  context = {
    "index_text": "# 索引\n",
    "overview_text": "# 概览\n",
    "log_text": "# 操作日志\n",
    "index_excerpt": "# 索引\n",
    "overview_excerpt": "# 概览\n",
    "index_truncated_for_prompt": False,
    "overview_truncated_for_prompt": False,
    "entity_pages": [],
    "concept_pages": [],
    "source_pages": [],
  }

  prompt = ingestModule.build_llm_prompt(
    schema_text="# schema",
    source_uri="viking://resources/demo/raw/source.md",
    source_text="raw text",
    context=context,
    source_slug="source",
  )

  assert "简体中文" in prompt
  assert "标题必须使用简体中文" in prompt
  assert "正文必须使用简体中文" in prompt
  assert "原始资料为英文时，不直接生成英文 wiki 页面，应提炼为中文内容" in prompt
  assert "必要技术术语、代码名、API名、路径、命令、库名可保留英文" in prompt
  assert "JSON 字段名必须保持英文" in prompt


def test_append_overview_note_uses_chinese_recent_updates_section() -> None:
  overviewText = "# 概览\n"

  updated = ingestModule.append_overview_note(overviewText, "新增了实体与概念页面", "示例来源")

  assert "## 最近更新" in updated
  assert "## Recent Additions" not in updated


def test_append_overview_note_is_idempotent_for_same_source_and_note() -> None:
  overviewText = "# 概览\n"

  first = ingestModule.append_overview_note(overviewText, "新增了实体与概念页面", "示例来源")
  second = ingestModule.append_overview_note(first, "新增了实体与概念页面", "示例来源")

  assert second == first
  assert second.count("## 最近更新") == 1


def test_query_build_llm_prompt_enforces_simplified_chinese_defaults() -> None:
  prompt = queryModule.build_llm_prompt(
    schema_text="# schema",
    question="这份知识库主要讲了什么？",
    overview_text="# 概览\n",
    selected_pages=[],
  )

  assert "默认用简体中文回答" in prompt
  assert "上下文不足，用中文说明缺失了什么" in prompt


def test_query_log_title_uses_operation_log_heading() -> None:
  assert queryModule.LOG_TITLE == "# 操作日志\n"


def test_render_synthesis_markdown_uses_chinese_sections() -> None:
  markdown = queryModule.render_synthesis_markdown(
    title="测试标题",
    question="问题示例",
    answer_markdown="回答示例",
    used_pages=["viking://resources/demo/wiki/sources/a.md"],
  )

  assert "## 问题" in markdown
  assert "## 回答" in markdown
  assert "## 使用的页面" in markdown
  assert "## Query" not in markdown
  assert "## Answer" not in markdown
  assert "## Used Pages" not in markdown


def test_tokenize_includes_chinese_bigrams() -> None:
  tokens = queryModule.tokenize("这个知识库主要介绍检索增强生成")

  assert "知识" in tokens
  assert "主要" in tokens


def test_graph_ui_category_labels_use_chinese_display_mapping() -> None:
  html = graphModule.render_graph_html(
    {
      "nodes": [
        {
          "id": "n1",
          "uri": "viking://resources/demo/wiki/sources/a.md",
          "rel_path": "sources/a.md",
          "label": "a",
          "category": "sources",
          "is_root": False,
        }
      ],
      "edges": [],
    },
    "viking://resources/demo/",
  )

  assert "sources = 资料来源" in html
  assert "entities = 实体" in html
  assert "concepts = 概念" in html
  assert "syntheses = 综合结论" in html
  assert "root = 根页面" in html


class HealthFakeClient:
  def __init__(self, texts: dict[str, str], stats: dict[str, dict[str, bool]]) -> None:
    self.texts = texts
    self.stats = stats

  def read_text(self, uri: str) -> str:
    return self.texts.get(uri, "")

  def stat(self, uri: str) -> dict[str, bool]:
    if uri not in self.stats:
      raise healthModule.OVFSHTTPError("404 not found")
    return self.stats[uri]

  def ls(self, uri: str, recursive: bool = False) -> list[str]:
    return []


def test_health_messages_use_chinese_values_and_keep_json_keys_english() -> None:
  kbRoot = "viking://resources/my-kb/"
  report = healthModule.build_report(HealthFakeClient(texts={}, stats={}), kbRoot)

  assert "status" in report
  assert "warnings" in report
  assert "errors" in report
  assert "details" in report
  assert any("缺少必要目录" in message for message in report["errors"])


class LintFakeClient:
  def __init__(self, texts: dict[str, str], stats: dict[str, dict[str, bool]], lsItems: list[object]) -> None:
    self.texts = texts
    self.stats = stats
    self.lsItems = lsItems

  def read_text(self, uri: str) -> str:
    return self.texts.get(uri, "")

  def stat(self, uri: str) -> dict[str, bool]:
    if uri not in self.stats:
      raise lintModule.OVFSHTTPError("404 not found")
    return self.stats[uri]

  def ls(self, uri: str, recursive: bool = False) -> list[object]:
    return self.lsItems


def test_lint_messages_use_chinese_values_and_keep_json_keys_english() -> None:
  kbRoot = "viking://resources/my-kb/"
  sourceUri = kbRoot + "wiki/sources/a.md"
  lsItems = [sourceUri]
  stats = {
    sourceUri: {"isDir": False},
  }
  texts = {
    sourceUri: "# 来源\n\n[内部坏链](missing-target)",
  }
  report = lintModule.build_report(LintFakeClient(texts, stats, lsItems), kbRoot)

  assert "status" in report
  assert "warnings" in report
  assert "errors" in report
  assert "details" in report
  assert any("内部链接失效" in message for message in report["errors"])
