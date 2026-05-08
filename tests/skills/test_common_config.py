from pathlib import Path
import json


def test_config_example_contains_required_keys():
  path = Path("config/config.example.json")
  assert path.exists()
  data = json.loads(path.read_text(encoding="utf-8"))
  assert set(data.keys()) == {
    "openviking_url",
    "openviking_api_key",
    "openviking_timeout",
    "openai_base_url",
    "openai_api_key",
    "openai_model",
  }
