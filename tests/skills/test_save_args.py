from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-save" / "scripts"
modulePath = scriptsDir / "save.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_save_script_args", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-save/scripts/save.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)


def test_parse_args_rejects_answer(monkeypatch) -> None:
  monkeypatch.setattr(sys, "argv", ["save.py", "--answer", "x"])
  with pytest.raises(SystemExit):
    module.parseArgs()


def test_parse_args_rejects_payload_with_answer_file(monkeypatch) -> None:
  monkeypatch.setattr(sys, "argv", ["save.py", "--payload-file", "/tmp/p.json", "--answer-file", "/tmp/a.md"])
  with pytest.raises(SystemExit):
    module.parseArgs()


def test_parse_args_rejects_payload_with_question(monkeypatch) -> None:
  monkeypatch.setattr(sys, "argv", ["save.py", "--payload-file", "/tmp/p.json", "--question", "q"])
  with pytest.raises(SystemExit):
    module.parseArgs()
