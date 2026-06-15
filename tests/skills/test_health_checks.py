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
  assert report["repair"]["index_rebuilt"] is True
  assert report["repair"]["index_uri"] == index_uri
  assert report["repair"]["index_write_uri"] == index_write_uri
  assert writes == [{
    "uri": index_write_uri,
    "text": writes[0]["text"],
    "create": False,
    "wait": True,
  }]
  assert json.loads(json.dumps(report))["repair"]["index_write_uri"] == index_write_uri
