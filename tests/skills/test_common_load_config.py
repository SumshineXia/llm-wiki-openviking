import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


repo_root = Path(__file__).resolve().parents[2]
module_path = repo_root / "skills" / "wiki-health" / "scripts" / "common.py"
spec = spec_from_file_location("wiki_health_common", module_path)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载 skills/wiki-health/scripts/common.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
load_config = module.load_config
ConfigError = module.ConfigError


def _clear_env(monkeypatch, tmp_path) -> None:
    for key in [
        "OPENVIKING_URL", "OPENVIKING_API_KEY", "OPENVIKING_ACCOUNT_ID",
        "OPENVIKING_USER_ID", "OPENVIKING_TIMEOUT", "OPENAI_BASE_URL",
        "OPENAI_API_KEY", "OPENAI_MODEL", "LLM_WIKI_CONFIG", "LLM_WIKI_PROFILE",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(module, "DEFAULT_CURRENT_PROFILE_PATH", tmp_path / "current")


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


def _write_single_profile_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "profiles": [
                    {
                        "profile": "only",
                        "openviking": {
                            "url": "http://only-host:1933",
                            "api_key": "only-key",
                            "timeout": 15,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_load_config_missing_file_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    missing_path = tmp_path / "missing.json"

    with pytest.raises(ConfigError, match="配置文件不存在"):
        load_config(str(missing_path))


def test_load_config_empty_file_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text("", encoding="utf-8")

    with pytest.raises(ConfigError, match="配置文件为空"):
        load_config(str(config_path))


def test_load_config_invalid_json_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(ConfigError, match="JSON 非法"):
        load_config(str(config_path))


def test_load_config_non_object_json_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ConfigError, match="JSON 对象"):
        load_config(str(config_path))


def test_load_config_flat_config_requires_openviking_url(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"profile": "legacy", "openviking_api_key": "k"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="flat config 缺少 openviking_url"):
        load_config(str(config_path))


def test_load_config_flat_config_with_explicit_localhost_is_allowed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "openviking_url": "http://localhost:1933",
            "openviking_api_key": "file-key",
            "openviking_timeout": 12,
        }),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config["openviking_url"] == "http://localhost:1933"
    assert config["openviking_timeout"] == 12


def test_load_config_uses_file_values_over_env(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "openviking_url": "http://file-host:1933",
            "openviking_api_key": "file-key",
            "openviking_account_id": "file-account",
            "openviking_user_id": "file-user",
            "openviking_timeout": 12,
            "openai_base_url": "https://file-openai.local",
            "openai_api_key": "file-openai-key",
            "openai_model": "file-model",
            "default_kb_name": "file-kb",
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENVIKING_URL", "http://env-host:1933")
    monkeypatch.setenv("OPENVIKING_API_KEY", "env-key")

    config = load_config(str(config_path))

    assert config["openviking_url"] == "http://file-host:1933"
    assert config["openviking_api_key"] == "file-key"
    assert isinstance(config["openviking_timeout"], float)


def test_load_config_ignores_openviking_env_overrides(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"openviking_url": "http://file-host:1933", "openviking_timeout": 12}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENVIKING_URL", "http://env-host:1933")
    monkeypatch.setenv("OPENVIKING_TIMEOUT", "99")

    config = load_config(str(config_path))

    assert config["openviking_url"] == "http://file-host:1933"
    assert config["openviking_timeout"] == 12.0


def test_load_config_explicit_config_path_overrides_llm_wiki_config(
    tmp_path: Path, monkeypatch,
) -> None:
    _clear_env(monkeypatch, tmp_path)
    explicit_config_path = tmp_path / "explicit-config.json"
    explicit_config_path.write_text(
        json.dumps({
            "openviking_url": "http://explicit-host:1933",
            "openviking_api_key": "explicit-key",
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_WIKI_CONFIG", "/nonexistent/path.json")

    config = load_config(str(explicit_config_path))

    assert config["openviking_url"] == "http://explicit-host:1933"
    assert config["openviking_api_key"] == "explicit-key"


def test_load_config_llm_wiki_config_env_is_ignored(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "DEFAULT_CONFIG_PATH", tmp_path / "default-config.json")
    env_config_path = tmp_path / "env-config.json"
    _write_v2_config(env_config_path)
    monkeypatch.setenv("LLM_WIKI_CONFIG", str(env_config_path))

    with pytest.raises(ConfigError, match="配置文件不存在"):
        load_config()


def test_load_config_explicit_profile_has_highest_priority(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_v2_config(config_path)
    monkeypatch.setenv("LLM_WIKI_PROFILE", "p1")

    config = load_config(str(config_path), profile="p2")

    assert config["profile"] == "p2"
    assert config["openviking_url"] == "http://p2-host:1933"
    assert config["profile_source"] == "--profile"


def test_load_config_env_profile_selects_profile(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_v2_config(config_path)
    monkeypatch.setenv("LLM_WIKI_PROFILE", "p2")

    config = load_config(str(config_path))

    assert config["profile"] == "p2"
    assert config["profile_source"] == "LLM_WIKI_PROFILE"


def test_load_config_invalid_env_profile_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_v2_config(config_path)
    monkeypatch.setenv("LLM_WIKI_PROFILE", "missing-profile")

    with pytest.raises(ConfigError, match="profile 不存在.*missing-profile"):
        load_config(str(config_path))


def test_load_config_invalid_explicit_profile_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_v2_config(config_path)

    with pytest.raises(ConfigError, match="profile 不存在.*nonexistent"):
        load_config(str(config_path), profile="nonexistent")


def test_load_config_uses_single_profile_by_default(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_single_profile_config(config_path)

    config = load_config(str(config_path))

    assert config["profile"] == "only"
    assert config["profile_source"] == "single-profile"
    assert config["openviking_url"] == "http://only-host:1933"


def test_load_config_rejects_ambiguous_multiple_profiles_without_selection(
    tmp_path: Path, monkeypatch,
) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_v2_config(config_path)

    with pytest.raises(ConfigError, match="多个 profile"):
        load_config(str(config_path))


def test_load_config_current_file_selects_profile(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_v2_config(config_path)
    current_path = tmp_path / "current"
    current_path.write_text("p2\n", encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_CURRENT_PROFILE_PATH", current_path)

    config = load_config(str(config_path))

    assert config["profile"] == "p2"
    assert config["profile_source"] == "current"


def test_load_config_profile_source_includes_config_path(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_single_profile_config(config_path)

    config = load_config(str(config_path))

    assert "config_path" in config
    assert config["config_path"] == str(config_path)


def test_load_config_timeout_cast_to_float(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"openviking_url": "http://h:1933", "openviking_timeout": 22}), encoding="utf-8")

    config = load_config(str(config_path))

    assert config["openviking_timeout"] == 22.0
    assert isinstance(config["openviking_timeout"], float)
