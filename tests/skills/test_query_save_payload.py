from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys
import tempfile

import pytest


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-query" / "scripts"
modulePath = scriptsDir / "query.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_query_script_save_payload", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-query/scripts/query.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)


def test_parse_args_supports_save_payload_file(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    ["query.py", "--kb-name", "kb", "--question", "q", "--save-payload-file", "/tmp/payload.json"],
  )
  args = module.parse_args()
  assert args.save_payload_file == "/tmp/payload.json"


def test_parse_args_rejects_no_save_payload_with_explicit_file(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "query.py",
      "--kb-name",
      "kb",
      "--question",
      "q",
      "--save-payload-file",
      "/tmp/payload.json",
      "--no-save-payload-file",
    ],
  )
  with pytest.raises(SystemExit):
    module.parse_args()


def test_build_save_payload_uses_current_answer() -> None:
  payload = module.build_save_payload(
    kb_name="my-kb",
    kb_root="viking://resources/my-kb/",
    question="问题",
    answer_markdown="当前答案",
    synthesis_title="标题",
    used_pages=["u1"],
    selected_pages=["u2"],
    created_at="2026-06-01T00:00:00Z",
  )
  assert payload["answer_markdown"] == "当前答案"
  assert payload["synthesis_title"] == "标题"
  assert payload["source"] == "wiki-query"


def test_write_json_file_writes_explicit_path(tmp_path: Path) -> None:
  path = tmp_path / "payload.json"
  module.write_json_file(path, {"a": 1}, pretty=True)
  assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}


def test_write_temp_json_file_is_under_tmp_and_keeps_file() -> None:
  path = module.write_temp_json_file({"a": 1}, pretty=False)
  assert str(path).startswith(tempfile.gettempdir())
  assert path.name.startswith("wiki-query-save-")
  assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}


class FakeOVFSClient:
  def __init__(self, _config) -> None:
    pass

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc, tb) -> None:
    return None


def test_main_auto_payload_write_failure_does_not_fail(monkeypatch, capsys) -> None:
  callCount = {"llm": 0}

  monkeypatch.setattr(sys, "argv", ["query.py", "--kb-name", "kb", "--question", "q"])
  monkeypatch.setattr(module, "OVFSClient", FakeOVFSClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())
  monkeypatch.setattr(module, "read_local_schema", lambda: "schema")
  monkeypatch.setattr(module, "read_if_exists", lambda client, uri, default="": default)
  monkeypatch.setattr(module, "select_relevant_pages", lambda client, kb_root, question, top_k: [{"uri": "u1", "content": "c", "score": "1"}])

  def fakeCallLlm(prompt, *, api_key, base_url, model):
    callCount["llm"] += 1
    return {"answer_markdown": "当前答案", "used_pages": ["u1"], "synthesis_title": "标题"}

  monkeypatch.setattr(module, "call_llm", fakeCallLlm)
  monkeypatch.setattr(module, "resolve_openai_settings", lambda args: {"api_key": "k", "base_url": None, "model": "m"})
  monkeypatch.setattr(module, "write_temp_json_file", lambda data, pretty: (_ for _ in ()).throw(OSError("tmp fail")))

  exitCode = module.main()
  output = json.loads(capsys.readouterr().out)

  assert exitCode == 0
  assert callCount["llm"] == 1
  assert output["status"] == "ok"
  assert output["kb_name"] == "kb"
  assert output["synthesis_title"] == "标题"
  assert output["recommended_save_skill"] == "wiki-save"
  assert output["save_payload"]["answer_markdown"] == "当前答案"
  assert output["save_payload_path"] is None
  assert "save_payload_write_error" in output


def test_main_explicit_save_payload_file_write_failure_returns_error(monkeypatch, capsys) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    ["query.py", "--kb-name", "kb", "--question", "q", "--save-payload-file", "/tmp/x.json"],
  )
  monkeypatch.setattr(module, "OVFSClient", FakeOVFSClient)
  monkeypatch.setattr(module.OVFSConfig, "load", lambda config_path=None, profile=None: object())
  monkeypatch.setattr(module, "read_local_schema", lambda: "schema")
  monkeypatch.setattr(module, "read_if_exists", lambda client, uri, default="": default)
  monkeypatch.setattr(module, "select_relevant_pages", lambda client, kb_root, question, top_k: [])
  monkeypatch.setattr(module, "call_llm", lambda prompt, *, api_key, base_url, model: {"answer_markdown": "a", "used_pages": [], "synthesis_title": "t"})
  monkeypatch.setattr(module, "resolve_openai_settings", lambda args: {"api_key": "k", "base_url": None, "model": "m"})
  monkeypatch.setattr(module, "write_json_file", lambda path, data, pretty: (_ for _ in ()).throw(OSError("write fail")))

  exitCode = module.main()
  output = json.loads(capsys.readouterr().out)

  assert exitCode == 1
  assert output["status"] == "error"
  assert "write fail" in output["error"]
