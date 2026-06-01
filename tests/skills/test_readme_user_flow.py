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


def testReadmeContainsChineseFirstConvention() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "页面标题和正文默认生成中文" in readmeText


def testReadmeContainsEnglishReservedTermsConvention() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "技术术语、路径、命令、API 名保留英文" in readmeText


def testReadmeContainsCliAndJsonStabilityConvention() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "保持 CLI 参数、目录结构、JSON 字段名不变。" in readmeText


def testReadmeContainsWikiUploadSourceAndWikiSaveInstallEntries() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "skills/wiki-upload-source" in readmeText
  assert "skills/wiki-save" in readmeText


def testReadmeContainsQueryConfirmThenWikiSaveFlow() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "query -> 确认 -> wiki-save" in readmeText
  assert "legacy `wiki-query --save` 会重新检索并再次调用 LLM" in readmeText


def testReadmeDoesNotClaimSevenCommonSkills() -> None:
  readmePath = Path(__file__).resolve().parents[2] / "README.md"
  readmeText = readmePath.read_text(encoding="utf-8")
  assert "7 个常用 skill" not in readmeText
