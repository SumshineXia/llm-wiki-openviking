from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re
import sys


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-query" / "scripts"
modulePath = scriptsDir / "query.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_query_script", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-query/scripts/query.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
buildSynthesisTarget = module.build_synthesis_target


def test_build_synthesis_target_with_slug() -> None:
  assert buildSynthesisTarget("abc", "ignored") == "wiki/syntheses/abc.md"


def test_build_synthesis_target_without_slug_prefix() -> None:
  target = buildSynthesisTarget(None, "这份文档的核心目标是什么？")
  assert target.startswith("wiki/syntheses/这份文档的核心目标是-")
  assert re.fullmatch(r"wiki/syntheses/.+-\d{8}-\d{6}\.md", target)
