import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-health" / "scripts"
ovfsPath = scriptsDir / "ovfs.py"
if str(scriptsDir) not in sys.path:
    sys.path.insert(0, str(scriptsDir))
import common as common_module

spec = spec_from_file_location("wiki_health_ovfs", ovfsPath)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载 skills/wiki-health/scripts/ovfs.py")
module = module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
OVFSConfig = module.OVFSConfig
OVFSClient = module.OVFSClient
OVFSError = module.OVFSError
ConfigError = common_module.ConfigError


def _clear_env(monkeypatch) -> None:
    for key in [
        "OPENVIKING_URL", "OPENVIKING_API_KEY", "OPENVIKING_ACCOUNT_ID",
        "OPENVIKING_USER_ID", "OPENVIKING_TIMEOUT", "LLM_WIKI_CONFIG",
        "LLM_WIKI_PROFILE",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_load_missing_config_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setattr(common_module, "DEFAULT_CONFIG_PATH", tmp_path / "missing.json")

    with pytest.raises(ConfigError, match="配置文件不存在"):
        OVFSConfig.load()


def test_load_ignores_env_overrides(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"openviking_url": "http://file-host:1933", "openviking_api_key": "file-key"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENVIKING_URL", "http://env-host:1933")
    monkeypatch.setenv("OPENVIKING_API_KEY", "env-key")

    config = OVFSConfig.load(config_path=str(config_path))

    assert config.url == "http://file-host:1933"
    assert config.api_key == "file-key"


def test_load_reads_profile_from_v2_config(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "version": 2,
            "profiles": [{
                "profile": "dev",
                "system": {"name": "Dev System"},
                "openviking": {
                    "url": "http://dev:1933",
                    "api_key": "dev-key",
                    "account_id": "dev-account",
                    "user_id": "dev-user",
                    "timeout": 18,
                },
            }],
        }),
        encoding="utf-8",
    )

    config = OVFSConfig.load(config_path=str(config_path), profile="dev")

    assert config.url == "http://dev:1933"
    assert config.api_key == "dev-key"
    assert config.account_id == "dev-account"
    assert config.user_id == "dev-user"
    assert config.profile == "dev"
    assert config.system_name == "Dev System"
    assert config.timeout == 18.0


def test_load_invalid_profile_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "version": 2,
            "profiles": [{"profile": "dev", "openviking": {"url": "http://dev:1933"}}],
        }),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="profile 不存在.*wrong"):
        OVFSConfig.load(config_path=str(config_path), profile="wrong")


def test_load_empty_url_in_config_raises_config_error(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"openviking_url": "", "openviking_api_key": "k"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="flat config 缺少 openviking_url"):
        OVFSConfig.load(config_path=str(config_path))


def test_load_missing_url_in_config_raises_config_error(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"openviking_api_key": "k"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="flat config 缺少 openviking_url"):
        OVFSConfig.load(config_path=str(config_path))


def test_ovfs_config_raises_ovfs_error_when_load_config_returns_empty_url(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(common_module, "load_config", lambda **kw: {"openviking_url": ""})

    with pytest.raises(OVFSError, match="OpenViking URL 未配置"):
        OVFSConfig.load(config_path=str(tmp_path / "x.json"))


def test_client_sets_auth_headers() -> None:
    config = OVFSConfig(
        url="http://localhost:1933",
        api_key="header-key",
        account_id="header-account",
        user_id="header-user",
    )

    client = OVFSClient(config=config)
    try:
        assert client.session.headers.get("X-API-Key") == "header-key"
        assert client.session.headers.get("X-OpenViking-Account") == "header-account"
        assert client.session.headers.get("X-OpenViking-User") == "header-user"
    finally:
        client.close()


def test_ovfs_config_load_rejects_deprecated_flat_default_kb_name(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "openviking_url": "http://file-host:1933",
                "default_kb_name": "old-default"
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="已废弃字段 default_kb_name"):
        OVFSConfig.load(config_path=str(config_path))


def test_ovfs_config_load_rejects_deprecated_flat_system_id(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "openviking_url": "http://file-host:1933",
                "system_id": "old-system"
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="已废弃字段 system_id"):
        OVFSConfig.load(config_path=str(config_path))


def test_ovfs_config_load_rejects_deprecated_flat_defaults(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "openviking_url": "http://file-host:1933",
                "defaults": {
                    "kb_name": "old-default"
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="已废弃字段 defaults"):
        OVFSConfig.load(config_path=str(config_path))


def test_ovfs_config_load_rejects_deprecated_v2_system_id(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "version": 2,
                "profiles": [
                    {
                        "profile": "dev",
                        "system": {
                            "id": "old-system",
                            "name": "Dev System"
                        },
                        "openviking": {
                            "url": "http://dev:1933"
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="已废弃字段 id"):
        OVFSConfig.load(config_path=str(config_path), profile="dev")


def test_ovfs_config_load_rejects_deprecated_v2_defaults(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "version": 2,
                "profiles": [
                    {
                        "profile": "dev",
                        "system": {
                            "name": "Dev System"
                        },
                        "openviking": {
                            "url": "http://dev:1933"
                        },
                        "defaults": {
                            "kb_name": "old-default"
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="已废弃字段 defaults"):
        OVFSConfig.load(config_path=str(config_path), profile="dev")
