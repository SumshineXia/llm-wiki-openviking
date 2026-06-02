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
  sys.modules[spec.name] = module
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


def test_ingest_schema_contains_chinese_language_rules() -> None:
  module = load_ingest_module()
  schema_text = module.get_schema_path().read_text(encoding="utf-8")

  assert "简体中文" in schema_text
  assert "页面标题使用简体中文" in schema_text
  assert "JSON 字段名保持英文" in schema_text
  assert "文件路径和目录名保持英文" in schema_text


def test_query_schema_contains_chinese_language_rules() -> None:
  schema_path = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "wiki-query"
    / "references"
    / "wiki_schema.md"
  )
  schema_text = schema_path.read_text(encoding="utf-8")

  assert "简体中文" in schema_text
  assert "页面标题使用简体中文" in schema_text
  assert "JSON 字段名保持英文" in schema_text
  assert "文件路径和目录名保持英文" in schema_text
