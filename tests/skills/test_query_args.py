from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re
import sys


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-query" / "scripts"
modulePath = scriptsDir / "query.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_query_script", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-query/scripts/query.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
buildSynthesisTarget = module.build_synthesis_target
normalizeSynthesisTitle = module.normalize_synthesis_title
parseArgs = module.parse_args


def test_build_synthesis_target_with_slug() -> None:
  assert buildSynthesisTarget("abc", "ignored") == "wiki/syntheses/abc.md"


def test_build_synthesis_target_explicit_slug_no_timestamp() -> None:
  target = buildSynthesisTarget("manual-title", "四层记忆机制解析")
  assert target == "wiki/syntheses/manual-title.md"


def test_build_synthesis_target_from_synthesis_title() -> None:
  target = buildSynthesisTarget(None, "四层记忆机制解析")
  assert target.startswith("wiki/syntheses/四层记忆机制解析-")
  assert re.fullmatch(r"wiki/syntheses/.+-\d{8}-\d{6}\.md", target)


def test_build_synthesis_target_not_from_question() -> None:
  target = buildSynthesisTarget(None, "四层记忆机制解析")
  assert "这份文档" not in target
  assert "核心目标" not in target


def test_build_synthesis_target_fallback_title() -> None:
  target = buildSynthesisTarget(None, "")
  assert target.startswith("wiki/syntheses/综合结论-")
  assert re.fullmatch(r"wiki/syntheses/.+-\d{8}-\d{6}\.md", target)


def test_build_synthesis_target_empty_title_not_question() -> None:
  target = buildSynthesisTarget(None, "")
  assert "综合结论" in target
  assert "核心目标" not in target


def test_build_synthesis_target_banned_prefix_removed() -> None:
  target = buildSynthesisTarget(None, "这份文档的核心目标是什么")
  stem = target.split("/")[-1]
  assert not stem.startswith("这份文档"), f"去掉空泛前缀，got {stem}"


def test_normalize_synthesis_title_basic() -> None:
  assert normalizeSynthesisTitle("四层记忆机制解析") == "四层记忆机制解析"


def test_normalize_synthesis_title_strips_markdown() -> None:
  assert normalizeSynthesisTitle("### 四层记忆机制解析") == "四层记忆机制解析"


def test_normalize_synthesis_title_removes_banned_prefix() -> None:
  result = normalizeSynthesisTitle("这份文档的核心目标是四层记忆机制解析")
  assert "四层记忆" in result
  assert not result.startswith("这份文档"), f"前缀未去除，got {result}"
  assert not result.startswith(("的", "是")), f"残留助词，got {result}"


def test_normalize_synthesis_title_no_dangling_particle() -> None:
  assert not normalizeSynthesisTitle("这个问题是四层记忆").startswith("是")


def test_normalize_synthesis_title_no_dangling_de() -> None:
  assert not normalizeSynthesisTitle("这份文档的机制").startswith("的")


def test_normalize_synthesis_title_empty_falls_back() -> None:
  result = normalizeSynthesisTitle("", fallback="综合结论")
  assert result == "综合结论"


def test_normalize_synthesis_title_truncates() -> None:
  long_title = "这是一段非常长的标题它超过了十五个汉字的限制"
  result = normalizeSynthesisTitle(long_title, max_chars=15)
  assert len(result) <= 15


def test_normalize_synthesis_title_fallback() -> None:
  assert normalizeSynthesisTitle("", fallback="默认标题") == "默认标题"
  assert normalizeSynthesisTitle("关于", fallback="默认标题") == "默认标题"


def test_parse_args_supports_config_and_profile(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "query.py",
      "--kb-name",
      "team-a/project-x",
      "--question",
      "hi",
      "--config",
      "/tmp/config.json",
      "--profile",
      "p2",
    ],
  )

  args = parseArgs()

  assert args.config == "/tmp/config.json"
  assert args.profile == "p2"
