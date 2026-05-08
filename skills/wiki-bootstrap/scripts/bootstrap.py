from __future__ import annotations

import argparse
from typing import Any

from common import build_kb_root, print_json, validate_kb_name
from ovfs import OVFSClient, OVFSConfig, ensure_dir, ensure_text_file


def plan_bootstrap_paths(kbName: str) -> dict[str, list[str]]:
  valid_name = validate_kb_name(kbName)
  kb_root = build_kb_root(valid_name)

  dirs = [
    f"{kb_root}raw/",
    f"{kb_root}wiki/",
    f"{kb_root}wiki/sources/",
    f"{kb_root}wiki/entities/",
    f"{kb_root}wiki/concepts/",
    f"{kb_root}wiki/syntheses/",
    f"{kb_root}graph/",
  ]

  files = [
    f"{kb_root}wiki/index.md",
    f"{kb_root}wiki/overview.md",
    f"{kb_root}wiki/log.md",
  ]

  return {"dirs": dirs, "files": files}


def build_initial_file_content(fileUri: str) -> str:
  if fileUri.endswith("wiki/index.md"):
    return (
      "# 索引\n\n"
      "- [概览](./overview.md)\n"
      "- [操作日志](./log.md)\n\n"
      "## 资料来源\n\n"
      "## 实体\n\n"
      "## 概念\n\n"
      "## 综合结论\n"
    )
  if fileUri.endswith("wiki/overview.md"):
    return "# 概览\n\n"
  if fileUri.endswith("wiki/log.md"):
    return "# 操作日志\n\n"
  return ""


def apply_bootstrap(plan: dict[str, list[str]], config: OVFSConfig) -> None:
  with OVFSClient(config) as client:
    for dirUri in plan["dirs"]:
      ensure_dir(client, dirUri)

    for fileUri in plan["files"]:
      ensure_text_file(client, fileUri, build_initial_file_content(fileUri))


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="初始化远端知识库目录与基础页面")
  parser.add_argument("--kb-name", required=True, help="知识库名称，例如 team-a/project-x/wiki-kb")
  parser.add_argument("--dry-run", action="store_true", help="仅输出计划，不执行创建")
  parser.add_argument("--pretty", action="store_true", help="以格式化 JSON 输出")
  parser.add_argument("--config", default=None, help="配置文件路径")
  parser.add_argument("--profile", default=None, help="profile 名称")
  return parser.parse_args()


def main() -> None:
  args = parse_args()
  plan = plan_bootstrap_paths(args.kb_name)
  config = OVFSConfig.load(config_path=args.config, profile=args.profile)
  result: dict[str, Any] = {
    "kb_name": validate_kb_name(args.kb_name),
    "dry_run": bool(args.dry_run),
    "plan": plan,
  }

  if args.dry_run:
    print_json(result, args.pretty)
    return

  apply_bootstrap(plan, config)
  result["status"] = "ok"
  print_json(result, args.pretty)


if __name__ == "__main__":
  main()
