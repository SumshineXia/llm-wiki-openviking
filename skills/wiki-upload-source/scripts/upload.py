from __future__ import annotations

import argparse
import posixpath
from pathlib import Path
from typing import Any

from common import build_error_result, build_kb_root, normalize_viking_uri, print_json, validate_kb_name
from ovfs import OVFSClient, OVFSConfig


def validate_upload_target(target: str) -> str:
  normalized = target.strip().lstrip("/")
  if not normalized:
    raise ValueError("--to 不能为空")
  if ".." in normalized:
    raise ValueError("--to 不能包含 ..")
  if "//" in normalized:
    raise ValueError("--to 不能包含 //")
  if normalized == "raw/":
    raise ValueError("--to 必须包含文件名")
  normalizedPath = posixpath.normpath(normalized)
  if not normalizedPath.startswith("raw/"):
    raise ValueError("--to 归一化后必须在 raw/ 下")
  if not normalized.startswith("raw/"):
    raise ValueError("--to 必须以 raw/ 开头")
  return normalizedPath


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="上传本地文件到 KB raw/ 目录")
  parser.add_argument("--kb-name", required=True, help="知识库名称")
  parser.add_argument("--file", required=True, help="本地文件路径")
  parser.add_argument("--to", required=True, help="上传目标相对路径，必须以 raw/ 开头")
  parser.add_argument("--wait", action="store_true", help="等待远端写入完成后再返回")
  parser.add_argument("--config", default=None, help="配置文件路径")
  parser.add_argument("--profile", default=None, help="profile 名称")
  parser.add_argument("--pretty", action="store_true", help="格式化输出 JSON")
  return parser.parse_args()


def runUpload(
  kbName: str,
  sourceFile: str,
  target: str,
  waitForCompletion: bool = False,
  configPath: str | None = None,
  profile: str | None = None,
) -> dict[str, Any]:
  normalizedKbName = validate_kb_name(kbName)
  sourcePath = Path(sourceFile).expanduser().resolve()
  if not sourcePath.exists() or not sourcePath.is_file():
    raise ValueError(f"--file 指向的文件不存在: {sourcePath}")

  normalizedTarget = validate_upload_target(target)
  kbRoot = build_kb_root(normalizedKbName)
  targetUri = normalize_viking_uri(normalizedKbName, normalizedTarget)

  config = OVFSConfig.load(config_path=configPath, profile=profile)
  with OVFSClient(config) as client:
    client.add_local_resource(file_path=str(sourcePath), to=targetUri, wait=waitForCompletion)

  return {
    "kb_name": normalizedKbName,
    "kb_root": kbRoot,
    "source_file": str(sourcePath),
    "target_uri": targetUri,
    "suggested_ingest_uri": targetUri,
    "next_step": "可使用 suggested_ingest_uri 调用 wiki-ingest。OpenViking 可能会将该资源转换为同名目录 bundle，wiki-ingest 会自动递归查找正文 markdown。",
    "wait": waitForCompletion,
    "uploaded": True,
  }


def main() -> int:
  args = parse_args()
  try:
    result = runUpload(
      args.kb_name,
      args.file,
      args.to,
      waitForCompletion=args.wait,
      configPath=args.config,
      profile=args.profile,
    )
    print_json(result, pretty=args.pretty)
    return 0
  except Exception as exc:
    print_json(build_error_result(exc), pretty=args.pretty)
    return 1


if __name__ == "__main__":
  raise SystemExit(main())
