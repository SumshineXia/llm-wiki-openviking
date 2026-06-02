from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import (
    ConfigError,
    build_error_result,
    find_profile_marker,
    get_profile_by_name,
    list_profiles,
    load_raw_config,
    mask_secret,
    print_json,
    read_text_file,
    resolve_config_path,
    select_profile_name,
)


def _build_profile_map(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in raw.get("profiles", []):
        if isinstance(item, dict):
            name = str(item.get("profile", "")).strip()
            if name:
                result[name] = item
    return result


def _validate_profile_usable(raw: dict[str, Any], name: str) -> dict[str, Any]:
    profile = get_profile_by_name(raw, name)
    openviking = profile.get("openviking") if isinstance(profile.get("openviking"), dict) else {}
    if not str(openviking.get("url") or "").strip():
        raise ConfigError(f"profile {name} 缺少 openviking.url，不能 use/bind")
    return profile


def _write_current_profile(profile_name: str) -> Path:
    from common import DEFAULT_CURRENT_PROFILE_PATH
    DEFAULT_CURRENT_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CURRENT_PROFILE_PATH.write_text(profile_name + "\n", encoding="utf-8")
    return DEFAULT_CURRENT_PROFILE_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="管理 llm-wiki-openviking 的 profile 选择")
    parser.add_argument("--config", default=None, help="配置文件路径，默认读取 ~/.config/llm-wiki-openviking/config.json")
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


def main() -> int:
    args = parse_args()

    try:
        raw, config_file_path = load_raw_config(args.config)
        config_path_str = str(config_file_path)

        if args.command == "list":
            names = list_profiles(raw)
            print_json({"status": "ok", "config_path": config_path_str, "profiles": names}, args.pretty)
            return 0

        if args.command == "current":
            profile_map = _build_profile_map(raw)
            profile_name, source = select_profile_name(args.profile, profile_map)
            get_profile_by_name(raw, profile_name)
            print_json(
                {"status": "ok", "config_path": config_path_str, "profile": profile_name, "source": source},
                args.pretty,
            )
            return 0

        if args.command == "use":
            _validate_profile_usable(raw, args.name)
            current_path = _write_current_profile(args.name)
            print_json(
                {"status": "ok", "config_path": config_path_str, "profile": args.name, "current_path": str(current_path)},
                args.pretty,
            )
            return 0

        if args.command == "show":
            if args.name:
                target_name = args.name
                profile_source = "argument"
            else:
                profile_map = _build_profile_map(raw)
                target_name, profile_source = select_profile_name(args.profile, profile_map)
            profile = get_profile_by_name(raw, target_name)

            openai = profile.get("openai") if isinstance(profile.get("openai"), dict) else {}
            openviking = profile.get("openviking") if isinstance(profile.get("openviking"), dict) else {}

            masked_openai = dict(openai)
            if isinstance(masked_openai.get("api_key"), str):
                masked_openai["api_key"] = mask_secret(masked_openai["api_key"])
            masked_openviking = dict(openviking)
            if isinstance(masked_openviking.get("api_key"), str):
                masked_openviking["api_key"] = mask_secret(masked_openviking["api_key"])

            masked_profile = dict(profile)
            masked_profile["openai"] = masked_openai
            masked_profile["openviking"] = masked_openviking

            openviking_url = ""
            if isinstance(openviking, dict) and isinstance(openviking.get("url"), str):
                openviking_url = openviking["url"]

            print_json(
                {
                    "status": "ok",
                    "config_path": config_path_str,
                    "profile": target_name,
                    "profile_source": profile_source,
                    "openviking_url": openviking_url,
                    "data": masked_profile,
                },
                args.pretty,
            )
            return 0

        if args.command == "bind":
            _validate_profile_usable(raw, args.name)
            bind_dir = Path(args.dir).expanduser().resolve()
            bind_dir.mkdir(parents=True, exist_ok=True)
            marker_path = bind_dir / ".llm-wiki-profile"
            marker_path.write_text(args.name + "\n", encoding="utf-8")
            print_json({"status": "ok", "profile": args.name, "marker": str(marker_path)}, args.pretty)
            return 0

        if args.command == "unbind":
            bind_dir = Path(args.dir).expanduser().resolve()
            marker_path = bind_dir / ".llm-wiki-profile"
            removed = False
            if marker_path.exists():
                marker_path.unlink()
                removed = True
            print_json({"status": "ok", "marker": str(marker_path), "removed": removed}, args.pretty)
            return 0

        raise ValueError(f"不支持的命令: {args.command}")

    except Exception as exc:
        print_json(build_error_result(exc), args.pretty)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
