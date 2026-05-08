from pathlib import Path


def testReadmeContainsNaturalLanguage() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "自然语言" in readmeText


def testReadmeContainsNoNeedCloneProject() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "不需要 clone 项目" in readmeText


def testReadmeContainsSkillInstallPath() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "~/.config/opencode/skills" in readmeText


def testReadmeContainsScriptsRunPath() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert readmeText.count("/scripts/run.sh") >= 1


def testReadmeContainsCdTmpCommand() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "cd /tmp" in readmeText


def testReadmeContainsWikiHealthRunScriptPath() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "~/.config/opencode/skills/wiki-health/scripts/run.sh" in readmeText


def test_readme_contains_off_repo_debug_command() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "cd /tmp" in readmeText
  assert "~/.config/opencode/skills/wiki-health/scripts/run.sh" in readmeText
  assert "--kb-name" in readmeText
