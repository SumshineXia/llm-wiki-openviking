from __future__ import annotations

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


repo_root = Path(__file__).resolve().parents[2]
module_path = repo_root / "skills" / "wiki-health" / "scripts" / "health.py"
spec = spec_from_file_location("wiki_health_script", module_path)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-health/scripts/health.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
required_wiki_pages = module.required_wiki_pages
normalize_relative_wiki_target = module.normalize_relative_wiki_target
extract_index_links = module.extract_index_links
check_index_targets = module.check_index_targets
check_duplicate_index_targets = module.check_duplicate_index_targets
check_source_log_coverage = module.check_source_log_coverage
check_required_structure = module.check_required_structure
build_report = module.build_report
requiredDirs = module.requiredDirs


def test_required_wiki_pages_contains_three_root_pages() -> None:
  kb_root = "viking://resources/my-kb/"
  pages = required_wiki_pages(kb_root)

  assert pages == [
    "viking://resources/my-kb/wiki/index.md",
    "viking://resources/my-kb/wiki/overview.md",
    "viking://resources/my-kb/wiki/log.md",
  ]


def test_normalize_relative_wiki_target_handles_parent_segments() -> None:
  assert normalize_relative_wiki_target("../overview.md") == "overview.md"
  assert normalize_relative_wiki_target("./entities/alice") == "entities/alice.md"


def test_extract_index_links_supports_markdown_and_wiki_links() -> None:
  index_text = "\n".join([
    "- [[entities/alice]]",
    "- [概览](../overview.md)",
  ])

  links = extract_index_links(index_text)

  assert "entities/alice.md" in links
  assert "overview.md" in links


class FakeClient:
  def __init__(
    self,
    texts: dict[str, str],
    stats: dict[str, dict[str, bool]],
    listings: dict[tuple[str, bool], list[object]] | None = None,
  ) -> None:
    self.texts = texts
    self.stats = stats
    self.listings = listings or {}

  def read_text(self, uri: str) -> str:
    return self.texts[uri]

  def stat(self, uri: str) -> dict[str, bool]:
    if uri not in self.stats:
      raise module.OVFSHTTPError("404 not found")
    return self.stats[uri]

  def ls(self, uri: str, recursive: bool = False) -> list[object]:
    return list(self.listings.get((uri, recursive), []))


def test_health_report_keys_remain_english() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  stats = {
    **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
    **{uri: {"isDir": False} for uri in required_file_uris},
  }
  texts = {
    required_file_uris[0]: "# Index\n\n- [[overview]]\n",
    required_file_uris[1]: "# Overview\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
    required_file_uris[2]: "# 日志\n\n已记录来源：index\n",
  }
  client = FakeClient(texts=texts, stats=stats)

  report = build_report(client, kb_root)

  assert "status" in report
  assert "warnings" in report
  assert "errors" in report
  assert "details" in report


def test_check_index_targets_does_not_report_existing_parent_relative_link() -> None:
  kb_root = "viking://resources/my-kb/"
  index_uri = f"{kb_root}wiki/index.md"
  overview_uri = f"{kb_root}wiki/overview.md"
  client = FakeClient(
    texts={index_uri: "- [概览](../overview.md)"},
    stats={
      index_uri: {"isDir": False},
      overview_uri: {"isDir": False},
    },
  )

  _, broken = check_index_targets(client, kb_root)

  assert broken == []


def test_check_required_structure_no_error_when_required_dirs_and_files_exist() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  stats = {
    **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
    **{uri: {"isDir": False} for uri in required_file_uris},
  }
  client = FakeClient(texts={}, stats=stats)

  missing_dirs, missing_files = check_required_structure(client, kb_root)

  assert missing_dirs == []
  assert missing_files == []


def test_check_required_structure_reports_missing_graph_directory() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  stats = {
    **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
    **{uri: {"isDir": False} for uri in required_file_uris},
  }
  stats[f"{kb_root}graph/"] = {"isDir": False}
  client = FakeClient(texts={}, stats=stats)

  missing_dirs, _ = check_required_structure(client, kb_root)

  assert f"{kb_root}graph/" in missing_dirs


def test_duplicate_index_targets_are_reported() -> None:
  duplicates = check_duplicate_index_targets(
    "## 实体\n- [[entities/aihub.md]] - AIHub\n- [[entities/aihub.md]] - aihub\n"
  )

  assert duplicates == ["entities/aihub.md"]


def test_unindexed_wiki_pages_are_reported_as_error() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  stats = {
    **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
    **{uri: {"isDir": False} for uri in required_file_uris},
    f"{kb_root}wiki/sources/a.md/a.md": {"isDir": False},
    f"{kb_root}wiki/sources/b.md/b.md": {"isDir": False},
  }
  texts = {
    required_file_uris[0]: "# 索引\n\n## 资料来源\n- [[sources/a.md]] - A\n",
    required_file_uris[1]: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
    required_file_uris[2]: "# 操作日志\n\n已记录来源：a\n",
    f"{kb_root}wiki/sources/a.md/a.md": "# A\n\n这是来源 A 的正文内容，长度足够通过页面有效性判断。",
    f"{kb_root}wiki/sources/b.md/b.md": "# B\n\n这是来源 B 的正文内容，长度足够通过页面有效性判断。",
  }
  client = FakeClient(
    texts=texts,
    stats=stats,
    listings={
      (f"{kb_root}wiki/", True): [
        {"uri": uri, "isDir": False} for uri in required_file_uris
      ] + [
        {"uri": f"{kb_root}wiki/sources/a.md/a.md", "isDir": False},
        {"uri": f"{kb_root}wiki/sources/b.md/b.md", "isDir": False},
      ],
      (f"{kb_root}wiki/sources/", True): [
        {"uri": f"{kb_root}wiki/sources/a.md/a.md", "isDir": False},
        {"uri": f"{kb_root}wiki/sources/b.md/b.md", "isDir": False},
      ],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
    },
  )

  report = build_report(client, kb_root)

  assert report["status"] == "error"
  assert f"{kb_root}wiki/sources/b.md" in report["details"]["unindexed_wiki_pages"]


def test_source_log_title_match_does_not_false_positive() -> None:
  kb_root = "viking://resources/my-kb/"
  source_uri = f"{kb_root}wiki/sources/axon.md/axon.md"
  client = FakeClient(
    texts={
      f"{kb_root}wiki/log.md": "# 操作日志\n\nIngested source: Axon·灵犀 智能软件工厂\n",
      source_uri: "# Axon·灵犀 智能软件工厂\n\n正文\n",
    },
    stats={
      f"{kb_root}wiki/log.md": {"isDir": False},
      f"{kb_root}wiki/sources/axon.md": {"isDir": True},
      source_uri: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/sources/", True): [
        {"uri": source_uri, "isDir": False},
      ],
    },
  )

  missing = check_source_log_coverage(client, kb_root)

  assert missing == []


def test_source_log_slug_missing_still_warns() -> None:
  kb_root = "viking://resources/my-kb/"
  source_uri = f"{kb_root}wiki/sources/debug-write-probe-after-vlm-fix.md/debug-write-probe-after-vlm-fix.md"
  client = FakeClient(
    texts={
      f"{kb_root}wiki/log.md": "# 操作日志\n\n无关内容\n",
      source_uri: "# debug-write-probe-after-vlm-fix\n\n正文\n",
    },
    stats={
      f"{kb_root}wiki/log.md": {"isDir": False},
      f"{kb_root}wiki/sources/debug-write-probe-after-vlm-fix.md": {"isDir": True},
      source_uri: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/sources/", True): [
        {"uri": source_uri, "isDir": False},
      ],
    },
  )

  missing = check_source_log_coverage(client, kb_root)

  assert missing == [f"{kb_root}wiki/sources/debug-write-probe-after-vlm-fix.md"]


def test_source_log_short_slug_does_not_match_unrelated_word() -> None:
  kb_root = "viking://resources/my-kb/"
  source_uri = f"{kb_root}wiki/sources/ai.md/ai.md"
  client = FakeClient(
    texts={
      f"{kb_root}wiki/log.md": "# 操作日志\n\nDaily maintenance completed\n",
      source_uri: "# AI\n\n正文\n",
    },
    stats={
      f"{kb_root}wiki/log.md": {"isDir": False},
      f"{kb_root}wiki/sources/ai.md": {"isDir": True},
      source_uri: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/sources/", True): [
        {"uri": source_uri, "isDir": False},
      ],
    },
  )

  missing = check_source_log_coverage(client, kb_root)

  assert missing == [f"{kb_root}wiki/sources/ai.md"]


def test_main_repair_index_only_writes_index_once(monkeypatch: pytest.MonkeyPatch) -> None:
  kb_root = "viking://resources/my-kb/"
  index_uri = f"{kb_root}wiki/index.md"
  index_write_uri = f"{kb_root}wiki/index.md/index.md"
  overview_uri = f"{kb_root}wiki/overview.md"
  log_uri = f"{kb_root}wiki/log.md"
  required_file_uris = required_wiki_pages(kb_root)
  writes: list[dict[str, object]] = []
  printed: list[dict[str, object]] = []

  class RepairClient(FakeClient):
    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc, tb):
      return False

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      writes.append({
        "uri": uri,
        "text": text,
        "create": create,
        "wait": wait,
      })
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  repair_client = RepairClient(
    texts={
      index_write_uri: "# 索引\n\n手工前言\n\n## 资料来源\n- [[sources/a.md]] - 旧标题\n",
      overview_uri: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      log_uri: "# 操作日志\n\n记录\n",
      f"{kb_root}wiki/sources/a.md/a.md": "# A\n\n这是来源 A 的正文内容，长度足够通过页面有效性判断。",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      **{uri: {"isDir": False} for uri in required_file_uris if uri != index_uri},
      index_uri: {"isDir": True},
      index_write_uri: {"isDir": False},
      f"{kb_root}wiki/sources/a.md": {"isDir": True},
      f"{kb_root}wiki/sources/a.md/a.md": {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/index.md/", False): [
        {"uri": index_write_uri, "isDir": False},
      ],
      (f"{kb_root}wiki/", True): [
        {"uri": index_write_uri, "isDir": False},
        {"uri": overview_uri, "isDir": False},
        {"uri": log_uri, "isDir": False},
        {"uri": f"{kb_root}wiki/sources/a.md/a.md", "isDir": False},
      ],
      (f"{kb_root}wiki/sources/", True): [
        {"uri": f"{kb_root}wiki/sources/a.md/a.md", "isDir": False},
      ],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
    },
  )

  monkeypatch.setattr(module.OVFSConfig, "load", staticmethod(lambda config_path=None, profile=None: object()))
  monkeypatch.setattr(module, "OVFSClient", lambda config: repair_client)
  monkeypatch.setattr(module, "build_kb_root", lambda kb_name: kb_root)
  monkeypatch.setattr(module, "print_json", lambda data, pretty=False: printed.append(data))
  monkeypatch.setattr(module.sys, "argv", ["health.py", "--kb-name", "my-kb", "--repair-index"])

  exit_code = module.main()

  assert exit_code in (0, 1)
  assert len(printed) == 1
  report = printed[0]
  assert isinstance(report, dict)
  actions = report["repair"]["actions"]
  assert len(actions) == 1
  action = actions[0]
  assert action["type"] == "repair_index"
  assert action["index_rebuilt"] is True
  assert action["index_uri"] == index_uri
  assert action["index_write_uri"] == index_write_uri
  assert writes == [{
    "uri": index_write_uri,
    "text": writes[0]["text"],
    "create": False,
    "wait": True,
  }]
  assert json.loads(json.dumps(report))["repair"]["actions"][0]["index_write_uri"] == index_write_uri


def test_check_index_targets_accepts_nested_source_bundle() -> None:
  kb_root = "viking://resources/my-kb/"
  index_uri = f"{kb_root}wiki/index.md"
  bundle_uri = f"{kb_root}wiki/sources/readme.md"
  nested_dir_uri = f"{bundle_uri}/llm-wiki-openviking_用户使用版"
  primary_uri = f"{nested_dir_uri}/关键内容.md"
  client = FakeClient(
    texts={
      index_uri: "# 索引\n\n## 资料来源\n- [[sources/readme.md]] - README\n",
      primary_uri: "# README\n\n正文内容足够长，用于通过有效页面判断。\n",
    },
    stats={
      index_uri: {"isDir": False},
      bundle_uri: {"isDir": True},
      nested_dir_uri: {"isDir": True},
      primary_uri: {"isDir": False},
    },
    listings={
      (f"{bundle_uri}/", False): [
        {"uri": nested_dir_uri, "isDir": True},
      ],
      (f"{bundle_uri}/", True): [
        {"uri": nested_dir_uri, "isDir": True},
        {"uri": primary_uri, "isDir": False},
      ],
    },
  )

  linked, broken = check_index_targets(client, kb_root)

  assert linked == ["sources/readme.md"]
  assert broken == []


def test_main_repair_index_keeps_nested_source_bundle_link_without_broken_target(monkeypatch: pytest.MonkeyPatch) -> None:
  kb_root = "viking://resources/my-kb/"
  index_uri = f"{kb_root}wiki/index.md"
  index_write_uri = f"{kb_root}wiki/index.md/index.md"
  overview_uri = f"{kb_root}wiki/overview.md"
  log_uri = f"{kb_root}wiki/log.md"
  bundle_uri = f"{kb_root}wiki/sources/readme.md"
  nested_dir_uri = f"{bundle_uri}/llm-wiki-openviking_用户使用版"
  primary_uri = f"{nested_dir_uri}/关键内容.md"
  required_file_uris = required_wiki_pages(kb_root)
  writes: list[dict[str, object]] = []
  printed: list[dict[str, object]] = []

  class RepairClient(FakeClient):
    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc, tb):
      return False

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      writes.append({"uri": uri, "text": text, "create": create, "wait": wait})
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  repair_client = RepairClient(
    texts={
      index_write_uri: "# 索引\n\n## 资料来源\n- [[sources/readme.md]] - README\n",
      overview_uri: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      log_uri: "# 操作日志\n\n记录\n",
      primary_uri: "# README\n\n正文内容足够长，用于通过有效页面判断。\n",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      **{uri: {"isDir": False} for uri in required_file_uris if uri != index_uri},
      index_uri: {"isDir": True},
      index_write_uri: {"isDir": False},
      bundle_uri: {"isDir": True},
      nested_dir_uri: {"isDir": True},
      primary_uri: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/index.md/", False): [{"uri": index_write_uri, "isDir": False}],
      (f"{kb_root}wiki/", True): [
        {"uri": index_write_uri, "isDir": False},
        {"uri": overview_uri, "isDir": False},
        {"uri": log_uri, "isDir": False},
        {"uri": nested_dir_uri, "isDir": True},
        {"uri": primary_uri, "isDir": False},
      ],
      (f"{kb_root}wiki/sources/", True): [
        {"uri": nested_dir_uri, "isDir": True},
        {"uri": primary_uri, "isDir": False},
      ],
      (f"{bundle_uri}/", False): [{"uri": nested_dir_uri, "isDir": True}],
      (f"{bundle_uri}/", True): [
        {"uri": nested_dir_uri, "isDir": True},
        {"uri": primary_uri, "isDir": False},
      ],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
    },
  )

  monkeypatch.setattr(module.OVFSConfig, "load", staticmethod(lambda config_path=None, profile=None: object()))
  monkeypatch.setattr(module, "OVFSClient", lambda config: repair_client)
  monkeypatch.setattr(module, "build_kb_root", lambda kb_name: kb_root)
  monkeypatch.setattr(module, "print_json", lambda data, pretty=False: printed.append(data))
  monkeypatch.setattr(module.sys, "argv", ["health.py", "--kb-name", "my-kb", "--repair-index"])

  exit_code = module.main()

  assert exit_code in (0, 1)
  report = printed[0]
  actions = report["repair"]["actions"]
  assert len(actions) == 1
  assert actions[0]["type"] == "repair_index"
  assert actions[0]["index_rebuilt"] is True
  assert report["details"]["broken_index_targets"] == []
  assert "[[sources/readme.md]]" in writes[0]["text"]


def test_stat_is_dir_handles_various_stat_shapes() -> None:
  stat_is_dir = module.stat_is_dir
  assert stat_is_dir(None) is False
  assert stat_is_dir({"isDir": True}) is True
  assert stat_is_dir({"isDir": False}) is False
  assert stat_is_dir({"is_dir": True}) is True
  assert stat_is_dir({"type": "directory"}) is True
  assert stat_is_dir({"type": "file"}) is False


def test_slugify_matches_ingest_logic() -> None:
  assert module.slugify("AIHub_用户指南") == "aihub-用户指南"
  assert module.slugify("README__5e5947c8") == "readme-5e5947c8"
  assert module.slugify("  Hello World  ") == "hello-world"


def test_candidate_source_slugs_includes_hash_stripped_variant() -> None:
  uri = "viking://resources/esf/raw/README__5e5947c8ee9740d68e3f926e2877dcf9"
  candidates = module.candidate_source_slugs_from_raw_child_uri(uri)
  assert "readme-5e5947c8ee9740d68e3f926e2877dcf9" in candidates
  assert "readme" in candidates


def test_candidate_source_slugs_without_hash_suffix() -> None:
  uri = "viking://resources/esf/raw/aihub_kb_opencode_usage_guide_revised_draft.md"
  candidates = module.candidate_source_slugs_from_raw_child_uri(uri)
  assert candidates == ["aihub-kb-opencode-usage-guide-revised-draft"]


def test_list_markdown_pages_ignores_bundle_abstract_metadata() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  source_page = f"{kb_root}wiki/sources/readme.md/readme.md"
  abstract_page = f"{kb_root}wiki/sources/readme.md/abstract.md"
  client = FakeClient(
    texts={
      required_file_uris[0]: "# 索引\n\n## 资料来源\n- [[sources/readme.md]] - README\n",
      required_file_uris[1]: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      required_file_uris[2]: "# 操作日志\n\nreadme\n",
      source_page: "# README\n\n正文内容足够长用于通过判断。\n",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      **{uri: {"isDir": False} for uri in required_file_uris},
      f"{kb_root}wiki/sources/readme.md": {"isDir": True},
      source_page: {"isDir": False},
      abstract_page: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/sources/", True): [
        {"uri": source_page, "isDir": False},
        {"uri": abstract_page, "isDir": False},
      ],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": uri, "isDir": False} for uri in required_file_uris
      ] + [{"uri": source_page, "isDir": False}],
    },
  )

  report = build_report(client, kb_root)

  assert report["summary"]["source_pages"] == 1


def test_check_unexpected_wiki_root_entries_finds_manual_page() -> None:
  kb_root = "viking://resources/my-kb/"
  manual_uri = f"{kb_root}wiki/manual.md"
  client = FakeClient(
    texts={},
    stats={},
    listings={
      (f"{kb_root}wiki/", False): [
        {"uri": f"{kb_root}wiki/index.md", "isDir": False},
        {"uri": f"{kb_root}wiki/overview.md", "isDir": False},
        {"uri": f"{kb_root}wiki/log.md", "isDir": False},
        {"uri": manual_uri, "isDir": False},
        {"uri": f"{kb_root}wiki/sources", "isDir": True},
        {"uri": f"{kb_root}wiki/entities", "isDir": True},
        {"uri": f"{kb_root}wiki/concepts", "isDir": True},
        {"uri": f"{kb_root}wiki/syntheses", "isDir": True},
      ],
    },
  )

  result = module.check_unexpected_wiki_root_entries(client, kb_root)
  assert result == [manual_uri]


def test_check_unexpected_wiki_root_entries_empty_when_all_standard() -> None:
  kb_root = "viking://resources/my-kb/"
  client = FakeClient(
    texts={},
    stats={},
    listings={
      (f"{kb_root}wiki/", False): [
        {"uri": f"{kb_root}wiki/index.md", "isDir": False},
        {"uri": f"{kb_root}wiki/overview.md", "isDir": False},
        {"uri": f"{kb_root}wiki/log.md", "isDir": False},
        {"uri": f"{kb_root}wiki/sources", "isDir": True},
        {"uri": f"{kb_root}wiki/entities", "isDir": True},
        {"uri": f"{kb_root}wiki/concepts", "isDir": True},
        {"uri": f"{kb_root}wiki/syntheses", "isDir": True},
      ],
    },
  )

  result = module.check_unexpected_wiki_root_entries(client, kb_root)
  assert result == []


def test_raw_source_check_only_scans_raw_top_level_children() -> None:
  kb_root = "viking://resources/my-kb/"
  raw_bundle_dir = f"{kb_root}raw/readme.md/"
  raw_nested_dir = f"{raw_bundle_dir}llm-wiki-openviking_用户使用版/"
  raw_fragment = f"{raw_nested_dir}六常用自然语言示例.md"
  source_page = f"{kb_root}wiki/sources/readme.md/readme.md"
  client = FakeClient(
    texts={
      source_page: "# README\n\n正文内容足够长用于通过判断。\n",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      f"{kb_root}wiki/index.md": {"isDir": False},
      f"{kb_root}wiki/overview.md": {"isDir": False},
      f"{kb_root}wiki/log.md": {"isDir": False},
      f"{kb_root}wiki/sources/readme.md": {"isDir": True},
      source_page: {"isDir": False},
      raw_bundle_dir.rstrip("/"): {"isDir": True},
      raw_nested_dir.rstrip("/"): {"isDir": True},
      raw_fragment: {"isDir": False},
    },
    listings={
      (f"{kb_root}raw/", False): [
        {"uri": f"{kb_root}raw/readme.md", "isDir": True},
      ],
      (f"{kb_root}wiki/sources/", True): [
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": f"{kb_root}wiki/index.md", "isDir": False},
        {"uri": f"{kb_root}wiki/overview.md", "isDir": False},
        {"uri": f"{kb_root}wiki/log.md", "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
    },
  )

  result = module.check_raw_sources_without_source_pages(client, kb_root)
  assert result == []


def test_raw_hash_suffix_candidate_matches_existing_source_page() -> None:
  kb_root = "viking://resources/my-kb/"
  raw_uri = f"{kb_root}raw/README__5e5947c8ee9740d68e3f926e2877dcf9"
  source_page = f"{kb_root}wiki/sources/readme.md/readme.md"
  client = FakeClient(
    texts={source_page: "# README\n\n正文\n"},
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      f"{kb_root}wiki/index.md": {"isDir": False},
      f"{kb_root}wiki/overview.md": {"isDir": False},
      f"{kb_root}wiki/log.md": {"isDir": False},
      f"{kb_root}wiki/sources/readme.md": {"isDir": True},
      source_page: {"isDir": False},
      raw_uri: {"isDir": True},
    },
    listings={
      (f"{kb_root}raw/", False): [
        {"uri": raw_uri, "isDir": True},
      ],
      (f"{kb_root}wiki/sources/", True): [
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": f"{kb_root}wiki/index.md", "isDir": False},
        {"uri": f"{kb_root}wiki/overview.md", "isDir": False},
        {"uri": f"{kb_root}wiki/log.md", "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
    },
  )

  candidates = module.candidate_source_slugs_from_raw_child_uri(raw_uri)
  assert "readme-5e5947c8ee9740d68e3f926e2877dcf9" in candidates
  assert "readme" in candidates

  result = module.check_raw_sources_without_source_pages(client, kb_root)
  assert result == []


def test_synthesis_log_missing_is_reported() -> None:
  kb_root = "viking://resources/my-kb/"
  synthesis_page = f"{kb_root}wiki/syntheses/answer.md/answer.md"
  client = FakeClient(
    texts={
      f"{kb_root}wiki/log.md": "# 操作日志\n\n无关内容\n",
      synthesis_page: "# Answer\n\n正文\n",
    },
    stats={
      f"{kb_root}wiki/log.md": {"isDir": False},
      f"{kb_root}wiki/syntheses/answer.md": {"isDir": True},
      synthesis_page: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/syntheses/", True): [
        {"uri": synthesis_page, "isDir": False},
      ],
    },
  )

  missing = module.check_synthesis_log_coverage(client, kb_root)

  assert missing == [f"{kb_root}wiki/syntheses/answer.md"]


def test_health_reports_unexpected_wiki_root_entries() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  manual_uri = f"{kb_root}wiki/manual.md"
  client = FakeClient(
    texts={
      required_file_uris[0]: "# 索引\n\n## 资料来源\n",
      required_file_uris[1]: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      required_file_uris[2]: "# 操作日志\n\n记录\n",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      **{uri: {"isDir": False} for uri in required_file_uris},
      manual_uri: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/", False): [
        {"uri": uri, "isDir": False} for uri in required_file_uris
      ] + [
        {"uri": manual_uri, "isDir": False},
        {"uri": f"{kb_root}wiki/sources", "isDir": True},
        {"uri": f"{kb_root}wiki/entities", "isDir": True},
        {"uri": f"{kb_root}wiki/concepts", "isDir": True},
        {"uri": f"{kb_root}wiki/syntheses", "isDir": True},
      ],
      (f"{kb_root}wiki/sources/", True): [],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}raw/", False): [],
    },
  )

  report = build_report(client, kb_root)

  assert manual_uri in report["details"]["unexpected_wiki_root_entries"]
  assert any("不符合 schema" in w for w in report["warnings"])


def test_health_reports_raw_source_candidate_without_source_page() -> None:
  kb_root = "viking://resources/my-kb/"
  required_file_uris = required_wiki_pages(kb_root)
  raw_uri = f"{kb_root}raw/new-note.md"
  client = FakeClient(
    texts={
      required_file_uris[0]: "# 索引\n\n## 资料来源\n",
      required_file_uris[1]: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      required_file_uris[2]: "# 操作日志\n\n记录\n",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      **{uri: {"isDir": False} for uri in required_file_uris},
      raw_uri: {"isDir": False},
    },
    listings={
      (f"{kb_root}raw/", False): [
        {"uri": raw_uri, "isDir": False},
      ],
      (f"{kb_root}wiki/sources/", True): [],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": uri, "isDir": False} for uri in required_file_uris
      ],
    },
  )

  report = build_report(client, kb_root)

  raw_pending = report["details"]["raw_sources_without_source_pages"]
  assert len(raw_pending) == 1
  assert raw_pending[0]["raw_uri"] == raw_uri
  assert any("尚未 ingest" in w for w in report["warnings"])


def test_repair_structure_reports_file_conflict_for_required_dir() -> None:
  kb_root = "viking://resources/my-kb/"
  graph_uri = f"{kb_root}graph/"
  required_file_uris = required_wiki_pages(kb_root)
  mkdir_calls: list[str] = []

  class ConflictClient(FakeClient):
    def mkdir(self, uri: str, description: str | None = None) -> None:
      mkdir_calls.append(uri)
      self.stats[uri] = {"isDir": True}

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  client = ConflictClient(
    texts={
      required_file_uris[0]: "# 索引\n\n## 资料来源\n",
      required_file_uris[1]: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      required_file_uris[2]: "# 操作日志\n\n记录\n",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs if rel != "graph/"},
      graph_uri: {"isDir": False},
      **{uri: {"isDir": False} for uri in required_file_uris},
    },
    listings={},
  )

  result = module.repair_structure(client, kb_root)

  assert graph_uri in result["skipped_conflicts"]
  assert graph_uri not in mkdir_calls
  assert result["structure_repaired"] is True


def test_repair_structure_does_not_overwrite_existing_page_but_creates_missing() -> None:
  kb_root = "viking://resources/my-kb/"
  overview_uri = f"{kb_root}wiki/overview.md"
  log_uri = f"{kb_root}wiki/log.md"
  index_uri = f"{kb_root}wiki/index.md"
  writes: list[dict[str, object]] = []

  class StructureClient(FakeClient):
    def mkdir(self, uri: str, description: str | None = None) -> None:
      self.stats[uri] = {"isDir": True}

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      writes.append({"uri": uri, "text": text, "create": create, "wait": wait})
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  client = StructureClient(
    texts={
      index_uri: "# 索引\n\n## 资料来源\n",
      overview_uri: "# 概览\n\n这是人工编写的非空概览内容，不应被覆盖。",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      index_uri: {"isDir": False},
      overview_uri: {"isDir": False},
    },
    listings={},
  )

  result = module.repair_structure(client, kb_root)

  written_uris = [w["uri"] for w in writes]
  assert log_uri in written_uris or any(log_uri in str(w["uri"]) for w in writes)
  assert overview_uri not in written_uris
  assert "这是人工编写的非空概览内容" in client.texts[overview_uri]


def test_repair_log_writes_to_resolved_log_bundle_child() -> None:
  kb_root = "viking://resources/my-kb/"
  log_dir = f"{kb_root}wiki/log.md"
  log_child = f"{log_dir}/log.md"
  source_page = f"{kb_root}wiki/sources/a.md/a.md"
  required_file_uris = required_wiki_pages(kb_root)
  writes: list[dict[str, object]] = []

  class LogRepairClient(FakeClient):
    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      writes.append({"uri": uri, "text": text, "create": create, "wait": wait})
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  client = LogRepairClient(
    texts={
      required_file_uris[0]: "# 索引\n\n## 资料来源\n- [[sources/a.md]] - A\n",
      required_file_uris[1]: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      log_child: "# 操作日志\n\n无关内容\n",
      source_page: "# A\n\n这是来源 A 的正文内容，长度足够通过页面有效性判断。",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      **{uri: {"isDir": False} for uri in required_file_uris if uri != f"{kb_root}wiki/log.md"},
      log_dir: {"isDir": True},
      log_child: {"isDir": False},
      f"{kb_root}wiki/sources/a.md": {"isDir": True},
      source_page: {"isDir": False},
    },
    listings={
      (f"{log_dir}/", False): [{"uri": log_child, "isDir": False}],
      (f"{kb_root}wiki/sources/", True): [{"uri": source_page, "isDir": False}],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": required_file_uris[0], "isDir": False},
        {"uri": required_file_uris[1], "isDir": False},
        {"uri": log_child, "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/", False): [
        {"uri": required_file_uris[0], "isDir": False},
        {"uri": required_file_uris[1], "isDir": False},
        {"uri": log_dir, "isDir": True},
      ],
      (f"{kb_root}raw/", False): [],
    },
  )

  result = module.repair_log(client, kb_root)

  assert result["type"] == "repair_log"
  assert result["log_repaired"] is True
  log_writes = [w for w in writes if "health-reconcile" in str(w["text"])]
  assert len(log_writes) >= 1
  assert log_writes[0]["uri"] == log_child
  assert "health-reconcile" in log_writes[0]["text"]
  assert "已补录 source 页面" in log_writes[0]["text"]
  assert "wiki/sources/a.md" in log_writes[0]["text"]


def test_repair_log_creates_missing_log_then_appends() -> None:
  kb_root = "viking://resources/my-kb/"
  source_page = f"{kb_root}wiki/sources/a.md/a.md"
  index_uri = f"{kb_root}wiki/index.md"
  overview_uri = f"{kb_root}wiki/overview.md"
  log_uri = f"{kb_root}wiki/log.md"
  writes: list[dict[str, object]] = []

  class LogCreateClient(FakeClient):
    def mkdir(self, uri: str, description: str | None = None) -> None:
      self.stats[uri] = {"isDir": True}

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      writes.append({"uri": uri, "text": text, "create": create, "wait": wait})
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  client = LogCreateClient(
    texts={
      index_uri: "# 索引\n\n## 资料来源\n- [[sources/a.md]] - A\n",
      overview_uri: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      source_page: "# A\n\n这是来源 A 的正文内容，长度足够通过页面有效性判断。",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      index_uri: {"isDir": False},
      overview_uri: {"isDir": False},
      f"{kb_root}wiki/sources/a.md": {"isDir": True},
      source_page: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/sources/", True): [{"uri": source_page, "isDir": False}],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": index_uri, "isDir": False},
        {"uri": overview_uri, "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/", False): [
        {"uri": index_uri, "isDir": False},
        {"uri": overview_uri, "isDir": False},
      ],
      (f"{kb_root}raw/", False): [],
    },
  )

  result = module.repair_log(client, kb_root)

  assert result["type"] == "repair_log"
  assert result["created_initial_log"] is True
  assert result["log_repaired"] is True

  assert any(w["text"] == "# 操作日志\n\n" for w in writes)
  health_writes = [w for w in writes if "health-reconcile" in str(w["text"])]
  assert len(health_writes) >= 1
  assert "# 操作日志" in str(health_writes[0]["text"])
  assert "health-reconcile" in str(health_writes[0]["text"])


def test_main_repair_structure_creates_missing_dir(monkeypatch: pytest.MonkeyPatch) -> None:
  kb_root = "viking://resources/my-kb/"
  index_uri = f"{kb_root}wiki/index.md"
  overview_uri = f"{kb_root}wiki/overview.md"
  log_uri = f"{kb_root}wiki/log.md"
  source_page = f"{kb_root}wiki/sources/a.md/a.md"
  calls: list[str] = []
  printed: list[dict[str, object]] = []

  class StructureMainClient(FakeClient):
    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc, tb):
      return False

    def mkdir(self, uri: str, description: str | None = None) -> None:
      calls.append(f"mkdir:{uri}")
      self.stats[uri] = {"isDir": True}

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      calls.append(f"write:{uri}")
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  client = StructureMainClient(
    texts={
      index_uri: "# 索引\n\n## 资料来源\n- [[sources/a.md]] - A\n",
      overview_uri: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      log_uri: "# 操作日志\n\n记录\n",
      source_page: "# A\n\n这是来源 A 的正文内容，长度足够通过页面有效性判断。",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs if rel != "graph/"},
      index_uri: {"isDir": False},
      overview_uri: {"isDir": False},
      log_uri: {"isDir": False},
      f"{kb_root}wiki/sources/a.md": {"isDir": True},
      source_page: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/sources/", True): [{"uri": source_page, "isDir": False}],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": index_uri, "isDir": False},
        {"uri": overview_uri, "isDir": False},
        {"uri": log_uri, "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/", False): [
        {"uri": index_uri, "isDir": False},
        {"uri": overview_uri, "isDir": False},
        {"uri": log_uri, "isDir": False},
        {"uri": f"{kb_root}wiki/sources", "isDir": True},
        {"uri": f"{kb_root}wiki/entities", "isDir": True},
        {"uri": f"{kb_root}wiki/concepts", "isDir": True},
        {"uri": f"{kb_root}wiki/syntheses", "isDir": True},
      ],
      (f"{kb_root}raw/", False): [],
    },
  )

  monkeypatch.setattr(module.OVFSConfig, "load", staticmethod(lambda config_path=None, profile=None: object()))
  monkeypatch.setattr(module, "OVFSClient", lambda config: client)
  monkeypatch.setattr(module, "build_kb_root", lambda kb_name: kb_root)
  monkeypatch.setattr(module, "print_json", lambda data, pretty=False: printed.append(data))
  monkeypatch.setattr(module.sys, "argv", ["health.py", "--kb-name", "my-kb", "--repair-structure"])

  exit_code = module.main()

  assert exit_code in (0, 1)
  report = printed[0]
  assert "repair" in report
  structure_action = [a for a in report["repair"]["actions"] if a["type"] == "repair_structure"][0]
  assert f"{kb_root}graph/" in structure_action["created_dirs"]
  assert any(f"mkdir:{kb_root}graph/" in c for c in calls)


def test_main_repair_log_appends_health_reconcile(monkeypatch: pytest.MonkeyPatch) -> None:
  kb_root = "viking://resources/my-kb/"
  log_child = f"{kb_root}wiki/log.md/log.md"
  source_page = f"{kb_root}wiki/sources/a.md/a.md"
  index_child = f"{kb_root}wiki/index.md/index.md"
  overview_child = f"{kb_root}wiki/overview.md/overview.md"
  writes: list[dict[str, object]] = []
  printed: list[dict[str, object]] = []

  class LogMainClient(FakeClient):
    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc, tb):
      return False

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      writes.append({"uri": uri, "text": text, "create": create, "wait": wait})
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}

  client = LogMainClient(
    texts={
      index_child: "# 索引\n\n## 资料来源\n- [[sources/a.md]] - A\n",
      overview_child: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      log_child: "# 操作日志\n\n无关内容\n",
      source_page: "# A\n\n这是来源 A 的正文内容，长度足够通过页面有效性判断。",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs},
      f"{kb_root}wiki/index.md": {"isDir": True},
      f"{kb_root}wiki/overview.md": {"isDir": True},
      f"{kb_root}wiki/log.md": {"isDir": True},
      index_child: {"isDir": False},
      overview_child: {"isDir": False},
      log_child: {"isDir": False},
      f"{kb_root}wiki/sources/a.md": {"isDir": True},
      source_page: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/index.md/", False): [{"uri": index_child, "isDir": False}],
      (f"{kb_root}wiki/overview.md/", False): [{"uri": overview_child, "isDir": False}],
      (f"{kb_root}wiki/log.md/", False): [{"uri": log_child, "isDir": False}],
      (f"{kb_root}wiki/sources/", True): [{"uri": source_page, "isDir": False}],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": index_child, "isDir": False},
        {"uri": overview_child, "isDir": False},
        {"uri": log_child, "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/", False): [
        {"uri": f"{kb_root}wiki/index.md", "isDir": True},
        {"uri": f"{kb_root}wiki/overview.md", "isDir": True},
        {"uri": f"{kb_root}wiki/log.md", "isDir": True},
        {"uri": f"{kb_root}wiki/sources", "isDir": True},
        {"uri": f"{kb_root}wiki/entities", "isDir": True},
        {"uri": f"{kb_root}wiki/concepts", "isDir": True},
        {"uri": f"{kb_root}wiki/syntheses", "isDir": True},
      ],
      (f"{kb_root}raw/", False): [],
    },
  )

  monkeypatch.setattr(module.OVFSConfig, "load", staticmethod(lambda config_path=None, profile=None: object()))
  monkeypatch.setattr(module, "OVFSClient", lambda config: client)
  monkeypatch.setattr(module, "build_kb_root", lambda kb_name: kb_root)
  monkeypatch.setattr(module, "print_json", lambda data, pretty=False: printed.append(data))
  monkeypatch.setattr(module.sys, "argv", ["health.py", "--kb-name", "my-kb", "--repair-log"])

  exit_code = module.main()

  assert exit_code in (0, 1)
  report = printed[0]
  log_action = [a for a in report["repair"]["actions"] if a["type"] == "repair_log"][0]
  assert log_action["log_repaired"] is True

  log_writes = [w for w in writes if "health-reconcile" in str(w["text"])]
  assert len(log_writes) >= 1
  assert log_writes[0]["uri"] == log_child
  assert "wiki/sources/a.md" in log_writes[0]["text"]


def test_main_repair_all_runs_structure_then_index_then_log(monkeypatch: pytest.MonkeyPatch) -> None:
  kb_root = "viking://resources/my-kb/"
  log_child = f"{kb_root}wiki/log.md/log.md"
  source_page = f"{kb_root}wiki/sources/a.md/a.md"
  index_child = f"{kb_root}wiki/index.md/index.md"
  overview_child = f"{kb_root}wiki/overview.md/overview.md"
  calls: list[str] = []
  printed: list[dict[str, object]] = []

  class AllRepairClient(FakeClient):
    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc, tb):
      return False

    def mkdir(self, uri: str, description: str | None = None) -> None:
      calls.append("mkdir")
      self.stats[uri] = {"isDir": True}

    def write_text(self, uri: str, text: str, *, create: bool, wait: bool) -> None:
      self.texts[uri] = text
      self.stats[uri] = {"isDir": False}
      if uri == index_child:
        calls.append("write_index")
      elif uri == log_child or "log.md" in uri:
        calls.append("write_log")
      else:
        calls.append("write_other")

  client = AllRepairClient(
    texts={
      index_child: "# 索引\n\n## 资料来源\n- [[sources/a.md]] - A\n",
      overview_child: "# 概览\n\n这是一个足够长的概览内容，用于通过有效页面判断。",
      log_child: "# 操作日志\n\n无关内容\n",
      source_page: "# A\n\n这是来源 A 的正文内容，长度足够通过页面有效性判断。",
    },
    stats={
      **{f"{kb_root}{rel}": {"isDir": True} for rel in requiredDirs if rel != "graph/"},
      f"{kb_root}wiki/index.md": {"isDir": True},
      f"{kb_root}wiki/overview.md": {"isDir": True},
      f"{kb_root}wiki/log.md": {"isDir": True},
      index_child: {"isDir": False},
      overview_child: {"isDir": False},
      log_child: {"isDir": False},
      f"{kb_root}wiki/sources/a.md": {"isDir": True},
      source_page: {"isDir": False},
    },
    listings={
      (f"{kb_root}wiki/index.md/", False): [{"uri": index_child, "isDir": False}],
      (f"{kb_root}wiki/overview.md/", False): [{"uri": overview_child, "isDir": False}],
      (f"{kb_root}wiki/log.md/", False): [{"uri": log_child, "isDir": False}],
      (f"{kb_root}wiki/sources/", True): [{"uri": source_page, "isDir": False}],
      (f"{kb_root}wiki/entities/", True): [],
      (f"{kb_root}wiki/concepts/", True): [],
      (f"{kb_root}wiki/syntheses/", True): [],
      (f"{kb_root}wiki/", True): [
        {"uri": index_child, "isDir": False},
        {"uri": overview_child, "isDir": False},
        {"uri": log_child, "isDir": False},
        {"uri": source_page, "isDir": False},
      ],
      (f"{kb_root}wiki/", False): [
        {"uri": f"{kb_root}wiki/index.md", "isDir": True},
        {"uri": f"{kb_root}wiki/overview.md", "isDir": True},
        {"uri": f"{kb_root}wiki/log.md", "isDir": True},
        {"uri": f"{kb_root}wiki/sources", "isDir": True},
        {"uri": f"{kb_root}wiki/entities", "isDir": True},
        {"uri": f"{kb_root}wiki/concepts", "isDir": True},
        {"uri": f"{kb_root}wiki/syntheses", "isDir": True},
      ],
      (f"{kb_root}raw/", False): [],
    },
  )

  monkeypatch.setattr(module.OVFSConfig, "load", staticmethod(lambda config_path=None, profile=None: object()))
  monkeypatch.setattr(module, "OVFSClient", lambda config: client)
  monkeypatch.setattr(module, "build_kb_root", lambda kb_name: kb_root)
  monkeypatch.setattr(module, "print_json", lambda data, pretty=False: printed.append(data))
  monkeypatch.setattr(module.sys, "argv", ["health.py", "--kb-name", "my-kb", "--repair-all"])

  exit_code = module.main()

  assert exit_code in (0, 1)
  report = printed[0]
  types = [a["type"] for a in report["repair"]["actions"]]
  assert types == ["repair_structure", "repair_index", "repair_log"]

  mkdir_idx = calls.index("mkdir")
  write_index_idx = calls.index("write_index")
  write_log_idx = calls.index("write_log")
  assert mkdir_idx < write_index_idx
  assert write_index_idx < write_log_idx
