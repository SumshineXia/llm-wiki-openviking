from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


repo_root = Path(__file__).resolve().parents[2]
module_path = repo_root / "skills" / "wiki-health" / "scripts" / "common.py"
spec = spec_from_file_location("wiki_health_common", module_path)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-health/scripts/common.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
validate_kb_name = module.validate_kb_name


@pytest.mark.parametrize("bad_name", ["", "../x", "a//b", "/a/b", "a/b/"])
def test_validate_kb_name_rejects_invalid_inputs(bad_name: str) -> None:
  with pytest.raises(ValueError):
    validate_kb_name(bad_name)


def test_validate_kb_name_accepts_team_project_kb() -> None:
  assert validate_kb_name("team-a/project-x/wiki-kb") == "team-a/project-x/wiki-kb"
