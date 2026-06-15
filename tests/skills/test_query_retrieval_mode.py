from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-query" / "scripts"
modulePath = scriptsDir / "query.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_query_script_retrieval", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-query/scripts/query.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)


def test_extract_index_entries_supports_legacy_and_link_variants() -> None:
  indexText = """# 索引

## 资料来源
- [[sources/a|别名A]]
- [来源B](wiki/sources/b.md?x=1#frag)

## Entities
- [[entities/c.md#段落]]
- [外链](https://example.com/1)

## 概念
- [[concepts/d]]

## 其他
- [[misc/e]]
"""

  entries = module.extract_index_entries(indexText)
  assert entries == {
    "sources/a.md",
    "sources/b.md",
    "entities/c.md",
    "concepts/d.md",
  }


class FakeClient:
  def __init__(self, pages: dict[str, str]) -> None:
    self.pages = pages
    self.readCalls: list[str] = []

  def read_text(self, uri: str) -> str:
    self.readCalls.append(uri)
    if uri not in self.pages:
      raise RuntimeError(f"missing {uri}")
    return self.pages[uri]


def test_select_relevant_pages_index_mode_no_scan(monkeypatch) -> None:
  kbRoot = "viking://resources/kb/"
  pageA = kbRoot + "wiki/sources/a.md"
  pageB = kbRoot + "wiki/concepts/b.md"
  pages = {
    pageA: "alpha 内容",
    pageB: "beta 内容",
  }
  client = FakeClient(pages)

  monkeypatch.setattr(module, "read_if_exists", lambda c, uri, default="": "## 资料来源\n- [[sources/a]]\n- [[concepts/b]]\n")
  monkeypatch.setattr(module, "resolve_canonical_markdown_uri", lambda c, uri: uri if uri.endswith(".md") else uri + ".md")

  scanCalled = {"value": False}
  def fakeListMarkdownPages(_client, _rootUri):
    scanCalled["value"] = True
    return [kbRoot + "wiki/scan/x.md"]

  monkeypatch.setattr(module, "list_markdown_pages", fakeListMarkdownPages)
  module.select_relevant_pages.retrieval_mode = "index"
  module.select_relevant_pages.candidate_multiplier = 2
  module.select_relevant_pages.max_page_chars = 5

  selectedPages, debug = module.select_relevant_pages(client, kbRoot, "alpha", top_k=1)

  assert selectedPages[0]["uri"] == pageA
  assert scanCalled["value"] is False
  assert debug["retrieval_mode"] == "index"
  assert debug["fallback_scan_used"] is False
  assert debug["content_limit_hit_count"] == 2


def test_select_relevant_pages_auto_fallback_scan(monkeypatch) -> None:
  kbRoot = "viking://resources/kb/"
  scanUri = kbRoot + "wiki/sources/fallback.md"
  pages = {scanUri: "fallback 内容"}
  client = FakeClient(pages)

  monkeypatch.setattr(module, "read_if_exists", lambda c, uri, default="": "# 索引\n")
  monkeypatch.setattr(module, "resolve_canonical_markdown_uri", lambda c, uri: None)
  monkeypatch.setattr(module, "list_markdown_pages", lambda c, rootUri: [scanUri])
  module.select_relevant_pages.retrieval_mode = "auto"
  module.select_relevant_pages.candidate_multiplier = 3
  module.select_relevant_pages.max_page_chars = 100

  selectedPages, debug = module.select_relevant_pages(client, kbRoot, "fallback", top_k=1)

  assert selectedPages[0]["uri"] == scanUri
  assert debug["fallback_scan_used"] is True
  assert debug["index_entry_count"] == 0
  assert debug["read_page_count"] == 1


def test_parse_args_retrieval_related_positive_validation(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "query.py",
      "--kb-name",
      "kb",
      "--question",
      "q",
      "--retrieval-mode",
      "scan",
      "--candidate-multiplier",
      "4",
      "--max-page-chars",
      "200",
      "--max-overview-chars",
      "300",
    ],
  )
  args = module.parse_args()
  assert args.retrieval_mode == "scan"
  assert args.candidate_multiplier == 4
  assert args.max_page_chars == 200
  assert args.max_overview_chars == 300


def test_parse_args_rejects_non_positive_values(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "query.py",
      "--kb-name",
      "kb",
      "--question",
      "q",
      "--candidate-multiplier",
      "0",
    ],
  )
  with pytest.raises(SystemExit):
    module.parse_args()


def test_build_llm_prompt_truncates_overview_when_exceeds_limit() -> None:
  module.build_llm_prompt.max_overview_chars = 10
  overviewText = "0123456789ABCDEFGHIJ"

  prompt = module.build_llm_prompt(
    schema_text="schema",
    question="question",
    overview_text=overviewText,
    selected_pages=[],
  )

  assert "0123456789" in prompt
  assert "ABCDEFGHIJ" not in prompt
  assert "[overview truncated to 10 chars]" in prompt


def test_build_llm_prompt_keeps_overview_when_within_limit() -> None:
  module.build_llm_prompt.max_overview_chars = 50
  overviewText = "short overview"

  prompt = module.build_llm_prompt(
    schema_text="schema",
    question="question",
    overview_text=overviewText,
    selected_pages=[],
  )

  assert "short overview" in prompt
  assert "[overview truncated to 50 chars]" not in prompt


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
