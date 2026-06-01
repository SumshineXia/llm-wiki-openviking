import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


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


def test_load_falls_back_to_defaults_and_ignores_legacy_ovcli_conf(
  tmp_path: Path,
  monkeypatch,
) -> None:
  legacyConfPath = tmp_path / ".openviking" / "ovcli.conf"
  legacyConfPath.parent.mkdir(parents=True, exist_ok=True)
  legacyConfPath.write_text(
    '{"url":"http://legacy:1933","api_key":"legacy-key","timeout":99}',
    encoding="utf-8",
  )

  monkeypatch.setenv("HOME", str(tmp_path))
  monkeypatch.delenv("OPENVIKING_URL", raising=False)
  monkeypatch.delenv("OPENVIKING_API_KEY", raising=False)
  monkeypatch.delenv("OPENVIKING_TIMEOUT", raising=False)

  config = OVFSConfig.load()

  assert config.url in ("http://localhost:1933", "http://127.0.0.1:1933")
  assert config.api_key != "legacy-key"
  assert config.timeout == 30.0


def test_load_ignores_env_overrides(tmp_path: Path, monkeypatch) -> None:
  monkeypatch.setattr(common_module, "DEFAULT_CONFIG_PATH", tmp_path / "config.json")
  monkeypatch.setattr(common_module, "DEFAULT_CURRENT_PROFILE_PATH", tmp_path / "current")
  monkeypatch.setenv("OPENVIKING_URL", "http://env-host:1933")
  monkeypatch.setenv("OPENVIKING_API_KEY", "env-key")
  monkeypatch.setenv("OPENVIKING_ACCOUNT_ID", "env-account")
  monkeypatch.setenv("OPENVIKING_USER_ID", "env-user")
  monkeypatch.setenv("OPENVIKING_TIMEOUT", "45.5")

  config = OVFSConfig.load()

  assert config.url in ("http://localhost:1933", "http://127.0.0.1:1933")
  assert config.api_key is None
  assert config.account_id is None
  assert config.user_id is None
  assert config.timeout == 30.0


def test_load_reads_profile_account_user_from_v2_config(tmp_path: Path, monkeypatch) -> None:
  config_path = tmp_path / "config.json"
  config_path.write_text(
    '{"version":2,"profiles":[{"profile":"dev","system":{"name":"Dev System"},"openviking":{"url":"http://dev:1933","api_key":"dev-key","account_id":"dev-account","user_id":"dev-user","timeout":18}}]}',
    encoding="utf-8",
  )

  monkeypatch.delenv("OPENVIKING_URL", raising=False)
  monkeypatch.delenv("OPENVIKING_API_KEY", raising=False)
  monkeypatch.delenv("OPENVIKING_ACCOUNT_ID", raising=False)
  monkeypatch.delenv("OPENVIKING_USER_ID", raising=False)
  monkeypatch.delenv("OPENVIKING_TIMEOUT", raising=False)

  config = OVFSConfig.load(config_path=str(config_path), profile="dev")

  assert config.url == "http://dev:1933"
  assert config.api_key == "dev-key"
  assert config.account_id == "dev-account"
  assert config.user_id == "dev-user"
  assert config.profile == "dev"
  assert config.system_name == "Dev System"
  assert config.timeout == 18.0


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
