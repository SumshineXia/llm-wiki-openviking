from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-save" / "scripts"
modulePath = scriptsDir / "save.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_save_script_updates", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-save/scripts/save.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)


def test_conflict_check_uses_resolve_canonical(monkeypatch, tmp_path: Path, capsys) -> None:
  answerPath = tmp_path / "answer.md"
  answerPath.write_text("答案", encoding="utf-8")

  class FakeClient:
    def __init__(self, _config) -> None:
      self.readCalls = []
      self.writeCalls = []

    def __enter__(self):
      return self

    def __exit__(self, excType, exc, tb) -> None:
      return None

    def stat(self, uri: str):
      if uri.endswith("wiki/syntheses/t.md"):
        return {"isDir": True}
      if uri.endswith("wiki/syntheses/t.md/t.md"):
        return None
      return {"isDir": False}

    def ls(self, uri: str, recursive: bool = False):
      if uri.endswith("wiki/syntheses/t.md/"):
        return [{"uri": "viking://resources/kb/wiki/syntheses/t.md/child.md", "isDir": False}]
      return []

    def read_text(self, uri: str) -> str:
      self.readCalls.append(uri)
      if uri.endswith("index.md"):
        return "# 索引\n"
      if uri.endswith("overview.md"):
        return "# 概览\n"
      return "# 操作日志\n"

    def write_text(self, uri: str, content: str, create: bool, wait: bool) -> None:
      self.writeCalls.append(uri)

  monkeypatch.setattr(
    sys,
    "argv",
    [
      "save.py",
      "--kb-name",
      "kb",
      "--answer-file",
      str(answerPath),
      "--question",
      "q",
      "--title",
      "t",
      "--on-conflict",
      "update",
    ],
  )
  monkeypatch.setattr(module, "OVFSClient", FakeClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())

  code = module.main()
  output = json.loads(capsys.readouterr().out)
  assert code == 0
  assert output["synthesis_uri"].endswith("wiki/syntheses/t.md/child.md")


def test_dry_run_does_not_write_remote(monkeypatch, tmp_path: Path, capsys) -> None:
  answerPath = tmp_path / "answer.md"
  answerPath.write_text("答案", encoding="utf-8")

  class FakeClient:
    def __init__(self, _config) -> None:
      self.writeCalls = []

    def __enter__(self):
      return self

    def __exit__(self, excType, exc, tb) -> None:
      return None

    def stat(self, uri: str):
      if uri.endswith("wiki/syntheses/t.md"):
        raise module.OVFSHTTPError("404")
      return {"isDir": False}

    def ls(self, uri: str, recursive: bool = False):
      return []

    def read_text(self, uri: str) -> str:
      if uri.endswith("index.md"):
        return "# 索引\n"
      if uri.endswith("overview.md"):
        return "# 概览\n"
      return "# 操作日志\n"

    def write_text(self, uri: str, content: str, create: bool, wait: bool) -> None:
      self.writeCalls.append(uri)

  fakeClient = FakeClient(None)
  monkeypatch.setattr(
    sys,
    "argv",
    ["save.py", "--kb-name", "kb", "--answer-file", str(answerPath), "--question", "q", "--title", "t", "--dry-run"],
  )
  monkeypatch.setattr(module, "OVFSClient", lambda _config: fakeClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())

  code = module.main()
  output = json.loads(capsys.readouterr().out)
  assert code == 0
  assert output["dry_run"] is True
  assert fakeClient.writeCalls == []


def test_overview_should_write_synthesis_block(monkeypatch, tmp_path: Path, capsys) -> None:
  answerPath = tmp_path / "answer.md"
  answerPath.write_text("答案", encoding="utf-8")

  class FakeClient:
    def __init__(self, _config) -> None:
      self.writeCalls = []

    def __enter__(self):
      return self

    def __exit__(self, excType, exc, tb) -> None:
      return None

    def stat(self, uri: str):
      if uri.endswith("wiki/syntheses/t.md"):
        raise module.OVFSHTTPError("404")
      return {"isDir": False}

    def ls(self, uri: str, recursive: bool = False):
      return []

    def read_text(self, uri: str) -> str:
      if uri.endswith("index.md"):
        return "# 索引\n"
      if uri.endswith("overview.md"):
        return "# 概览\n"
      return "# 操作日志\n"

    def write_text(self, uri: str, content: str, create: bool, wait: bool) -> None:
      self.writeCalls.append(uri)

  fakeClient = FakeClient(None)
  monkeypatch.setattr(
    sys,
    "argv",
    ["save.py", "--kb-name", "kb", "--answer-file", str(answerPath), "--question", "q", "--title", "t"],
  )
  monkeypatch.setattr(module, "OVFSClient", lambda _config: fakeClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())

  code = module.main()
  output = json.loads(capsys.readouterr().out)
  assert code == 0
  assert output["status"] == "ok"
  assert "viking://resources/kb/wiki/overview.md" in fakeClient.writeCalls


def test_save_rebuilds_index_and_preserves_manual_sections(monkeypatch, tmp_path: Path, capsys) -> None:
  answerPath = tmp_path / "answer.md"
  answerPath.write_text("答案", encoding="utf-8")
  createdClients = []

  class FakeClient:
    def __init__(self, _config) -> None:
      self.writeCalls: list[tuple[str, str, bool, bool]] = []

    def __enter__(self):
      return self

    def __exit__(self, excType, exc, tb) -> None:
      return None

    def stat(self, uri: str):
      if uri.endswith("wiki/syntheses/t.md"):
        raise module.OVFSHTTPError("404")
      if uri.endswith("wiki/index.md"):
        return {"isDir": True}
      return {"isDir": False}

    def ls(self, uri: str, recursive: bool = False):
      if uri.endswith("wiki/index.md/"):
        return []
      return []

    def read_text(self, uri: str) -> str:
      if uri.endswith("index.md"):
        return "# 索引\n\n## 资料来源\n- [[sources/old.md]] - Old\n\n## 自定义说明\n手工备注\n"
      if uri.endswith("overview.md"):
        return "# 概览\n"
      return "# 操作日志\n"

    def write_text(self, uri: str, content: str, create: bool, wait: bool) -> None:
      self.writeCalls.append((uri, content, create, wait))

  def makeClient(config):
    client = FakeClient(config)
    createdClients.append(client)
    return client

  monkeypatch.setattr(
    sys,
    "argv",
    ["save.py", "--kb-name", "kb", "--answer-file", str(answerPath), "--question", "q", "--title", "t"],
  )
  monkeypatch.setattr(module, "OVFSClient", makeClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())

  code = module.main()
  output = json.loads(capsys.readouterr().out)
  fakeClient = createdClients[0]
  writtenIndex = next(
    content for uri, content, _create, _wait in fakeClient.writeCalls if uri.endswith("wiki/index.md/index.md")
  )
  indexWriteCall = next(
    (uri, content, create, wait) for uri, content, create, wait in fakeClient.writeCalls if uri.endswith("wiki/index.md/index.md")
  )

  assert code == 0
  assert output["index_update_mode"] == "rebuild"
  assert output["touched_index_entries"]["syntheses"] == {"syntheses/t.md": "t"}
  assert any(uri.endswith("wiki/index.md/index.md") for uri, _content, _create, _wait in fakeClient.writeCalls)
  assert "- [[syntheses/t.md]] - t" in writtenIndex
  assert "## 自定义说明" in writtenIndex
  assert "手工备注" in writtenIndex
  assert indexWriteCall[2] is False


def test_save_fails_when_index_bundle_listing_returns_non_not_found_error(monkeypatch, tmp_path: Path, capsys) -> None:
  answerPath = tmp_path / "answer.md"
  answerPath.write_text("答案", encoding="utf-8")

  class FakeClient:
    def __init__(self, _config) -> None:
      self.writeCalls = []

    def __enter__(self):
      return self

    def __exit__(self, excType, exc, tb) -> None:
      return None

    def stat(self, uri: str):
      if uri.endswith("wiki/syntheses/t.md"):
        raise module.OVFSHTTPError("404")
      if uri.endswith("wiki/index.md"):
        return {"isDir": True}
      return {"isDir": False}

    def ls(self, uri: str, recursive: bool = False):
      if uri.endswith("wiki/index.md/") and recursive is False:
        raise module.OVFSHTTPError("500 temporary failure")
      return []

    def read_text(self, uri: str) -> str:
      if uri.endswith("overview.md"):
        return "# 概览\n"
      return "# 操作日志\n"

    def write_text(self, uri: str, content: str, create: bool, wait: bool) -> None:
      self.writeCalls.append((uri, content, create, wait))

  monkeypatch.setattr(
    sys,
    "argv",
    ["save.py", "--kb-name", "kb", "--answer-file", str(answerPath), "--question", "q", "--title", "t"],
  )
  monkeypatch.setattr(module, "OVFSClient", FakeClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())

  code = module.main()
  output = json.loads(capsys.readouterr().out)

  assert code == 1
  assert output["error_type"] == "OVFSHTTPError"
  assert "500 temporary failure" in output["error"]
