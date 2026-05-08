from pathlib import Path


SKILL_MAIN_MAP = {
  "wiki-bootstrap": "bootstrap.py",
  "wiki-upload-source": "upload.py",
  "wiki-ingest": "ingest.py",
  "wiki-query": "query.py",
  "wiki-health": "health.py",
  "wiki-lint": "lint.py",
  "wiki-graph": "graph.py",
}


def test_all_skills_have_run_sh():
  for skill_name in SKILL_MAIN_MAP:
    run_path = Path("skills") / skill_name / "scripts" / "run.sh"
    assert run_path.exists()
    assert run_path.stat().st_mode & 0o111


def test_run_sh_invokes_expected_main_script():
  for skill_name, main_file in SKILL_MAIN_MAP.items():
    run_path = Path("skills") / skill_name / "scripts" / "run.sh"
    content = run_path.read_text(encoding="utf-8")
    assert f"$SKILL_DIR/scripts/{main_file}" in content


def test_run_sh_checks_main_script_exists_before_exec():
  for skill_name, main_file in SKILL_MAIN_MAP.items():
    run_path = Path("skills") / skill_name / "scripts" / "run.sh"
    content = run_path.read_text(encoding="utf-8")
    assert "if [ ! -f" in content
    assert f'"$SKILL_DIR/scripts/{main_file}"' in content
    assert "Missing target script:" in content
    assert " >&2" in content
    assert "exit 1" in content
