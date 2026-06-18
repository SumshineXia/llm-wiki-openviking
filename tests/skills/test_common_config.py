from pathlib import Path
import json


def test_config_example_contains_required_keys() -> None:
  path = Path("config/config.example.json")
  assert path.exists()
  data = json.loads(path.read_text(encoding="utf-8"))
  assert data.get("version") == 2
  profiles = data.get("profiles")
  assert isinstance(profiles, list)
  assert len(profiles) >= 1

  first = profiles[0]
  assert isinstance(first, dict)
  assert "profile" in first
  assert "openviking" in first
  assert "openai" in first

  system = first.get("system")
  assert isinstance(system, dict)
  assert "id" not in system
  assert "defaults" not in first

  raw = path.read_text(encoding="utf-8")
  assert "default_kb_name" not in raw
  assert "wiki-kb" not in raw
  assert "[http://" not in raw
  assert "[https://" not in raw
