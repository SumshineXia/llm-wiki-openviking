from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-ingest" / "scripts"
modulePath = scriptsDir / "wiki_index.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_index_helper", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-ingest/scripts/wiki_index.py")
module = module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FakeClient:
  def __init__(self, *, stats=None, listings=None, texts=None) -> None:
    self.stats = stats or {}
    self.listings = listings or {}
    self.texts = texts or {}

  def stat(self, uri: str):
    if uri not in self.stats:
      raise module.OVFSHTTPError("404")
    return self.stats[uri]

  def ls(self, uri: str, recursive: bool = False):
    return list(self.listings.get((uri, recursive), []))

  def read_text(self, uri: str) -> str:
    return self.texts[uri]


def test_canonical_index_rel_path_from_uri_collapses_bundle_path() -> None:
  kbRoot = "viking://resources/demo/"
  uri = "viking://resources/demo/wiki/sources/topic-a.md/tmp-001.md"

  assert module.canonical_index_rel_path_from_uri(kbRoot, uri) == "sources/topic-a.md"


def test_resolve_markdown_write_target_uri_prefers_same_name_child_for_index_bundle() -> None:
  indexUri = "viking://resources/demo/wiki/index.md"
  sameNameUri = "viking://resources/demo/wiki/index.md/index.md"
  tmpUri = "viking://resources/demo/wiki/index.md/tmp-001.md"
  client = FakeClient(
    stats={
      indexUri: {"isDir": True},
      sameNameUri: {"isDir": False},
      tmpUri: {"isDir": False},
    },
    listings={
      ("viking://resources/demo/wiki/index.md/", False): [
        {"uri": tmpUri, "isDir": False},
        {"uri": sameNameUri, "isDir": False},
      ],
    },
  )

  targetUri, create = module.resolve_markdown_write_target_uri(client, indexUri)

  assert targetUri == sameNameUri
  assert create is False


def test_resolve_canonical_markdown_uri_raises_non_not_found_ls_errors() -> None:
  bundleUri = "viking://resources/demo/wiki/entities/a.md"

  class FailingClient(FakeClient):
    def ls(self, uri: str, recursive: bool = False):
      if uri == bundleUri + "/" and recursive is False:
        raise module.OVFSHTTPError("500 temporary failure")
      return super().ls(uri, recursive=recursive)

  client = FailingClient(
    stats={
      bundleUri: {"isDir": True},
    }
  )

  with pytest.raises(module.OVFSHTTPError, match="500"):
    module.resolve_canonical_markdown_uri(client, bundleUri)


def test_resolve_canonical_markdown_uri_skips_bundle_abstract_metadata_file() -> None:
  bundleUri = "viking://resources/demo/wiki/entities/a.md"
  abstractUri = f"{bundleUri}/abstract.md"
  client = FakeClient(
    stats={
      bundleUri: {"isDir": True},
      abstractUri: {"isDir": False},
    },
    listings={
      (f"{bundleUri}/", False): [
        {"uri": abstractUri, "isDir": False},
      ],
    },
  )

  assert module.resolve_canonical_markdown_uri(client, bundleUri) is None


def test_resolve_markdown_write_target_uri_skips_bundle_abstract_metadata_file() -> None:
  bundleUri = "viking://resources/demo/wiki/entities/a.md"
  abstractUri = f"{bundleUri}/abstract.md"
  expectedWriteUri = f"{bundleUri}/a.md"
  client = FakeClient(
    stats={
      bundleUri: {"isDir": True},
      abstractUri: {"isDir": False},
    },
    listings={
      (f"{bundleUri}/", False): [
        {"uri": abstractUri, "isDir": False},
      ],
    },
  )

  assert module.resolve_markdown_write_target_uri(client, bundleUri) == (expectedWriteUri, True)


def test_list_indexable_wiki_pages_keeps_bare_overview_md() -> None:
  client = FakeClient(
    stats={
      "viking://resources/demo/wiki/entities/overview.md": {"isDir": False},
    },
    listings={
      ("viking://resources/demo/wiki/sources/", True): [],
      ("viking://resources/demo/wiki/entities/", True): [
        {"uri": "viking://resources/demo/wiki/entities/overview.md", "isDir": False},
      ],
      ("viking://resources/demo/wiki/concepts/", True): [],
      ("viking://resources/demo/wiki/syntheses/", True): [],
    },
  )

  pages = module.list_indexable_wiki_pages(client, "viking://resources/demo/")

  assert pages["entities"] == ["entities/overview.md"]


def test_list_indexable_wiki_pages_keeps_bare_abstract_md() -> None:
  client = FakeClient(
    stats={
      "viking://resources/demo/wiki/concepts/abstract.md": {"isDir": False},
    },
    listings={
      ("viking://resources/demo/wiki/sources/", True): [],
      ("viking://resources/demo/wiki/entities/", True): [],
      ("viking://resources/demo/wiki/concepts/", True): [
        {"uri": "viking://resources/demo/wiki/concepts/abstract.md", "isDir": False},
      ],
      ("viking://resources/demo/wiki/syntheses/", True): [],
    },
  )

  pages = module.list_indexable_wiki_pages(client, "viking://resources/demo/")

  assert pages["concepts"] == ["concepts/abstract.md"]


def test_list_indexable_wiki_pages_ignores_dot_prefixed_derived_files() -> None:
  client = FakeClient(
    stats={
      "viking://resources/demo/wiki/entities/.overview.md": {"isDir": False},
      "viking://resources/demo/wiki/entities/.abstract.md": {"isDir": False},
      "viking://resources/demo/wiki/entities/.relations.json": {"isDir": False},
      "viking://resources/demo/wiki/entities/real-page.md": {"isDir": False},
    },
    listings={
      ("viking://resources/demo/wiki/sources/", True): [],
      ("viking://resources/demo/wiki/entities/", True): [
        {"uri": "viking://resources/demo/wiki/entities/.overview.md", "isDir": False},
        {"uri": "viking://resources/demo/wiki/entities/.abstract.md", "isDir": False},
        {"uri": "viking://resources/demo/wiki/entities/.relations.json", "isDir": False},
        {"uri": "viking://resources/demo/wiki/entities/real-page.md", "isDir": False},
      ],
      ("viking://resources/demo/wiki/concepts/", True): [],
      ("viking://resources/demo/wiki/syntheses/", True): [],
    },
  )

  pages = module.list_indexable_wiki_pages(client, "viking://resources/demo/")

  assert pages["entities"] == ["entities/real-page.md"]


def test_list_indexable_wiki_pages_raises_non_not_found_ls_errors() -> None:
  class FailingClient(FakeClient):
    def ls(self, uri: str, recursive: bool = False):
      if uri == "viking://resources/demo/wiki/entities/" and recursive is True:
        raise module.OVFSHTTPError("500 temporary failure")
      return super().ls(uri, recursive=recursive)

  client = FailingClient(
    listings={
      ("viking://resources/demo/wiki/sources/", True): [],
      ("viking://resources/demo/wiki/concepts/", True): [],
      ("viking://resources/demo/wiki/syntheses/", True): [],
    }
  )

  with pytest.raises(module.OVFSHTTPError, match="500"):
    module.list_indexable_wiki_pages(client, "viking://resources/demo/")


def test_list_indexable_wiki_pages_supports_section_filter() -> None:
  client = FakeClient(
    stats={
      "viking://resources/demo/wiki/entities/a.md": {"isDir": False},
    },
    listings={
      ("viking://resources/demo/wiki/entities/", True): [
        {"uri": "viking://resources/demo/wiki/entities/a.md", "isDir": False},
      ],
    },
  )

  pages = module.list_indexable_wiki_pages(client, "viking://resources/demo/", section_key="entities")

  assert pages == {"entities": ["entities/a.md"]}


def test_parse_index_bullet_link_and_title_handles_hyphenated_slug() -> None:
  line = "- [[concepts/retrieval-augmented-generation.md]] - 检索增强生成"

  assert module.parse_index_bullet_link_and_title(line) == (
    "concepts/retrieval-augmented-generation.md",
    "检索增强生成",
  )


def test_parse_index_entry_map_only_collects_managed_sections() -> None:
  indexText = """# 索引

## 其他
- [[entities/alice.md]] - Alice

## 实体
- [[entities/bob.md]] - Bob
"""

  entries, entryOrder = module.parse_index_entry_map(indexText)

  assert entries["entities"] == {"entities/bob.md": "Bob"}
  assert entryOrder["entities"] == ["entities/bob.md"]


def test_rebuild_index_text_preserves_non_managed_sections_and_manual_content() -> None:
  previousIndexText = """# 索引

- [概览](./overview.md)
- [操作日志](./log.md)

<!-- 顶部注释 -->

## 自定义导航
- [手工页面](./manual.md)

## Sources
- [[sources/old-source.md]] - 旧来源
"""

  rebuilt = module.rebuild_index_text(
    FakeClient(),
    "viking://resources/demo/",
    previousIndexText,
    touched_entries={
      "sources": {"sources/new-source.md": "新来源"},
      "entities": {},
      "concepts": {},
      "syntheses": {},
    },
  )

  assert "<!-- 顶部注释 -->" in rebuilt
  assert "## 自定义导航" in rebuilt
  assert "- [手工页面](./manual.md)" in rebuilt
  assert "## Sources" in rebuilt
  assert "- [[sources/new-source.md]] - 新来源" in rebuilt
  assert "- [[sources/old-source.md]] - 旧来源" not in rebuilt


def test_rebuild_index_text_preserves_manual_lines_inside_managed_sections() -> None:
  previousIndexText = """# 索引

## 实体
<!-- 节内注释 -->
- [人工导航](./manual-entity.md)
- [[entities/old-entity.md]] - 旧实体
手工备注
"""

  rebuilt = module.rebuild_index_text(
    FakeClient(),
    "viking://resources/demo/",
    previousIndexText,
    touched_entries={
      "sources": {},
      "entities": {"entities/new-entity.md": "新实体"},
      "concepts": {},
      "syntheses": {},
    },
  )

  assert "<!-- 节内注释 -->" in rebuilt
  assert "- [人工导航](./manual-entity.md)" in rebuilt
  assert "手工备注" in rebuilt
  assert "- [[entities/new-entity.md]] - 新实体" in rebuilt
  assert "- [[entities/old-entity.md]] - 旧实体" not in rebuilt


def test_rebuild_index_text_keeps_manual_lines_first_when_section_has_no_old_managed_bullets() -> None:
  previousIndexText = """# 索引

## 概念
节内说明
- [人工导航](./manual-concept.md)
"""

  rebuilt = module.rebuild_index_text(
    FakeClient(),
    "viking://resources/demo/",
    previousIndexText,
    touched_entries={
      "sources": {},
      "entities": {},
      "concepts": {"concepts/new-concept.md": "新概念"},
      "syntheses": {},
    },
  )

  conceptSection = rebuilt.split("## 概念\n", 1)[1].split("## ", 1)[0]
  manualIntroIndex = conceptSection.index("节内说明")
  manualNavIndex = conceptSection.index("- [人工导航](./manual-concept.md)")
  managedBulletIndex = conceptSection.index("- [[concepts/new-concept.md]] - 新概念")

  assert manualIntroIndex < managedBulletIndex
  assert manualNavIndex < managedBulletIndex


def test_rebuild_index_text_keeps_existing_order_and_sorts_new_items() -> None:
  kbRoot = "viking://resources/demo/"
  previousIndexText = """# 索引

## 实体
- [[entities/b.md]] - 旧 B
- [[entities/a.md]] - 旧 A
"""
  client = FakeClient(
    stats={
      f"{kbRoot}wiki/entities/a.md": {"isDir": False},
      f"{kbRoot}wiki/entities/b.md": {"isDir": False},
      f"{kbRoot}wiki/entities/c.md": {"isDir": False},
      f"{kbRoot}wiki/entities/d.md": {"isDir": False},
    },
    listings={
      (f"{kbRoot}wiki/sources/", True): [],
      (f"{kbRoot}wiki/entities/", True): [
        {"uri": f"{kbRoot}wiki/entities/b.md", "isDir": False},
        {"uri": f"{kbRoot}wiki/entities/a.md", "isDir": False},
        {"uri": f"{kbRoot}wiki/entities/d.md", "isDir": False},
      ],
      (f"{kbRoot}wiki/concepts/", True): [],
      (f"{kbRoot}wiki/syntheses/", True): [],
    },
    texts={
      f"{kbRoot}wiki/entities/d.md": "# Delta\n\n正文",
    },
  )

  rebuilt = module.rebuild_index_text(
    client,
    kbRoot,
    previousIndexText,
    touched_entries={
      "entities": {"entities/c.md": "Charlie"},
    },
  )

  entitySection = rebuilt.split("## 实体\n", 1)[1].split("## ", 1)[0]

  assert entitySection.index("- [[entities/b.md]] - 旧 B") < entitySection.index("- [[entities/a.md]] - 旧 A")
  assert entitySection.index("- [[entities/a.md]] - 旧 A") < entitySection.index("- [[entities/c.md]] - Charlie")
  assert entitySection.index("- [[entities/c.md]] - Charlie") < entitySection.index("- [[entities/d.md]] - Delta")
