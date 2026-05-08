from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "llm-wiki-openviking" / "config.json"


def validate_kb_name(kbName: str) -> str:
  normalized = kbName.strip()
  if not normalized:
    raise ValueError("--kb-name 不能为空")
  if ".." in normalized or "//" in normalized:
    raise ValueError("--kb-name 不能包含 .. 或 //")
  if normalized.startswith("/") or normalized.endswith("/"):
    raise ValueError("--kb-name 不能以 / 开头或结尾")
  return normalized


def build_kb_root(kbName: str) -> str:
  valid_name = validate_kb_name(kbName)
  return f"viking://resources/{valid_name}/"


def resolve_config_path(config_path: str | None = None) -> Path:
  if config_path is None:
    return DEFAULT_CONFIG_PATH
  return Path(config_path).expanduser()


def load_config(config_path: str | None = None) -> dict[str, Any]:
  selected_path = resolve_config_path(config_path)
  data: dict[str, Any] = {}

  if selected_path.exists():
    raw = selected_path.read_text(encoding="utf-8").strip()
    if raw:
      data = json.loads(raw)

  return {
    "openviking_url": os.getenv("OPENVIKING_URL", data.get("openviking_url", "http://localhost:1933")),
    "openviking_api_key": os.getenv("OPENVIKING_API_KEY", data.get("openviking_api_key", "")),
    "openviking_timeout": float(os.getenv("OPENVIKING_TIMEOUT", data.get("openviking_timeout", 30))),
    "openai_base_url": os.getenv("OPENAI_BASE_URL", data.get("openai_base_url", "")),
    "openai_api_key": os.getenv("OPENAI_API_KEY", data.get("openai_api_key", "")),
    "openai_model": os.getenv("OPENAI_MODEL", data.get("openai_model", "gpt-4o-mini")),
  }


def normalize_viking_uri(kbName: str, pathOrUri: str) -> str:
  kb_root = build_kb_root(kbName)
  normalized_path = pathOrUri.strip()

  if normalized_path.startswith("viking://"):
    return normalized_path

  if not normalized_path:
    return kb_root

  rel_path = normalized_path.lstrip("/")
  return f"{kb_root}{rel_path}"


def print_json(obj: dict[str, Any], pretty: bool) -> None:
  if pretty:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return
  print(json.dumps(obj, ensure_ascii=False))
