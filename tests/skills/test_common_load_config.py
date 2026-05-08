import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
module_path = repo_root / "skills" / "wiki-health" / "scripts" / "common.py"
spec = spec_from_file_location("wiki_health_common", module_path)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-health/scripts/common.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
load_config = module.load_config


def test_load_config_uses_defaults_without_file_and_env(tmp_path: Path, monkeypatch) -> None:
  config_path = tmp_path / "missing.json"
  monkeypatch.delenv("OPENVIKING_URL", raising=False)
  monkeypatch.delenv("OPENVIKING_API_KEY", raising=False)
  monkeypatch.delenv("OPENVIKING_TIMEOUT", raising=False)
  monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
  monkeypatch.delenv("OPENAI_API_KEY", raising=False)
  monkeypatch.delenv("OPENAI_MODEL", raising=False)

  config = load_config(str(config_path))

  assert config == {
    "openviking_url": "http://localhost:1933",
    "openviking_api_key": "",
    "openviking_timeout": 30.0,
    "openai_base_url": "",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
  }


def test_load_config_env_overrides_file_values(tmp_path: Path, monkeypatch) -> None:
  config_path = tmp_path / "config.json"
  config_path.write_text(
    json.dumps(
      {
        "openviking_url": "http://file-host:1933",
        "openviking_api_key": "file-key",
        "openviking_timeout": 12,
        "openai_base_url": "https://file-openai.local",
        "openai_api_key": "file-openai-key",
        "openai_model": "file-model",
      }
    ),
    encoding="utf-8",
  )

  monkeypatch.setenv("OPENVIKING_URL", "http://env-host:1933")
  monkeypatch.setenv("OPENVIKING_API_KEY", "env-key")
  monkeypatch.setenv("OPENVIKING_TIMEOUT", "45.5")
  monkeypatch.setenv("OPENAI_BASE_URL", "https://env-openai.local")
  monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")
  monkeypatch.setenv("OPENAI_MODEL", "env-model")

  config = load_config(str(config_path))

  assert config == {
    "openviking_url": "http://env-host:1933",
    "openviking_api_key": "env-key",
    "openviking_timeout": 45.5,
    "openai_base_url": "https://env-openai.local",
    "openai_api_key": "env-openai-key",
    "openai_model": "env-model",
  }
  assert isinstance(config["openviking_timeout"], float)


def test_load_config_casts_timeout_to_float_from_env(tmp_path: Path, monkeypatch) -> None:
  config_path = tmp_path / "config.json"
  config_path.write_text(json.dumps({"openviking_timeout": 22}), encoding="utf-8")
  monkeypatch.setenv("OPENVIKING_TIMEOUT", "61")

  config = load_config(str(config_path))

  assert config["openviking_timeout"] == 61.0
  assert isinstance(config["openviking_timeout"], float)
