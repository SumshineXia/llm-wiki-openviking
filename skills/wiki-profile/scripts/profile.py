from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from common import DEFAULT_CURRENT_PROFILE_PATH, resolve_config_path


def _read_text_file(path: Path) -> str:
  if not path.exists():
    return ""
  return path.read_text(encoding="utf-8").strip()


def _find_profile_marker(start: Path) -> tuple[str, Path | None]:
  current = start
  while True:
    marker = current / ".llm-wiki-profile"
    marker_value = _read_text_file(marker)
    if marker_value:
      return marker_value, marker
    if current.parent == current:
      return "", None
    current = current.parent


def _load_raw_config(config_path: str | None) -> dict[str, Any]:
  selected_path = resolve_config_path(config_path)
  if not selected_path.exists():
    return {}
  raw_text = _read_text_file(selected_path)
  if not raw_text:
    return {}
  raw_data = json.loads(raw_text)
  if not isinstance(raw_data, dict):
    raise ValueError(f"配置必须是 JSON 对象: {selected_path}")
  return raw_data


def _list_profiles(config: dict[str, Any]) -> list[str]:
  profiles = config.get("profiles")
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


def _mask_secret(value: str) -> str:
  if len(value) <= 8:
    return "*" * len(value)
  return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def _get_selected_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
  profiles = config.get("profiles")
  if not isinstance(profiles, list):
    raise ValueError("配置中缺少 profiles 列表")
  for item in profiles:
    if not isinstance(item, dict):
      continue
    if str(item.get("profile", "")).strip() == profile_name:
      return item
  raise ValueError(f"profile 不存在: {profile_name}")


def _resolve_current_profile(cli_profile: str | None, config: dict[str, Any]) -> tuple[str, str]:
  config_profiles = _list_profiles(config)
  if cli_profile and cli_profile.strip():
    return cli_profile.strip(), "--profile"

  env_profile = os.getenv("LLM_WIKI_PROFILE", "").strip()
  if env_profile:
    return env_profile, "LLM_WIKI_PROFILE"

  marker_profile, marker_path = _find_profile_marker(Path.cwd())
  if marker_profile:
    _ = marker_path
    return marker_profile, ".llm-wiki-profile"

  current_profile = _read_text_file(DEFAULT_CURRENT_PROFILE_PATH)
  if current_profile:
    return current_profile, "current"

  if config_profiles:
    return config_profiles[0], "profiles[0]"

  return "", "profiles[0]"


def _write_current_profile(profile_name: str) -> Path:
  DEFAULT_CURRENT_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
  DEFAULT_CURRENT_PROFILE_PATH.write_text(profile_name + "\n", encoding="utf-8")
  return DEFAULT_CURRENT_PROFILE_PATH


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="管理 llm-wiki-openviking 的 profile 选择")
  parser.add_argument("--config", default=None, help="配置文件路径，默认读取 LLM_WIKI_CONFIG 或 ~/.config/llm-wiki-openviking/config.json")
  parser.add_argument("--profile", default=None, help="显式指定 profile 名称（仅影响本次命令）")
  parser.add_argument("--pretty", action="store_true", help="格式化输出 JSON")

  subparsers = parser.add_subparsers(dest="command", required=True)
  subparsers.add_parser("list", help="列出所有 profile")
  subparsers.add_parser("current", help="显示当前生效 profile 及来源")

  use_parser = subparsers.add_parser("use", help="将某个 profile 设为 current")
  use_parser.add_argument("name", help="profile 名称")

  show_parser = subparsers.add_parser("show", help="显示指定 profile 的详细信息")
  show_parser.add_argument("name", nargs="?", default=None, help="profile 名称，缺省则显示当前生效 profile")

  bind_parser = subparsers.add_parser("bind", help="在目录写入 .llm-wiki-profile")
  bind_parser.add_argument("name", help="profile 名称")
  bind_parser.add_argument("--dir", default=".", help="绑定目录，默认当前目录")

  unbind_parser = subparsers.add_parser("unbind", help="删除目录中的 .llm-wiki-profile")
  unbind_parser.add_argument("--dir", default=".", help="解绑目录，默认当前目录")

  return parser.parse_args()


def _print_json(payload: dict[str, Any], pretty: bool) -> None:
  if pretty:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return
  print(json.dumps(payload, ensure_ascii=False))


def main() -> int:
  args = parse_args()
  config_path = str(resolve_config_path(args.config))
  config = _load_raw_config(args.config)
  profiles = _list_profiles(config)

  if args.command == "list":
    _print_json({"status": "ok", "config_path": config_path, "profiles": profiles}, args.pretty)
    return 0

  if args.command == "current":
    profile_name, source = _resolve_current_profile(args.profile, config)
    _print_json(
      {
        "status": "ok",
        "config_path": config_path,
        "profile": profile_name,
        "source": source,
      },
      args.pretty,
    )
    return 0

  if args.command == "use":
    _get_selected_profile(config, args.name)
    current_path = _write_current_profile(args.name)
    _print_json(
      {
        "status": "ok",
        "config_path": config_path,
        "profile": args.name,
        "current_path": str(current_path),
      },
      args.pretty,
    )
    return 0

  if args.command == "show":
    target_name = args.name
    if not target_name:
      target_name, _ = _resolve_current_profile(args.profile, config)
    profile = _get_selected_profile(config, target_name)
    openai = profile.get("openai") if isinstance(profile.get("openai"), dict) else {}
    openviking = profile.get("openviking") if isinstance(profile.get("openviking"), dict) else {}

    masked_openai = dict(openai)
    if isinstance(masked_openai.get("api_key"), str):
      masked_openai["api_key"] = _mask_secret(masked_openai["api_key"])
    masked_openviking = dict(openviking)
    if isinstance(masked_openviking.get("api_key"), str):
      masked_openviking["api_key"] = _mask_secret(masked_openviking["api_key"])

    masked_profile = dict(profile)
    masked_profile["openai"] = masked_openai
    masked_profile["openviking"] = masked_openviking

    _print_json(
      {
        "status": "ok",
        "config_path": config_path,
        "profile": target_name,
        "data": masked_profile,
      },
      args.pretty,
    )
    return 0

  if args.command == "bind":
    _get_selected_profile(config, args.name)
    bind_dir = Path(args.dir).expanduser().resolve()
    bind_dir.mkdir(parents=True, exist_ok=True)
    marker_path = bind_dir / ".llm-wiki-profile"
    marker_path.write_text(args.name + "\n", encoding="utf-8")
    _print_json(
      {
        "status": "ok",
        "profile": args.name,
        "marker": str(marker_path),
      },
      args.pretty,
    )
    return 0

  if args.command == "unbind":
    bind_dir = Path(args.dir).expanduser().resolve()
    marker_path = bind_dir / ".llm-wiki-profile"
    removed = False
    if marker_path.exists():
      marker_path.unlink()
      removed = True
    _print_json(
      {
        "status": "ok",
        "marker": str(marker_path),
        "removed": removed,
      },
      args.pretty,
    )
    return 0

  raise ValueError(f"不支持的命令: {args.command}")


if __name__ == "__main__":
  raise SystemExit(main())
