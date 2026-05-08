from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Optional
import sys


repo_root = Path(__file__).resolve().parents[2]
scripts_dir = repo_root / "skills" / "wiki-graph" / "scripts"
module_path = scripts_dir / "graph.py"
sys.path.insert(0, str(scripts_dir))
spec = spec_from_file_location("wiki_graph_graph", module_path)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-graph/scripts/graph.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
build_graph_output_paths = module.build_graph_output_paths
build_graph_output_dir_uri = module.build_graph_output_dir_uri
ensure_graph_output_dir = module.ensure_graph_output_dir


def test_build_graph_output_paths_returns_wiki_graph_targets() -> None:
  kb_root = "viking://resources/my-kb/"
  graph_json_uri, graph_html_uri = build_graph_output_paths(kb_root)

  assert graph_json_uri == "viking://resources/my-kb/wiki/graph/graph.json"
  assert graph_html_uri == "viking://resources/my-kb/wiki/graph/graph.html"


def test_build_graph_output_dir_uri_returns_wiki_graph_dir() -> None:
  kb_root = "viking://resources/my-kb/"

  assert build_graph_output_dir_uri(kb_root) == "viking://resources/my-kb/wiki/graph/"


def test_ensure_graph_output_dir_uses_wiki_graph_dir() -> None:
  calls: list[tuple[object, str, str]] = []

  def fake_ensure_dir(client: object, uri: str, description: Optional[str] = None) -> None:
    calls.append((client, uri, description or ""))

  original_ensure_dir = module.ensure_dir
  module.ensure_dir = fake_ensure_dir
  try:
    fake_client = object()
    ensure_graph_output_dir(fake_client, "viking://resources/my-kb/")
  finally:
    module.ensure_dir = original_ensure_dir

  assert calls == [
    (
      fake_client,
      "viking://resources/my-kb/wiki/graph/",
      "wiki graph output dir",
    )
  ]
