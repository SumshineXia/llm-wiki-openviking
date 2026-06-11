from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-ingest" / "scripts"
modulePath = scriptsDir / "ingest.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_ingest_context_slimming", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-ingest/scripts/ingest.py")
module = module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ContextClient:
  def __init__(self) -> None:
    self.texts = {
      "viking://resources/demo/wiki/index.md": "# 索引\n\n## 实体\n- [[entities/alice.md]] - Alice\n\n## 概念\n- [[concepts/rag.md]] - RAG\n",
      "viking://resources/demo/wiki/overview.md": "# 概览\n" + ("A" * 40),
      "viking://resources/demo/wiki/log.md": "# 操作日志\n",
    }
    self.lsCalls: list[tuple[str, bool]] = []

  def stat(self, uri: str) -> dict[str, bool]:
    if uri in self.texts:
      return {"isDir": False}
    if uri.endswith("/wiki/entities/") or uri.endswith("/wiki/concepts/") or uri.endswith("/wiki/sources/"):
      return {"isDir": True}
    raise module.OVFSHTTPError("404 not found")

  def read_text(self, uri: str) -> str:
    return self.texts[uri]

  def ls(self, uri: str, recursive: bool = False):
    self.lsCalls.append((uri, recursive))
    if recursive:
      raise AssertionError("不应使用 recursive list 提取 existing page names")
    if uri.endswith("/wiki/sources/"):
      return []
    return []


class FallbackClient(ContextClient):
  def __init__(self) -> None:
    super().__init__()
    self.texts["viking://resources/demo/wiki/index.md"] = "# 索引\n"

  def ls(self, uri: str, recursive: bool = False):
    self.lsCalls.append((uri, recursive))
    if recursive:
      raise AssertionError("不应使用 recursive list 提取 existing page names")
    if uri.endswith("/wiki/entities/"):
      return [{"uri": "viking://resources/demo/wiki/entities/bob.md", "isDir": False}]
    if uri.endswith("/wiki/concepts/"):
      return [{"uri": "viking://resources/demo/wiki/concepts/vector-db.md", "isDir": False}]
    if uri.endswith("/wiki/sources/"):
      return []
    return []


def test_truncate_for_prompt_keeps_head_and_tail() -> None:
  text = "0123456789" * 10
  excerpt, truncated = module.truncate_for_prompt(text, max_chars=40)

  assert truncated is True
  assert "[truncated for prompt]" in excerpt
  assert excerpt.startswith("01")
  assert excerpt.endswith("89")


def test_build_context_snapshot_keeps_full_text_and_adds_prompt_excerpt() -> None:
  client = ContextClient()

  context = module.build_context_snapshot(
    client,
    "viking://resources/demo/",
    max_context_chars=20,
    max_existing_page_names=10,
  )

  assert context["index_text"].startswith("# 索引")
  assert len(context["overview_text"]) == 45
  assert context["index_truncated_for_prompt"] is True
  assert context["overview_truncated_for_prompt"] is True
  assert context["entity_pages"] == ["viking://resources/demo/wiki/entities/alice.md"]
  assert context["concept_pages"] == ["viking://resources/demo/wiki/concepts/rag.md"]


def test_build_context_snapshot_fallbacks_to_one_level_listing() -> None:
  client = FallbackClient()

  context = module.build_context_snapshot(
    client,
    "viking://resources/demo/",
    max_context_chars=30,
    max_existing_page_names=10,
  )

  assert context["entity_pages"] == ["viking://resources/demo/wiki/entities/bob.md"]
  assert context["concept_pages"] == ["viking://resources/demo/wiki/concepts/vector-db.md"]
  assert ("viking://resources/demo/wiki/entities/", False) in client.lsCalls
  assert ("viking://resources/demo/wiki/concepts/", False) in client.lsCalls


def test_build_llm_prompt_uses_excerpt_not_full_context() -> None:
  context = {
    "index_text": "FULL-INDEX",
    "overview_text": "FULL-OVERVIEW",
    "log_text": "# 操作日志\n",
    "index_excerpt": "INDEX-EXCERPT",
    "overview_excerpt": "OVERVIEW-EXCERPT",
    "index_truncated_for_prompt": True,
    "overview_truncated_for_prompt": True,
    "entity_pages": ["viking://resources/demo/wiki/entities/a.md"],
    "concept_pages": ["viking://resources/demo/wiki/concepts/b.md"],
    "source_pages": [],
  }
  prompt = module.build_llm_prompt(
    schema_text="# schema",
    source_uri="viking://resources/demo/raw/a.md",
    source_text="raw",
    context=context,
    source_slug="a",
  )

  assert "INDEX-EXCERPT" in prompt
  assert "OVERVIEW-EXCERPT" in prompt
  assert "FULL-INDEX" not in prompt
  assert "FULL-OVERVIEW" not in prompt


def test_build_llm_prompt_raises_when_excerpt_missing() -> None:
  context = {
    "index_text": "FULL-INDEX",
    "overview_text": "FULL-OVERVIEW",
    "log_text": "# 操作日志\n",
    "entity_pages": ["viking://resources/demo/wiki/entities/a.md"],
    "concept_pages": ["viking://resources/demo/wiki/concepts/b.md"],
    "source_pages": [],
  }

  with pytest.raises(ValueError, match="index_excerpt and overview_excerpt"):
    module.build_llm_prompt(
      schema_text="# schema",
      source_uri="viking://resources/demo/raw/a.md",
      source_text="raw",
      context=context,
      source_slug="a",
    )


def test_parse_args_supports_context_slimming_defaults(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    ["ingest.py", "--kb-name", "demo", "--source-uri", "viking://resources/demo/raw/a.md"],
  )
  args = module.parse_args()

  assert args.max_context_chars == 12000
  assert args.max_existing_page_names == 100
  assert args.wait_for_indexing is False


@pytest.mark.parametrize("arg", ["--max-context-chars", "--max-existing-page-names"])
def test_parse_args_rejects_non_positive_values(monkeypatch, arg: str) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "ingest.py",
      "--kb-name",
      "demo",
      "--source-uri",
      "viking://resources/demo/raw/a.md",
      arg,
      "0",
    ],
  )
  with pytest.raises(SystemExit):
    module.parse_args()


def test_parse_args_supports_wait_for_indexing(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "ingest.py",
      "--kb-name",
      "demo",
      "--source-uri",
      "viking://resources/demo/raw/a.md",
      "--wait-for-indexing",
    ],
  )
  args = module.parse_args()

  assert args.wait_for_indexing is True
