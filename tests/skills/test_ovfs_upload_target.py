from pathlib import Path, PurePosixPath
import re


repo_root = Path(__file__).resolve().parents[2]
ovfs_path = repo_root / "skills" / "wiki-ingest" / "scripts" / "ovfs.py"
source = ovfs_path.read_text(encoding="utf-8")

func_match = re.search(
    r"def _resolve_upload_target_for_create\(uri: str\) -> str:(.+?)(?=\n\n|\Z)",
    source,
    re.DOTALL,
)
if not func_match:
  raise RuntimeError("无法在 ovfs.py 中找到 _resolve_upload_target_for_create")

func_body = func_match.group(0)
exec_env: dict = {"PurePosixPath": PurePosixPath}
exec(func_body, exec_env)
resolve_upload_target_for_create = exec_env["_resolve_upload_target_for_create"]


def test_same_name_child_uri_returns_parent() -> None:
  uri = "viking://resources/my-kb/wiki/overview.md/overview.md"
  result = resolve_upload_target_for_create(uri)
  assert result == "viking://resources/my-kb/wiki/overview.md/", (
    f"同名 child 应返回父目录，got {result}"
  )


def test_plain_uri_returns_self() -> None:
  uri = "viking://resources/my-kb/wiki/concepts/new-thing.md"
  result = resolve_upload_target_for_create(uri)
  assert result == uri, f"普通 URI 应返回自身，got {result}"


def test_plain_uri_with_non_md_extension_returns_self() -> None:
  uri = "viking://resources/my-kb/graph/graph.json"
  result = resolve_upload_target_for_create(uri)
  assert result == uri, f"非 .md URI 应返回自身，got {result}"


def test_deep_same_name_child_returns_parent() -> None:
  uri = "viking://resources/my-kb/wiki/entities/foo.md/foo.md"
  result = resolve_upload_target_for_create(uri)
  assert result == "viking://resources/my-kb/wiki/entities/foo.md/", (
    f"深层同名 child 应返回父目录，got {result}"
  )


def test_no_false_positive_on_unrelated_child() -> None:
  uri = "viking://resources/my-kb/wiki/overview.md/other.md"
  result = resolve_upload_target_for_create(uri)
  assert result == uri, (
    f"不同名 child 应返回 URI 自身，got {result}"
  )


def test_source_page_same_name_child_returns_parent() -> None:
  uri = "viking://resources/my-kb/wiki/sources/doc.md/doc.md"
  result = resolve_upload_target_for_create(uri)
  assert result == "viking://resources/my-kb/wiki/sources/doc.md/", (
    f"source 页面同名 child 应返回父目录，got {result}"
  )
