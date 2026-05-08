from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from typing import Optional


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-lint" / "scripts"
modulePath = scriptsDir / "lint.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_lint_script", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-lint/scripts/lint.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)


def test_check_orphan_pages_uses_canonical_targets() -> None:
  kbRoot = "viking://resources/team-a/project-x/"

  sourceUri = "viking://resources/team-a/project-x/wiki/sources/wiki-test-1.md/tmp-source.md"
  overviewUri = "viking://resources/team-a/project-x/wiki/overview.md/tmp-overview.md"

  pageMap = {
    sourceUri: "请看 [概览](../overview.md)",
    overviewUri: "# Overview\n\n示例内容",
  }

  class DummyClient:
    pass

  canonicalMap = {
    "viking://resources/team-a/project-x/wiki/overview.md": overviewUri,
  }

  originalResolver = module.resolve_canonical_markdown_uri

  def fakeResolver(_client: object, uri: str) -> Optional[str]:
    return canonicalMap.get(uri)

  module.resolve_canonical_markdown_uri = fakeResolver
  try:
    orphans = module.check_orphan_pages(DummyClient(), kbRoot, pageMap)
  finally:
    module.resolve_canonical_markdown_uri = originalResolver

  assert overviewUri not in orphans
