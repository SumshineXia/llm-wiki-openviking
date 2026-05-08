import importlib.util
from pathlib import Path
import sys


def load_ingest_module():
  ingest_path = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "wiki-ingest"
    / "scripts"
    / "ingest.py"
  )
  spec = importlib.util.spec_from_file_location("wiki_ingest_skill_ingest", ingest_path)
  assert spec is not None and spec.loader is not None
  sys.path.insert(0, str(ingest_path.parent))
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_get_schema_path_points_to_skill_reference() -> None:
  module = load_ingest_module()
  expected = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "wiki-ingest"
    / "references"
    / "wiki_schema.md"
  )
  assert module.get_schema_path() == expected
