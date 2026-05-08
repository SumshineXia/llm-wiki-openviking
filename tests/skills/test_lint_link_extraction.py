from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


repo_root = Path(__file__).resolve().parents[2]
scripts_dir = repo_root / "skills" / "wiki-lint" / "scripts"
module_path = scripts_dir / "lint.py"
sys.path.insert(0, str(scripts_dir))
spec = spec_from_file_location("wiki_lint_script", module_path)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-lint/scripts/lint.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
extract_internal_links = module.extract_internal_links


def test_extract_internal_links_supports_parent_relative_markdown_links() -> None:
  text = "\n".join([
    "- [概览](../overview.md)",
    "- [实体](../entities/foo.md)",
  ])

  links = extract_internal_links(text)

  assert "overview.md" in links
  assert "entities/foo.md" in links


def test_extract_internal_links_strips_fragment_from_internal_markdown_link() -> None:
  text = "- [锚点](foo.md#bar)"

  links = extract_internal_links(text)

  assert "foo.md" in links
  assert "foo.md#bar" not in links


def test_extract_internal_links_strips_query_from_internal_markdown_link() -> None:
  text = "- [查询](foo.md?x=1)"

  links = extract_internal_links(text)

  assert "foo.md" in links
  assert "foo.md?x=1" not in links


def test_extract_internal_links_ignores_mailto_link() -> None:
  text = "- [联系](mailto:test@example.com)"

  links = extract_internal_links(text)

  assert "mailto:test@example.com" not in links
  assert len(links) == 0
