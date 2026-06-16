from pathlib import Path


def get_skill_names() -> list[str]:
  return sorted(path.name for path in Path("skills").glob("wiki-*") if (path / "SKILL.md").exists())


def test_skill_docs_do_not_use_legacy_project_scripts_command():
  for skill_name in get_skill_names():
    skill_doc_path = Path("skills") / skill_name / "SKILL.md"
    content = skill_doc_path.read_text(encoding="utf-8")
    assert "python3 -m scripts." not in content


def test_skill_docs_reference_run_sh_entrypoint():
  for skill_name in get_skill_names():
    skill_doc_path = Path("skills") / skill_name / "SKILL.md"
    content = skill_doc_path.read_text(encoding="utf-8")
    assert "run.sh" in content


def test_skill_docs_do_not_use_skills_relative_path_command():
  for skill_name in get_skill_names():
    skill_doc_path = Path("skills") / skill_name / "SKILL.md"
    content = skill_doc_path.read_text(encoding="utf-8")
    assert "./skills/" not in content


def test_skill_docs_do_not_reference_fixed_opencode_skill_install_path():
  for skill_name in get_skill_names():
    skill_doc_path = Path("skills") / skill_name / "SKILL.md"
    content = skill_doc_path.read_text(encoding="utf-8")
    assert "~/.config/opencode/skills/" not in content
    assert "$HOME/.config/opencode/skills/" not in content


def test_skill_docs_reference_current_skill_dir_placeholder():
  for skill_name in get_skill_names():
    skill_doc_path = Path("skills") / skill_name / "SKILL.md"
    content = skill_doc_path.read_text(encoding="utf-8")
    assert "<THIS_SKILL_DIR>" in content
    assert 'bash "<THIS_SKILL_DIR>/scripts/run.sh"' in content


def test_query_doc_references_sibling_wiki_save_without_fixed_root():
  content = (Path("skills") / "wiki-query" / "SKILL.md").read_text(encoding="utf-8")
  assert '../wiki-save/scripts/run.sh' in content
  assert "~/.config/opencode/skills/wiki-save" not in content
