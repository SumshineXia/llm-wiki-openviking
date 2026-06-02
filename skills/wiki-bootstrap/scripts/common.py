from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "llm-wiki-openviking" / "config.json"
DEFAULT_CURRENT_PROFILE_PATH = Path.home() / ".config" / "llm-wiki-openviking" / "current"


class ConfigError(ValueError):
    pass


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
    return DEFAULT_CONFIG_PATH


def read_text_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def find_profile_marker(start: Path | None = None) -> tuple[str, Path | None]:
    current = start or Path.cwd()
    while True:
        marker = current / ".llm-wiki-profile"
        marker_value = read_text_file(marker)
        if marker_value:
            return marker_value, marker
        if current.parent == current:
            return "", None
        current = current.parent


def list_profiles(raw: dict[str, Any]) -> list[str]:
    profiles = raw.get("profiles")
    if not isinstance(profiles, list):
        return []
    result: list[str] = []
    for item in profiles:
        if not isinstance(item, dict):
            continue
        name = str(item.get("profile", "")).strip()
        if name:
            result.append(name)
    return result


def select_profile_name(
    profile_name: str | None,
    profile_map: dict[str, dict[str, Any]],
    start_dir: Path | None = None,
) -> tuple[str, str]:
    if profile_name and profile_name.strip():
        return profile_name.strip(), "--profile"

    env_profile = os.getenv("LLM_WIKI_PROFILE", "").strip()
    if env_profile:
        return env_profile, "LLM_WIKI_PROFILE"

    marker_profile, _ = find_profile_marker(start_dir)
    if marker_profile:
        return marker_profile, ".llm-wiki-profile"

    current_profile = read_text_file(DEFAULT_CURRENT_PROFILE_PATH)
    if current_profile:
        return current_profile, "current"

    names = sorted(profile_map.keys())
    if len(names) == 1:
        return names[0], "single-profile"

    if len(names) > 1:
        raise ConfigError(
            "配置中存在多个 profile，请使用 --profile、wiki-profile use <name> 或 wiki-profile bind <name>；"
            f"available_profiles={names}"
        )

    raise ConfigError("配置中未找到任何 profile")


def get_profile_by_name(raw: dict[str, Any], name: str) -> dict[str, Any]:
    profiles = raw.get("profiles")
    if not isinstance(profiles, list):
        raise ConfigError("配置中缺少 profiles 列表")
    for item in profiles:
        if not isinstance(item, dict):
            continue
        if str(item.get("profile", "")).strip() == name:
            return item
    available = list_profiles(raw)
    raise ConfigError(
        f"profile 不存在: {name}; available_profiles={available}"
    )


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def load_raw_config(config_path: str | None = None) -> tuple[dict[str, Any], Path]:
    selected_path = resolve_config_path(config_path)
    if not selected_path.exists():
        raise ConfigError(f"配置文件不存在: {selected_path}")
    raw_text = read_text_file(selected_path)
    if not raw_text:
        raise ConfigError(f"配置文件为空: {selected_path}")
    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件 JSON 非法: {selected_path}; {exc}") from exc
    if not isinstance(raw_data, dict):
        raise ConfigError(f"配置文件必须是 JSON 对象: {selected_path}")
    return raw_data, selected_path


def _build_profile_map(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = raw.get("profiles", [])
    profile_map: dict[str, dict[str, Any]] = {}
    for item in profiles:
        if isinstance(item, dict):
            name = str(item.get("profile", "")).strip()
            if name:
                profile_map[name] = item
    return profile_map


def parse_openviking_timeout(value: Any, config_path: Path) -> float:
    try:
        return float(value if value is not None else 30)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"openviking_timeout 非法: {value}; config={config_path}"
        ) from exc


def _normalize_flat_config(flat: dict[str, Any], config_path: Path) -> dict[str, Any]:
    flat["openviking_timeout"] = parse_openviking_timeout(
        flat.get("openviking_timeout", 30), config_path
    )
    return flat


def _to_flat_config(
    raw: dict[str, Any],
    profile_name: str | None,
    config_path: Path,
    start_dir: Path | None = None,
) -> dict[str, Any]:
    is_v2 = raw.get("version") == 2 and isinstance(raw.get("profiles"), list)
    if not is_v2:
        url = str(raw.get("openviking_url") or "").strip()
        if not url:
            raise ConfigError(f"flat config 缺少 openviking_url; config={config_path}")
        return _normalize_flat_config(dict(raw), config_path)

    profile_map = _build_profile_map(raw)

    if not profile_map:
        raise ConfigError(f"v2 config 中 profiles 为空; config={config_path}")

    selected_profile_name, profile_source = select_profile_name(
        profile_name, profile_map, start_dir
    )

    if selected_profile_name not in profile_map:
        raise ConfigError(
            f"profile 不存在: {selected_profile_name}; "
            f"available_profiles={sorted(profile_map.keys())}; "
            f"config={config_path}"
        )

    selected_profile = profile_map[selected_profile_name]
    system = selected_profile.get("system") if isinstance(selected_profile.get("system"), dict) else {}
    openviking = selected_profile.get("openviking") if isinstance(selected_profile.get("openviking"), dict) else {}
    openai = selected_profile.get("openai") if isinstance(selected_profile.get("openai"), dict) else {}
    defaults = selected_profile.get("defaults") if isinstance(selected_profile.get("defaults"), dict) else {}

    openviking_url = str(openviking.get("url") or "").strip()
    if not openviking_url:
        raise ConfigError(
            f"profile {selected_profile_name} 缺少 openviking.url; config={config_path}"
        )

    return {
        "profile": selected_profile_name,
        "profile_source": profile_source,
        "config_path": str(config_path),
        "system_id": system.get("id", ""),
        "system_name": system.get("name", ""),
        "ipmp_system_num": system.get("ipmp_system_num", ""),
        "openviking_url": openviking_url,
        "openviking_api_key": openviking.get("api_key", ""),
        "openviking_account_id": openviking.get("account_id", ""),
        "openviking_user_id": openviking.get("user_id", ""),
        "openviking_timeout": parse_openviking_timeout(openviking.get("timeout", 30), config_path),
        "openai_base_url": openai.get("base_url", ""),
        "openai_api_key": openai.get("api_key", ""),
        "openai_model": openai.get("model", "gpt-4o-mini"),
        "default_kb_name": defaults.get("kb_name", ""),
    }


def load_config(
    config_path: str | None = None,
    profile: str | None = None,
    start_dir: Path | None = None,
) -> dict[str, Any]:
    selected_path = resolve_config_path(config_path)

    if not selected_path.exists():
        raise ConfigError(f"配置文件不存在: {selected_path}")

    raw_text = read_text_file(selected_path)
    if not raw_text:
        raise ConfigError(f"配置文件为空: {selected_path}")

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件 JSON 非法: {selected_path}; {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"配置文件必须是 JSON 对象: {selected_path}")

    return _to_flat_config(data, profile, selected_path, start_dir)


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


def build_error_result(exc: Exception, **context: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "error",
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }
    for k, v in context.items():
        if v not in (None, ""):
            payload[k] = v
    return payload
