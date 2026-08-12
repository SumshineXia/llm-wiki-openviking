from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-lint" / "scripts"
modulePath = scriptsDir / "lint.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_lint_script_report_semantics", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-lint/scripts/lint.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)


class ReportSemanticsClient:
  def __init__(self, kb_root: str) -> None:
    self.kb_root = kb_root
    self.read_uris = []

    self.index_uri = kb_root + "wiki/index.md"
    self.source_child_uri = kb_root + "wiki/sources/a.md/tmp-source.md"
    self.source_abstract_uri = kb_root + "wiki/sources/a.md/abstract.md"
    self.overview_child_uri = kb_root + "wiki/overview.md/tmp-overview.md"
    self.deep_child_uri = kb_root + "wiki/sources/readme.md/xxx/关键内容.md"

    self.texts = {
      self.index_uri: "# Index\n\n请看 [来源](sources/a.md)",
      self.source_child_uri: "# Source\n\n请看 [概览](../overview.md)",
      self.source_abstract_uri: "",
      self.overview_child_uri: "# Overview\n\n这里是足够长的概览内容，避免被识别为空页面。",
      self.deep_child_uri: "# 关键内容\n\n这里是足够长的深层实际内容，避免被识别为空页面。",
    }

  def ls(self, uri: str, recursive: bool = False):
    wiki_root = self.kb_root + "wiki/"

    if uri == wiki_root and recursive is True:
      return [
        {"uri": self.kb_root + "wiki/sources", "isDir": True},
        {"uri": self.kb_root + "wiki/entities", "isDir": True},
        {"uri": self.kb_root + "wiki/concepts", "isDir": True},
        {"uri": self.kb_root + "wiki/syntheses", "isDir": True},
        {"uri": self.index_uri, "isDir": False},
        {"uri": self.kb_root + "wiki/overview.md", "isDir": True},
        {"uri": self.overview_child_uri, "isDir": False},
        {"uri": self.kb_root + "wiki/sources/a.md", "isDir": True},
        {"uri": self.source_child_uri, "isDir": False},
        {"uri": self.source_abstract_uri, "isDir": False},
        {"uri": self.kb_root + "wiki/sources/readme.md", "isDir": True},
        {"uri": self.kb_root + "wiki/sources/readme.md/xxx", "isDir": True},
        {"uri": self.deep_child_uri, "isDir": False},
      ]

    if uri == wiki_root and recursive is False:
      return [
        {"uri": self.kb_root + "wiki/sources", "isDir": True},
        {"uri": self.kb_root + "wiki/entities", "isDir": True},
        {"uri": self.kb_root + "wiki/concepts", "isDir": True},
        {"uri": self.kb_root + "wiki/syntheses", "isDir": True},
        {"uri": self.index_uri, "isDir": False},
        {"uri": self.kb_root + "wiki/overview.md", "isDir": True},
      ]

    return []

  def stat(self, uri: str):
    raise AssertionError(f"stat should not be needed when ls items include isDir hints: {uri}")

  def read_text(self, uri: str) -> str:
    self.read_uris.append(uri)
    return self.texts.get(uri, "")


def test_build_report_keeps_all_non_dir_markdown_pages_for_summary_and_details() -> None:
  kbRoot = "viking://resources/team-a/project-x/"
  client = ReportSemanticsClient(kbRoot)

  report = module.build_report(client, kbRoot)

  expected_pages = {
    client.index_uri,
    client.source_child_uri,
    client.source_abstract_uri,
    client.overview_child_uri,
    client.deep_child_uri,
  }

  assert report["summary"]["total_pages"] == len(expected_pages)
  assert set(client.read_uris) == expected_pages

  assert client.source_abstract_uri in report["details"]["stub_pages"]
  assert client.source_abstract_uri in report["details"]["pages_without_outbound_links"]
  assert client.deep_child_uri in report["details"]["pages_without_outbound_links"]
