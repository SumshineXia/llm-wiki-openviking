from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys

import pytest


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-ingest" / "scripts"
modulePath = scriptsDir / "ingest.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_ingest_chunking", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-ingest/scripts/ingest.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)


class FakeOVFSClient:
  def __init__(self, source_text: str) -> None:
    self.source_uri = "viking://resources/demo/raw/long.md"
    self.texts = {
      self.source_uri: source_text,
      "viking://resources/demo/wiki/index.md": "# 索引\n\n## 实体\n\n## 概念\n",
      "viking://resources/demo/wiki/overview.md": "# 概览\n",
      "viking://resources/demo/wiki/log.md": "# 操作日志\n",
    }

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc, tb):
    return None

  def stat(self, uri: str):
    if uri in self.texts:
      return {"isDir": False}
    if uri.endswith("/"):
      return {"isDir": True}
    raise module.OVFSHTTPError("404 not found")

  def read_text(self, uri: str) -> str:
    return self.texts[uri]

  def ls(self, uri: str, recursive: bool = False):
    if recursive:
      return []
    if uri.endswith("wiki/entities/") or uri.endswith("wiki/concepts/") or uri.endswith("wiki/sources/"):
      return []
    return []

  def write_text(self, uri: str, markdown: str, create: bool, wait: bool) -> None:
    self.texts[uri] = markdown


def setup_main_monkeypatch(
  monkeypatch: pytest.MonkeyPatch,
  *,
  source_text: str,
  argv_extra: list[str],
  call_llm_impl,
) -> None:
  client = FakeOVFSClient(source_text)

  class DummyConfig:
    @staticmethod
    def load(config_path=None, profile=None):
      return object()

  monkeypatch.setattr(module, "OVFSConfig", DummyConfig)
  monkeypatch.setattr(module, "OVFSClient", lambda config: client)
  monkeypatch.setattr(module, "load_config", lambda config_path=None, profile=None: {})
  monkeypatch.setattr(
    module,
    "resolve_openai_settings",
    lambda args: {"api_key": "k", "base_url": None, "model": "m"},
  )
  monkeypatch.setattr(module, "read_local_schema", lambda: "# schema")
  monkeypatch.setattr(module, "call_llm", call_llm_impl)
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "ingest.py",
      "--kb-name",
      "demo",
      "--source-uri",
      "viking://resources/demo/raw/long.md",
      "--dry-run",
      *argv_extra,
    ],
  )


def test_split_markdown_into_chunks_prefers_heading_break() -> None:
  text = "A" * 30 + "\n# H2\n" + "B" * 40
  result = module.split_markdown_into_chunks(
    text,
    chunk_size=40,
    chunk_overlap=5,
    max_chunks=10,
  )

  assert result["chunk_count"] >= 2
  assert result["chunks"][0].endswith("\n")
  assert any("# H2" in chunk for chunk in result["chunks"])
  assert result["truncated"] is False


def test_split_markdown_into_chunks_marks_truncated_when_exceeds_max() -> None:
  text = ("x" * 60) + ("\n\n" + "y" * 60) + ("\n\n" + "z" * 60)
  result = module.split_markdown_into_chunks(
    text,
    chunk_size=50,
    chunk_overlap=10,
    max_chunks=2,
  )

  assert result["chunk_count"] > 2
  assert result["used_chunk_count"] == 2
  assert result["truncated"] is True


def test_dedupe_pages_by_slug_keeps_first_item() -> None:
  pages = [
    {"slug": "alice", "title": "A", "markdown": "1", "kind": "entity"},
    {"slug": "alice", "title": "B", "markdown": "2", "kind": "entity"},
    {"slug": "bob", "title": "C", "markdown": "3", "kind": "entity"},
  ]
  deduped = module.dedupe_pages_by_slug(pages)

  assert [page["slug"] for page in deduped] == ["alice", "bob"]
  assert deduped[0]["title"] == "A"


def test_parse_args_supports_long_doc_defaults(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    ["ingest.py", "--kb-name", "demo", "--source-uri", "viking://resources/demo/raw/a.md"],
  )
  args = module.parse_args()

  assert args.long_doc_threshold == 30000
  assert args.chunk_size == 18000
  assert args.chunk_overlap == 1000
  assert args.max_chunks == 20
  assert args.allow_partial_chunks is False


def test_parse_args_rejects_overlap_not_smaller_than_chunk_size(monkeypatch) -> None:
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "ingest.py",
      "--kb-name",
      "demo",
      "--source-uri",
      "viking://resources/demo/raw/a.md",
      "--chunk-size",
      "100",
      "--chunk-overlap",
      "100",
    ],
  )
  with pytest.raises(SystemExit):
    module.parse_args()


def test_main_allow_partial_chunks_continue_when_some_chunk_failures(
  monkeypatch: pytest.MonkeyPatch,
  capsys: pytest.CaptureFixture[str],
) -> None:
  source_text = ("# T\n" + ("A" * 90))
  call_count = {"chunk": 0}

  def fake_call_llm(prompt: str, *, api_key, base_url, model):
    if "分块摘要" in prompt:
      call_count["chunk"] += 1
      if call_count["chunk"] == 1:
        raise RuntimeError("chunk failed")
      return {
        "summary": "ok",
        "key_entities": ["实体A"],
        "key_concepts": ["概念A"],
        "key_claims": ["主张A"],
        "possible_wikilinks": ["[[entities/a.md]]"],
      }
    return {
      "source_title": "长文档",
      "source_page_markdown": "# 长文档",
      "entity_pages": [],
      "concept_pages": [],
      "overview_note": "note",
      "log_note": "log",
    }

  setup_main_monkeypatch(
    monkeypatch,
    source_text=source_text,
    argv_extra=[
      "--long-doc-threshold",
      "10",
      "--chunk-size",
      "40",
      "--chunk-overlap",
      "5",
      "--max-chunks",
      "20",
      "--allow-partial-chunks",
    ],
    call_llm_impl=fake_call_llm,
  )

  exit_code = module.main()
  output = capsys.readouterr().out
  result = json.loads(output)

  assert exit_code == 0
  assert result["status"] == "ok"
  assert result["partial_chunks_used"] is True
  assert result["summary_failures"] >= 1


def test_main_allow_partial_chunks_still_fails_when_all_chunks_fail(
  monkeypatch: pytest.MonkeyPatch,
  capsys: pytest.CaptureFixture[str],
) -> None:
  source_text = ("# T\n" + ("A" * 90))

  def fake_call_llm(prompt: str, *, api_key, base_url, model):
    if "分块摘要" in prompt:
      raise RuntimeError("all chunk failed")
    raise AssertionError("不应进入 reduce 阶段")

  setup_main_monkeypatch(
    monkeypatch,
    source_text=source_text,
    argv_extra=[
      "--long-doc-threshold",
      "10",
      "--chunk-size",
      "40",
      "--chunk-overlap",
      "5",
      "--max-chunks",
      "20",
      "--allow-partial-chunks",
    ],
    call_llm_impl=fake_call_llm,
  )

  exit_code = module.main()
  output = capsys.readouterr().out
  result = json.loads(output)

  assert exit_code == 1
  assert result["status"] == "error"
  assert "All chunk summaries failed" in result["error"]


def test_main_fail_fast_when_chunk_count_exceeds_max_chunks(
  monkeypatch: pytest.MonkeyPatch,
  capsys: pytest.CaptureFixture[str],
) -> None:
  source_text = "A" * 220

  def fake_call_llm(prompt: str, *, api_key, base_url, model):
    raise AssertionError("超过 max_chunks 时不应调用 LLM")

  setup_main_monkeypatch(
    monkeypatch,
    source_text=source_text,
    argv_extra=[
      "--long-doc-threshold",
      "10",
      "--chunk-size",
      "40",
      "--chunk-overlap",
      "5",
      "--max-chunks",
      "2",
    ],
    call_llm_impl=fake_call_llm,
  )

  exit_code = module.main()
  output = capsys.readouterr().out
  result = json.loads(output)

  assert exit_code == 1
  assert result["status"] == "error"
  assert "exceeds max_chunks" in result["error"]


def test_main_long_doc_result_contains_new_fields(
  monkeypatch: pytest.MonkeyPatch,
  capsys: pytest.CaptureFixture[str],
) -> None:
  source_text = "# T\n" + ("A" * 90)

  def fake_call_llm(prompt: str, *, api_key, base_url, model):
    if "分块摘要" in prompt:
      return {
        "summary": "ok",
        "key_entities": ["实体A"],
        "key_concepts": ["概念A"],
        "key_claims": ["主张A"],
        "possible_wikilinks": ["[[entities/a.md]]"],
      }
    return {
      "source_title": "长文档",
      "source_page_markdown": "# 长文档",
      "entity_pages": [],
      "concept_pages": [],
      "overview_note": "note",
      "log_note": "log",
    }

  setup_main_monkeypatch(
    monkeypatch,
    source_text=source_text,
    argv_extra=[
      "--long-doc-threshold",
      "10",
      "--chunk-size",
      "40",
      "--chunk-overlap",
      "5",
      "--max-chunks",
      "20",
    ],
    call_llm_impl=fake_call_llm,
  )

  exit_code = module.main()
  output = capsys.readouterr().out
  result = json.loads(output)

  assert exit_code == 0
  assert result["long_doc_mode"] is True
  assert isinstance(result["chunk_count"], int)
  assert isinstance(result["used_chunk_count"], int)
  assert result["chunk_count"] >= result["used_chunk_count"] >= 1
  assert result["chunks_truncated"] is False
  assert result["summary_failures"] == 0
  assert result["partial_chunks_used"] is False
