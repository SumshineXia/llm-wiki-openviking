from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "llm-wiki-openviking" / "config.json"
DEFAULT_CURRENT_PROFILE_PATH = Path.home() / ".config" / "llm-wiki-openviking" / "current"


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
  if config_path:
    return Path(config_path).expanduser()
  env_path = os.getenv("LLM_WIKI_CONFIG", "").strip()
  if env_path:
    return Path(env_path).expanduser()
  return DEFAULT_CONFIG_PATH


def _read_text_file(path: Path) -> str:
  if not path.exists():
    return ""
  return path.read_text(encoding="utf-8").strip()


def _find_profile_from_parent(start: Path) -> str:
  current = start
  while True:
    marker = current / ".llm-wiki-profile"
    marker_value = _read_text_file(marker)
    if marker_value:
      return marker_value
    if current.parent == current:
      return ""
    current = current.parent


def _to_flat_config(raw: dict[str, Any], profile_name: str | None) -> dict[str, Any]:
  is_v2 = raw.get("version") == 2 and isinstance(raw.get("profiles"), list)
  if not is_v2:
    return dict(raw)

  profiles = raw.get("profiles", [])
  profile_map: dict[str, dict[str, Any]] = {}
  for item in profiles:
    if isinstance(item, dict):
      name = str(item.get("profile", "")).strip()
      if name:
        profile_map[name] = item

  env_profile = os.getenv("LLM_WIKI_PROFILE", "").strip()
  marker_profile = _find_profile_from_parent(Path.cwd())
  current_profile = _read_text_file(DEFAULT_CURRENT_PROFILE_PATH)

  selected_profile_name = (
    (profile_name or "").strip()
    or env_profile
    or marker_profile
    or current_profile
    or (str(profiles[0].get("profile", "")).strip() if profiles and isinstance(profiles[0], dict) else "")
  )

  selected_profile = profile_map.get(selected_profile_name, {})
  system = selected_profile.get("system") if isinstance(selected_profile.get("system"), dict) else {}
  openviking = selected_profile.get("openviking") if isinstance(selected_profile.get("openviking"), dict) else {}
  openai = selected_profile.get("openai") if isinstance(selected_profile.get("openai"), dict) else {}
  defaults = selected_profile.get("defaults") if isinstance(selected_profile.get("defaults"), dict) else {}

  return {
    "profile": selected_profile_name,
    "system_id": system.get("id", ""),
    "system_name": system.get("name", ""),
    "ipmp_system_num": system.get("ipmp_system_num", ""),
    "openviking_url": openviking.get("url", "http://localhost:1933"),
    "openviking_api_key": openviking.get("api_key", ""),
    "openviking_account_id": openviking.get("account_id", ""),
    "openviking_user_id": openviking.get("user_id", ""),
    "openviking_timeout": openviking.get("timeout", 30),
    "openai_base_url": openai.get("base_url", ""),
    "openai_api_key": openai.get("api_key", ""),
    "openai_model": openai.get("model", "gpt-4o-mini"),
    "default_kb_name": defaults.get("kb_name", ""),
  }


def load_config(config_path: str | None = None, profile: str | None = None) -> dict[str, Any]:
  selected_path = resolve_config_path(config_path)
  data: dict[str, Any] = {}

  if selected_path.exists():
    raw = _read_text_file(selected_path)
    if raw:
      data = json.loads(raw)

  flat = _to_flat_config(data, profile)

  return {
    "profile": flat.get("profile", ""),
    "system_id": flat.get("system_id", ""),
    "system_name": flat.get("system_name", ""),
    "ipmp_system_num": flat.get("ipmp_system_num", ""),
    "openviking_url": os.getenv("OPENVIKING_URL", flat.get("openviking_url", "http://localhost:1933")),
    "openviking_api_key": os.getenv("OPENVIKING_API_KEY", flat.get("openviking_api_key", "")),
    "openviking_account_id": os.getenv("OPENVIKING_ACCOUNT_ID", flat.get("openviking_account_id", "")),
    "openviking_user_id": os.getenv("OPENVIKING_USER_ID", flat.get("openviking_user_id", "")),
    "openviking_timeout": float(os.getenv("OPENVIKING_TIMEOUT", flat.get("openviking_timeout", 30))),
    "openai_base_url": os.getenv("OPENAI_BASE_URL", flat.get("openai_base_url", "")),
    "openai_api_key": os.getenv("OPENAI_API_KEY", flat.get("openai_api_key", "")),
    "openai_model": os.getenv("OPENAI_MODEL", flat.get("openai_model", "gpt-4o-mini")),
    "default_kb_name": flat.get("default_kb_name", ""),
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
