from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-lint" / "scripts"
modulePath = scriptsDir / "lint.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_lint_script_perf", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-lint/scripts/lint.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)


class CountingClient:
  def __init__(self, kb_root: str) -> None:
    self.kb_root = kb_root
    self.stat_calls = 0
    self.ls_calls = []

    self.source_uri = kb_root + "wiki/sources/a.md"
    self.target_uri = kb_root + "wiki/concepts/b.md"

    self.texts = {
      self.source_uri: "# A\n\n- [B](../concepts/b.md)\n",
      self.target_uri: "# B\n\n内容足够长，避免被识别为空页面。\n",
    }

  def ls(self, uri: str, recursive: bool = False):
    self.ls_calls.append((uri, recursive))
    wiki_root = self.kb_root + "wiki/"

    if uri == wiki_root and recursive is True:
      return [
        {"uri": self.kb_root + "wiki/sources", "isDir": True},
        {"uri": self.kb_root + "wiki/concepts", "isDir": True},
        {"uri": self.source_uri, "isDir": False},
        {"uri": self.target_uri, "isDir": False},
      ]

    if uri == wiki_root and recursive is False:
      return [
        {"uri": self.kb_root + "wiki/sources", "isDir": True},
        {"uri": self.kb_root + "wiki/concepts", "isDir": True},
      ]

    return []

  def stat(self, uri: str):
    self.stat_calls += 1
    raise AssertionError(f"stat should not be called during in-memory lint link resolution: {uri}")

  def read_text(self, uri: str) -> str:
    return self.texts.get(uri, "")


def test_build_report_does_not_stat_or_resolve_per_link_and_scans_tree_once(monkeypatch):
  kbRoot = "viking://resources/demo/"
  wikiRoot = kbRoot + "wiki/"
  client = CountingClient(kbRoot)

  def failResolver(*args, **kwargs):
    raise AssertionError("resolve_canonical_markdown_uri should not be used in build_report hot path")

  monkeypatch.setattr(module, "resolve_canonical_markdown_uri", failResolver)

  report = module.build_report(client, kbRoot)

  assert report["summary"]["broken_links"] == 0
  assert client.stat_calls == 0

  assert client.ls_calls.count((wikiRoot, True)) == 1
  assert client.ls_calls.count((wikiRoot, False)) == 1
  assert len([call for call in client.ls_calls if call[1] is True]) == 1
  assert len(client.ls_calls) == 2
