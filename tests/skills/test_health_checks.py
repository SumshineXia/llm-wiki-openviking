from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
module_path = repo_root / "skills" / "wiki-health" / "scripts" / "health.py"
spec = spec_from_file_location("wiki_health_script", module_path)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-health/scripts/health.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
required_wiki_pages = module.required_wiki_pages
normalize_relative_wiki_target = module.normalize_relative_wiki_target
extract_index_links = module.extract_index_links
check_index_targets = module.check_index_targets
check_required_structure = module.check_required_structure
requiredDirs = module.requiredDirs


def test_required_wiki_pages_contains_three_root_pages() -> None:
  kb_root = "viking://resources/my-kb/"
  pages = required_wiki_pages(kb_root)

  assert pages == [
    "viking://resources/my-kb/wiki/index.md",
    "viking://resources/my-kb/wiki/overview.md",
    "viking://resources/my-kb/wiki/log.md",
  ]


def test_normalize_relative_wiki_target_handles_parent_segments() -> None:
  assert normalize_relative_wiki_target("../overview.md") == "overview.md"
  assert normalize_relative_wiki_target("./entities/alice") == "entities/alice.md"


def test_extract_index_links_supports_markdown_and_wiki_links() -> None:
  index_text = "\n".join([
    "- [[entities/alice]]",
    "- [概览](../overview.md)",
  ])

  links = extract_index_links(index_text)

  assert "entities/alice.md" in links
  assert "overview.md" in links


class FakeClient:
  def __init__(self, texts: dict[str, str], stats: dict[str, dict[str, bool]]) -> None:
    self.texts = texts
    self.stats = stats

  def read_text(self, uri: str) -> str:
    return self.texts[uri]

  def stat(self, uri: str) -> dict[str, bool]:
    if uri not in self.stats:
      raise RuntimeError("404 not found")
    return self.stats[uri]

  def ls(self, uri: str, recursive: bool = False) -> list[str]:
    return []


def test_check_index_targets_does_not_report_existing_parent_relative_link() -> None:
  kb_root = "viking://resources/my-kb/"
  index_uri = f"{kb_root}wiki/index.md"
  overview_uri = f"{kb_root}wiki/overview.md"
  client = FakeClient(
    texts={index_uri: "- [概览](../overview.md)"},
    stats={
      index_uri: {"isDir": False},
      overview_uri: {"isDir": False},
    },
  )

  _, broken = check_index_targets(client, kb_root)

  assert broken == []


def test_check_required_structure_no_error_when_required_dirs_and_files_exist() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  stats = {
    **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
    **{uri: {"isDir": False} for uri in required_file_uris},
  }
  client = FakeClient(texts={}, stats=stats)

  missing_dirs, missing_files = check_required_structure(client, kb_root)

  assert missing_dirs == []
  assert missing_files == []


def test_check_required_structure_reports_missing_graph_directory() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  stats = {
    **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
    **{uri: {"isDir": False} for uri in required_file_uris},
  }
  stats[f"{kb_root}graph/"] = {"isDir": False}
  client = FakeClient(texts={}, stats=stats)

  missing_dirs, _ = check_required_structure(client, kb_root)

  assert f"{kb_root}graph/" in missing_dirs
