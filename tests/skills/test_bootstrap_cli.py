import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess
import sys


repo_root = Path(__file__).resolve().parents[2]
scripts_dir = repo_root / "skills" / "wiki-bootstrap" / "scripts"
module_path = scripts_dir / "bootstrap.py"
sys.path.insert(0, str(scripts_dir))
spec = spec_from_file_location("wiki_bootstrap_cli", module_path)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-bootstrap/scripts/bootstrap.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
plan_bootstrap_paths = module.plan_bootstrap_paths
build_initial_file_content = module.build_initial_file_content
ensure_bootstrap_text_file = module.ensure_bootstrap_text_file
apply_bootstrap = module.apply_bootstrap
parse_args = module.parse_args


def test_plan_bootstrap_paths_contains_required_dirs_and_files() -> None:
  plan = plan_bootstrap_paths("team-a/project-x/wiki-kb")

  assert "dirs" in plan
  assert "files" in plan

  assert "viking://resources/team-a/project-x/wiki-kb/raw/" in plan["dirs"]
  assert "viking://resources/team-a/project-x/wiki-kb/wiki/" in plan["dirs"]
  assert "viking://resources/team-a/project-x/wiki-kb/wiki/sources/" in plan["dirs"]
  assert "viking://resources/team-a/project-x/wiki-kb/wiki/entities/" in plan["dirs"]
  assert "viking://resources/team-a/project-x/wiki-kb/wiki/concepts/" in plan["dirs"]
  assert "viking://resources/team-a/project-x/wiki-kb/wiki/syntheses/" in plan["dirs"]
  assert "viking://resources/team-a/project-x/wiki-kb/graph/" in plan["dirs"]

  assert "viking://resources/team-a/project-x/wiki-kb/wiki/index.md" in plan["files"]
  assert "viking://resources/team-a/project-x/wiki-kb/wiki/overview.md" in plan["files"]
  assert "viking://resources/team-a/project-x/wiki-kb/wiki/log.md" in plan["files"]


def test_bootstrap_cli_dry_run_outputs_required_structure() -> None:
  process = subprocess.run(
    [
      "python3",
      str(module_path),
      "--kb-name",
      "team-a/project-x/wiki-kb",
      "--dry-run",
    ],
    check=True,
    capture_output=True,
    text=True,
  )
  data = json.loads(process.stdout)

  assert "kb_name" in data
  assert "dry_run" in data
  assert "plan" in data
  assert "dirs" in data["plan"]
  assert "files" in data["plan"]


def test_build_initial_file_content_uses_chinese_root_templates() -> None:
  kb_root = "viking://resources/team-a/project-x/wiki-kb/"

  index_content = build_initial_file_content(f"{kb_root}wiki/index.md")
  overview_content = build_initial_file_content(f"{kb_root}wiki/overview.md")
  log_content = build_initial_file_content(f"{kb_root}wiki/log.md")

  assert "# 索引" in index_content
  assert "## 资料来源" in index_content
  assert "## 实体" in index_content
  assert "## 概念" in index_content
  assert "## 综合结论" in index_content

  assert overview_content.startswith("# 概览")
  assert log_content.startswith("# 操作日志")


def test_parse_args_supports_config_and_profile(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "bootstrap.py",
      "--kb-name",
      "team-a/project-x/wiki-kb",
      "--config",
      "/tmp/config.json",
      "--profile",
      "p1",
    ],
  )

  args = parse_args()

  assert args.config == "/tmp/config.json"
  assert args.profile == "p1"


def test_ensure_bootstrap_text_file_defaults_to_async_wait_false() -> None:
  class FakeClient:
    def __init__(self) -> None:
      self.write_calls = []

    def exists(self, uri: str) -> bool:
      return False

    def write_text(self, uri: str, content: str, create: bool = False, wait: bool = True):
      self.write_calls.append(
        {
          "uri": uri,
          "content": content,
          "create": create,
          "wait": wait,
        }
      )

  client = FakeClient()
  uri = "viking://resources/demo/wiki/index.md"
  content = "# 索引\n\n"

  ensure_bootstrap_text_file(client, uri, content)

  assert client.write_calls == [
    {
      "uri": uri,
      "content": content,
      "create": True,
      "wait": False,
    }
  ]


def test_apply_bootstrap_passes_wait_for_indexing_true_to_page_writes(monkeypatch) -> None:
  dir_calls = []
  file_calls = []

  class FakeClient:
    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc, tb):
      return None

  def fake_ovfs_client(config):
    return FakeClient()

  def fake_ensure_dir(client, uri):
    dir_calls.append(uri)

  def fake_ensure_bootstrap_text_file(client, uri, content, *, waitForIndexing):
    file_calls.append(
      {
        "uri": uri,
        "content": content,
        "waitForIndexing": waitForIndexing,
      }
    )

  monkeypatch.setattr(module, "OVFSClient", fake_ovfs_client)
  monkeypatch.setattr(module, "ensure_dir", fake_ensure_dir)
  monkeypatch.setattr(module, "ensure_bootstrap_text_file", fake_ensure_bootstrap_text_file)

  plan = {
    "dirs": ["viking://resources/demo/raw/"],
    "files": [
      "viking://resources/demo/wiki/index.md",
      "viking://resources/demo/wiki/overview.md",
    ],
  }

  apply_bootstrap(plan, config=object(), waitForIndexing=True)

  assert dir_calls == ["viking://resources/demo/raw/"]
  assert [item["uri"] for item in file_calls] == plan["files"]
  assert all(item["waitForIndexing"] is True for item in file_calls)


def test_parse_args_supports_wait_for_indexing(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "bootstrap.py",
      "--kb-name",
      "team-a/project-x/wiki-kb",
      "--wait-for-indexing",
    ],
  )

  args = parse_args()

  assert args.wait_for_indexing is True
