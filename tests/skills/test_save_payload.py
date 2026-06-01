from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys

import pytest


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-save" / "scripts"
modulePath = scriptsDir / "save.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_save_script_payload", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-save/scripts/save.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)


def test_build_input_rejects_payload_kb_name_conflict(tmp_path: Path) -> None:
  payloadPath = tmp_path / "payload.json"
  payloadPath.write_text(
    json.dumps(
      {
        "kb_name": "from-payload",
        "question": "q",
        "answer_markdown": "a",
        "synthesis_title": "t",
      },
      ensure_ascii=False,
    ),
    encoding="utf-8",
  )

  args = module.parseArgs.__globals__["argparse"].Namespace(
    kb_name="from-cli",
    payload_file=str(payloadPath),
    answer_file=None,
    question=None,
    title=None,
    used_page=[],
  )
  with pytest.raises(ValueError, match="kb_name"):
    module.buildInput(args)


def test_payload_kb_root_is_validated_but_not_trusted(monkeypatch, tmp_path: Path, capsys) -> None:
  payloadPath = tmp_path / "payload.json"
  payloadPath.write_text(
    json.dumps(
      {
        "kb_name": "my-kb",
        "kb_root": "viking://resources/wrong-kb/",
        "question": "问题",
        "answer_markdown": "答案",
        "synthesis_title": "标题",
        "used_pages": ["viking://resources/my-kb/wiki/a.md"],
      },
      ensure_ascii=False,
    ),
    encoding="utf-8",
  )

  class FakeClient:
    def __init__(self, _config) -> None:
      self.writes = []

    def __enter__(self):
      return self

    def __exit__(self, excType, exc, tb) -> None:
      return None

    def stat(self, uri: str):
      if uri.endswith("wiki/syntheses/标题.md"):
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
      self.writes.append(uri)

  monkeypatch.setattr(sys, "argv", ["save.py", "--payload-file", str(payloadPath), "--dry-run"])
  monkeypatch.setattr(module, "OVFSClient", FakeClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())

  code = module.main()
  output = json.loads(capsys.readouterr().out)
  assert code == 0
  assert output["kb_root"] == "viking://resources/my-kb/"
  assert output["payload_kb_root_mismatch"] is True


def test_build_input_rejects_non_string_payload_fields(tmp_path: Path) -> None:
  payloadPath = tmp_path / "payload.json"
  payloadPath.write_text(
    json.dumps(
      {
        "kb_name": "my-kb",
        "question": None,
        "answer_markdown": "答案",
        "synthesis_title": "标题",
        "used_pages": [],
      },
      ensure_ascii=False,
    ),
    encoding="utf-8",
  )

  args = module.parseArgs.__globals__["argparse"].Namespace(
    kb_name=None,
    payload_file=str(payloadPath),
    answer_file=None,
    question=None,
    title=None,
    used_page=[],
  )
  with pytest.raises(ValueError, match="question"):
    module.buildInput(args)


def test_build_input_rejects_invalid_used_pages_type(tmp_path: Path) -> None:
  payloadPath = tmp_path / "payload.json"
  payloadPath.write_text(
    json.dumps(
      {
        "kb_name": "my-kb",
        "question": "问题",
        "answer_markdown": "答案",
        "synthesis_title": "标题",
        "used_pages": ["u1", 1],
      },
      ensure_ascii=False,
    ),
    encoding="utf-8",
  )

  args = module.parseArgs.__globals__["argparse"].Namespace(
    kb_name=None,
    payload_file=str(payloadPath),
    answer_file=None,
    question=None,
    title=None,
    used_page=[],
  )
  with pytest.raises(ValueError, match="used_pages"):
    module.buildInput(args)


def test_build_input_rejects_non_string_payload_kb_root(tmp_path: Path) -> None:
  payloadPath = tmp_path / "payload.json"
  payloadPath.write_text(
    json.dumps(
      {
        "kb_name": "my-kb",
        "kb_root": 123,
        "question": "问题",
        "answer_markdown": "答案",
        "synthesis_title": "标题",
        "used_pages": [],
      },
      ensure_ascii=False,
    ),
    encoding="utf-8",
  )

  args = module.parseArgs.__globals__["argparse"].Namespace(
    kb_name=None,
    payload_file=str(payloadPath),
    answer_file=None,
    question=None,
    title=None,
    used_page=[],
  )
  with pytest.raises(ValueError, match="kb_root"):
    module.buildInput(args)
