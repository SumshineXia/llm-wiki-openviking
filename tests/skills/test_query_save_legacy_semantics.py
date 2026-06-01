from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys


repoRoot = Path(__file__).resolve().parents[2]

queryScriptsDir = repoRoot / "skills" / "wiki-query" / "scripts"
queryModulePath = queryScriptsDir / "query.py"
sys.path.insert(0, str(queryScriptsDir))
querySpec = spec_from_file_location("wiki_query_script_legacy_save", queryModulePath)
if querySpec is None or querySpec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-query/scripts/query.py")
queryModule = module_from_spec(querySpec)
querySpec.loader.exec_module(queryModule)

saveScriptsDir = repoRoot / "skills" / "wiki-save" / "scripts"
saveModulePath = saveScriptsDir / "save.py"
sys.path.insert(0, str(saveScriptsDir))
saveSpec = spec_from_file_location("wiki_save_script_helpers", saveModulePath)
if saveSpec is None or saveSpec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-save/scripts/save.py")
saveModule = module_from_spec(saveSpec)
saveSpec.loader.exec_module(saveModule)


def test_query_and_save_helper_outputs_are_consistent() -> None:
  indexText = "# 索引\n\n## 综合结论\n- [[syntheses/existing.md]] - 旧标题\n"
  linkPath = "syntheses/existing.md"
  title = "新标题"
  question = "问题示例"
  answerMarkdown = "回答示例"
  usedPages = ["viking://resources/demo/wiki/sources/a.md"]

  queryIndex = queryModule.upsert_index_link_bullet(indexText, "syntheses", linkPath, title)
  saveIndex = saveModule.upsert_index_link_bullet(indexText, "## 综合结论", linkPath, title)
  assert queryIndex == saveIndex

  queryMarkdown = queryModule.render_synthesis_markdown(title, question, answerMarkdown, usedPages)
  saveMarkdown = saveModule.render_synthesis_markdown(title, question, answerMarkdown, usedPages)
  assert queryMarkdown == saveMarkdown

  queryNote = queryModule.build_overview_note(linkPath, title)
  saveNote = saveModule.build_overview_note(linkPath, title)
  assert queryNote == saveNote

  overviewText = "# 概览\n"
  queryOverview = queryModule.upsert_overview_synthesis_block(overviewText, linkPath, queryNote)
  saveOverview = saveModule.upsert_overview_synthesis_block(overviewText, linkPath, saveNote)
  assert queryOverview == saveOverview


class FakeOVFSClient:
  def __init__(self, _config) -> None:
    self.writeCalls: list[tuple[str, str, bool]] = []

  def __enter__(self):
    return self

  def __exit__(self, excType, exc, tb) -> None:
    return None

  def stat(self, uri: str):
    if uri.endswith("wiki/syntheses/标题.md"):
      raise queryModule.OVFSHTTPError("404")
    return {"isDir": False}

  def ls(self, uri: str, recursive: bool = False):
    return []

  def read_text(self, uri: str) -> str:
    if uri.endswith("wiki/index.md"):
      return "# 索引\n\n## 综合结论\n- [[syntheses/标题.md]] - 旧标题\n"
    if uri.endswith("wiki/overview.md"):
      return "# 概览\n\n<!-- synthesis:syntheses/标题.md:start -->\n- [[syntheses/标题.md]] - 旧标题\n<!-- synthesis:syntheses/标题.md:end -->\n"
    return "# 操作日志\n"

  def write_text(self, uri: str, content: str, create: bool, wait: bool) -> None:
    self.writeCalls.append((uri, content, create))


def test_legacy_save_updates_index_overview_log_and_returns_deprecated_fields(monkeypatch, capsys) -> None:
  fakeClient = FakeOVFSClient(None)
  monkeypatch.setattr(
    sys,
    "argv",
    ["query.py", "--kb-name", "kb", "--question", "q", "--save", "--slug", "标题"],
  )
  monkeypatch.setattr(queryModule, "OVFSClient", lambda _config: fakeClient)
  monkeypatch.setattr(queryModule.OVFSConfig, "load", lambda config_path=None, profile=None: object())
  monkeypatch.setattr(queryModule, "read_local_schema", lambda: "schema")
  monkeypatch.setattr(queryModule, "select_relevant_pages", lambda client, kb_root, question, top_k: [{"uri": "u1", "content": "c", "score": "1"}])
  monkeypatch.setattr(
    queryModule,
    "call_llm",
    lambda prompt, *, api_key, base_url, model: {"answer_markdown": "当前答案", "used_pages": ["u1"], "synthesis_title": "新标题"},
  )
  monkeypatch.setattr(queryModule, "resolve_openai_settings", lambda args: {"api_key": "k", "base_url": None, "model": "m"})
  monkeypatch.setattr(queryModule, "write_temp_json_file", lambda data, pretty: Path("/tmp/payload.json"))

  code = queryModule.main()
  output = json.loads(capsys.readouterr().out)

  assert code == 0
  assert output["saved"] is True
  assert output["save_deprecated"] is True
  assert output["recommended_save_skill"] == "wiki-save"
  assert output["legacy_save_requeries"] is True
  assert output["created"] is True
  assert output["updated"] is False
  assert output["overview_updated"] is True

  writtenUris = [item[0] for item in fakeClient.writeCalls]
  assert "viking://resources/kb/wiki/index.md" in writtenUris
  assert "viking://resources/kb/wiki/overview.md" in writtenUris
  assert "viking://resources/kb/wiki/log.md" in writtenUris
