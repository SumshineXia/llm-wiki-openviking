from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-lint" / "scripts"
modulePath = scriptsDir / "lint.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_lint_script", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-lint/scripts/lint.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)


def test_check_orphan_pages_uses_in_memory_direct_child_resolution() -> None:
  kbRoot = "viking://resources/team-a/project-x/"

  sourceUri = kbRoot + "wiki/sources/wiki-test-1.md/tmp-source.md"
  overviewUri = kbRoot + "wiki/overview.md/tmp-overview.md"

  pageMap = {
    sourceUri: "请看 [概览](../overview.md)",
    overviewUri: "# Overview\n\n示例内容足够长",
  }

  class DummyClient:
    pass

  orphans = module.check_orphan_pages(DummyClient(), kbRoot, pageMap)

  assert overviewUri not in orphans


def test_actual_bundle_child_link_still_resolves_in_memory() -> None:
  kbRoot = "viking://resources/team-a/project-x/"

  sourceUri = kbRoot + "wiki/sources/a.md/tmp-source.md"
  overviewUri = kbRoot + "wiki/overview.md/tmp-overview.md"

  pageMap = {
    sourceUri: "请看 [实际子文件](../overview.md/tmp-overview.md)",
    overviewUri: "# Overview\n\n示例内容足够长",
  }

  class DummyClient:
    pass

  linkIndex = module.build_link_resolution_index_from_page_map(kbRoot, pageMap)
  linkGraph, broken = module.build_internal_link_graph(kbRoot, pageMap, linkIndex)
  orphans = module.check_orphan_pages(
    DummyClient(),
    kbRoot,
    pageMap,
    link_index=linkIndex,
    link_graph=linkGraph,
  )

  assert broken == []
  assert overviewUri not in orphans


def test_logical_link_does_not_implicitly_resolve_deep_nested_child() -> None:
  kbRoot = "viking://resources/team-a/project-x/"

  sourceUri = kbRoot + "wiki/index.md"
  deepChildUri = kbRoot + "wiki/sources/readme.md/xxx/关键内容.md"

  pageMap = {
    sourceUri: "# Index\n\n请看 [readme](sources/readme.md)",
    deepChildUri: "# 关键内容\n\n示例内容足够长",
  }

  class DummyClient:
    pass

  linkIndex = module.build_link_resolution_index_from_page_map(kbRoot, pageMap)
  linkGraph, broken = module.build_internal_link_graph(kbRoot, pageMap, linkIndex)
  orphans = module.check_orphan_pages(
    DummyClient(),
    kbRoot,
    pageMap,
    link_index=linkIndex,
    link_graph=linkGraph,
  )

  assert broken == [
    {
      "source_uri": sourceUri,
      "target": "sources/readme.md",
    }
  ]
  assert deepChildUri in orphans


def test_exact_deep_actual_child_link_resolves() -> None:
  kbRoot = "viking://resources/team-a/project-x/"

  sourceUri = kbRoot + "wiki/index.md"
  deepChildUri = kbRoot + "wiki/sources/readme.md/xxx/关键内容.md"

  pageMap = {
    sourceUri: "# Index\n\n请看 [关键内容](sources/readme.md/xxx/关键内容.md)",
    deepChildUri: "# 关键内容\n\n示例内容足够长",
  }

  class DummyClient:
    pass

  linkIndex = module.build_link_resolution_index_from_page_map(kbRoot, pageMap)
  linkGraph, broken = module.build_internal_link_graph(kbRoot, pageMap, linkIndex)
  orphans = module.check_orphan_pages(
    DummyClient(),
    kbRoot,
    pageMap,
    link_index=linkIndex,
    link_graph=linkGraph,
  )

  assert broken == []
  assert deepChildUri not in orphans
