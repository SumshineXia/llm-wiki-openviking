from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


repo_root = Path(__file__).resolve().parents[2]
scripts_dir = repo_root / "skills" / "wiki-upload-source" / "scripts"
module_path = scripts_dir / "upload.py"
sys.path.insert(0, str(scripts_dir))
spec = spec_from_file_location("wiki_upload_source_upload", module_path)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-upload-source/scripts/upload.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
validate_upload_target = module.validate_upload_target


def test_validate_upload_target_rejects_non_raw_path() -> None:
  with pytest.raises(ValueError):
    validate_upload_target("wiki/index.md")


def test_validate_upload_target_accepts_raw_path() -> None:
  assert validate_upload_target("raw/design.md") == "raw/design.md"


@pytest.mark.parametrize(
  "target",
  [
    "raw/../wiki/index.md",
    "raw//design.md",
    "raw/",
    "",
  ],
)
def test_validate_upload_target_rejects_unsafe_raw_path(target: str) -> None:
  with pytest.raises(ValueError):
    validate_upload_target(target)
