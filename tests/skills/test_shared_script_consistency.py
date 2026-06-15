from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
skill_names = [
  "wiki-bootstrap",
  "wiki-health",
  "wiki-ingest",
  "wiki-query",
  "wiki-lint",
  "wiki-graph",
  "wiki-upload-source",
  "wiki-profile",
  "wiki-save",
]

shared_ovfs_skill_names = [
  "wiki-bootstrap",
  "wiki-graph",
  "wiki-health",
  "wiki-lint",
  "wiki-profile",
  "wiki-query",
  "wiki-save",
  "wiki-upload-source",
]

wiki_index_skill_names = [
  "wiki-health",
  "wiki-ingest",
  "wiki-query",
  "wiki-save",
]


def test_common_py_files_are_consistent() -> None:
  contents = [
    (repo_root / "skills" / skill_name / "scripts" / "common.py").read_text(encoding="utf-8")
    for skill_name in skill_names
  ]
  assert all(text == contents[0] for text in contents)


def test_ovfs_py_files_are_consistent() -> None:
  contents = [
    (repo_root / "skills" / skill_name / "scripts" / "ovfs.py").read_text(encoding="utf-8")
    for skill_name in shared_ovfs_skill_names
  ]
  assert all(text == contents[0] for text in contents)


def test_wiki_index_py_files_are_consistent() -> None:
  contents = [
    (repo_root / "skills" / skill_name / "scripts" / "wiki_index.py").read_text(encoding="utf-8")
    for skill_name in wiki_index_skill_names
  ]
  assert all(text == contents[0] for text in contents)
