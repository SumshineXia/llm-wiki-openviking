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
