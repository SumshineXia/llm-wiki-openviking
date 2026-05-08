import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-health" / "scripts"
ovfsPath = scriptsDir / "ovfs.py"
if str(scriptsDir) not in sys.path:
  sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_health_ovfs", ovfsPath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-health/scripts/ovfs.py")
module = module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
OVFSConfig = module.OVFSConfig


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


def test_load_prefers_env_overrides(monkeypatch) -> None:
  monkeypatch.setenv("OPENVIKING_URL", "http://env-host:1933")
  monkeypatch.setenv("OPENVIKING_API_KEY", "env-key")
  monkeypatch.setenv("OPENVIKING_TIMEOUT", "45.5")

  config = OVFSConfig.load()

  assert config.url == "http://env-host:1933"
  assert config.api_key == "env-key"
  assert config.timeout == 45.5
