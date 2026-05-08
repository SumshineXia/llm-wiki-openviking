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
