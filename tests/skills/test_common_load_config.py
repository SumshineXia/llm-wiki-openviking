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


def _clear_env(monkeypatch) -> None:
  monkeypatch.delenv("OPENVIKING_URL", raising=False)
  monkeypatch.delenv("OPENVIKING_API_KEY", raising=False)
  monkeypatch.delenv("OPENVIKING_ACCOUNT_ID", raising=False)
  monkeypatch.delenv("OPENVIKING_USER_ID", raising=False)
  monkeypatch.delenv("OPENVIKING_TIMEOUT", raising=False)
  monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
  monkeypatch.delenv("OPENAI_API_KEY", raising=False)
  monkeypatch.delenv("OPENAI_MODEL", raising=False)
  monkeypatch.delenv("LLM_WIKI_CONFIG", raising=False)
  monkeypatch.delenv("LLM_WIKI_PROFILE", raising=False)


def _write_v2_config(path: Path) -> None:
  path.write_text(
    json.dumps(
      {
        "version": 2,
        "profiles": [
          {
            "profile": "p1",
            "system": {"id": "s1", "name": "System 1", "ipmp_system_num": "IPMP-1"},
            "openviking": {
              "url": "http://p1-host:1933",
              "api_key": "p1-key",
              "account_id": "p1-account",
              "user_id": "p1-user",
              "timeout": 11,
            },
            "openai": {
              "base_url": "https://p1-openai.local",
              "api_key": "p1-openai-key",
              "model": "p1-model",
            },
            "defaults": {"kb_name": "kb-p1"},
          },
          {
            "profile": "p2",
            "system": {"id": "s2", "name": "System 2", "ipmp_system_num": "IPMP-2"},
            "openviking": {
              "url": "http://p2-host:1933",
              "api_key": "p2-key",
              "account_id": "p2-account",
              "user_id": "p2-user",
              "timeout": 22,
            },
            "openai": {
              "base_url": "https://p2-openai.local",
              "api_key": "p2-openai-key",
              "model": "p2-model",
            },
            "defaults": {"kb_name": "kb-p2"},
          },
        ],
      }
    ),
    encoding="utf-8",
  )


def test_load_config_uses_defaults_without_file_and_env(tmp_path: Path, monkeypatch) -> None:
  config_path = tmp_path / "missing.json"
  _clear_env(monkeypatch)

  config = load_config(str(config_path))

  assert config == {
    "profile": "",
    "system_id": "",
    "system_name": "",
    "ipmp_system_num": "",
    "openviking_url": "http://localhost:1933",
    "openviking_api_key": "",
    "openviking_account_id": "",
    "openviking_user_id": "",
    "openviking_timeout": 30.0,
    "openai_base_url": "",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "default_kb_name": "",
  }


def test_load_config_env_overrides_file_values(tmp_path: Path, monkeypatch) -> None:
  _clear_env(monkeypatch)
  config_path = tmp_path / "config.json"
  config_path.write_text(
    json.dumps(
      {
        "profile": "flat",
        "system_id": "flat-system",
        "system_name": "Flat System",
        "ipmp_system_num": "FLAT-IPMP",
        "openviking_url": "http://file-host:1933",
        "openviking_api_key": "file-key",
        "openviking_account_id": "file-account",
        "openviking_user_id": "file-user",
        "openviking_timeout": 12,
        "openai_base_url": "https://file-openai.local",
        "openai_api_key": "file-openai-key",
        "openai_model": "file-model",
        "default_kb_name": "file-kb",
      }
    ),
    encoding="utf-8",
  )

  monkeypatch.setenv("OPENVIKING_URL", "http://env-host:1933")
  monkeypatch.setenv("OPENVIKING_API_KEY", "env-key")
  monkeypatch.setenv("OPENVIKING_ACCOUNT_ID", "env-account")
  monkeypatch.setenv("OPENVIKING_USER_ID", "env-user")
  monkeypatch.setenv("OPENVIKING_TIMEOUT", "45.5")
  monkeypatch.setenv("OPENAI_BASE_URL", "https://env-openai.local")
  monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")
  monkeypatch.setenv("OPENAI_MODEL", "env-model")

  config = load_config(str(config_path))

  assert config == {
    "profile": "flat",
    "system_id": "flat-system",
    "system_name": "Flat System",
    "ipmp_system_num": "FLAT-IPMP",
    "openviking_url": "http://env-host:1933",
    "openviking_api_key": "env-key",
    "openviking_account_id": "env-account",
    "openviking_user_id": "env-user",
    "openviking_timeout": 45.5,
    "openai_base_url": "https://env-openai.local",
    "openai_api_key": "env-openai-key",
    "openai_model": "env-model",
    "default_kb_name": "file-kb",
  }
  assert isinstance(config["openviking_timeout"], float)


def test_load_config_casts_timeout_to_float_from_env(tmp_path: Path, monkeypatch) -> None:
  _clear_env(monkeypatch)
  config_path = tmp_path / "config.json"
  config_path.write_text(json.dumps({"openviking_timeout": 22}), encoding="utf-8")
  monkeypatch.setenv("OPENVIKING_TIMEOUT", "61")

  config = load_config(str(config_path))

  assert config["openviking_timeout"] == 61.0
  assert isinstance(config["openviking_timeout"], float)


def test_load_config_uses_first_profile_by_default(tmp_path: Path, monkeypatch) -> None:
  _clear_env(monkeypatch)
  config_path = tmp_path / "config.json"
  _write_v2_config(config_path)

  config = load_config(str(config_path))

  assert config["profile"] == "p1"
  assert config["openviking_account_id"] == "p1-account"
  assert config["default_kb_name"] == "kb-p1"


def test_load_config_explicit_profile_has_high_priority(tmp_path: Path, monkeypatch) -> None:
  _clear_env(monkeypatch)
  config_path = tmp_path / "config.json"
  _write_v2_config(config_path)
  monkeypatch.setenv("LLM_WIKI_PROFILE", "p1")

  config = load_config(str(config_path), profile="p2")

  assert config["profile"] == "p2"
  assert config["openviking_url"] == "http://p2-host:1933"


def test_load_config_uses_llm_wiki_config_env(tmp_path: Path, monkeypatch) -> None:
  _clear_env(monkeypatch)
  config_path = tmp_path / "config-from-env.json"
  _write_v2_config(config_path)
  monkeypatch.setenv("LLM_WIKI_CONFIG", str(config_path))

  config = load_config()

  assert config["profile"] == "p1"
  assert config["openviking_api_key"] == "p1-key"


def test_load_config_explicit_config_path_overrides_llm_wiki_config(
  tmp_path: Path,
  monkeypatch,
) -> None:
  _clear_env(monkeypatch)
  env_config_path = tmp_path / "env-config.json"
  explicit_config_path = tmp_path / "explicit-config.json"
  _write_v2_config(env_config_path)
  explicit_config_path.write_text(
    json.dumps(
      {
        "openviking_url": "http://explicit-host:1933",
        "openviking_api_key": "explicit-key",
      }
    ),
    encoding="utf-8",
  )
  monkeypatch.setenv("LLM_WIKI_CONFIG", str(env_config_path))

  config = load_config(str(explicit_config_path))

  assert config["openviking_url"] == "http://explicit-host:1933"
  assert config["openviking_api_key"] == "explicit-key"


def test_load_config_compat_with_flat_config(tmp_path: Path, monkeypatch) -> None:
  _clear_env(monkeypatch)
  config_path = tmp_path / "flat.json"
  config_path.write_text(
    json.dumps(
      {
        "profile": "legacy",
        "system_name": "Legacy",
        "openviking_account_id": "legacy-account",
        "openviking_user_id": "legacy-user",
        "default_kb_name": "legacy-kb",
      }
    ),
    encoding="utf-8",
  )

  config = load_config(str(config_path))

  assert config["profile"] == "legacy"
  assert config["system_name"] == "Legacy"
  assert config["openviking_account_id"] == "legacy-account"
  assert config["openviking_user_id"] == "legacy-user"
  assert config["default_kb_name"] == "legacy-kb"
