from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-ingest" / "scripts"
modulePath = scriptsDir / "ingest.py"
import sys
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_ingest_ingest", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-ingest/scripts/ingest.py")
module = module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

resolve_write_target_uri = module.resolve_write_target_uri
resolve_canonical_markdown_uri = module.resolve_canonical_markdown_uri
write_page = module.write_page
get_uri_stat = module.get_uri_stat
expected_content_child_uri = module.expected_content_child_uri


class DummyOVFS:
  pass


# ===== expected_content_child_uri 测试 =====

def test_expected_content_child_uri() -> None:
  uri = "viking://resources/my-kb/wiki/overview.md"
  assert expected_content_child_uri(uri) == "viking://resources/my-kb/wiki/overview.md/overview.md"


def test_expected_content_child_uri_with_trailing_slash() -> None:
  uri = "viking://resources/my-kb/wiki/concepts/foo.md/"
  assert expected_content_child_uri(uri) == "viking://resources/my-kb/wiki/concepts/foo.md/foo.md"


# ===== resolve_write_target_uri 测试 =====

def test_write_target_not_exists_returns_uri_with_create_flag() -> None:
  client = DummyOVFS()
  with patch.object(module, "get_uri_stat", return_value=None):
    uri, create = resolve_write_target_uri(client, "viking://resources/my-kb/wiki/concepts/new-thing.md")
  assert uri == "viking://resources/my-kb/wiki/concepts/new-thing.md"
  assert create is True


def test_write_target_is_plain_file_returns_uri_without_create() -> None:
  client = DummyOVFS()
  with patch.object(module, "get_uri_stat", return_value={"isDir": False}):
    uri, create = resolve_write_target_uri(client, "viking://resources/my-kb/wiki/sources/foo.md/tmp123.md")
  assert uri == "viking://resources/my-kb/wiki/sources/foo.md/tmp123.md"
  assert create is False


def test_write_target_is_dir_finds_same_name_child_first() -> None:
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  same_name_uri = "viking://resources/my-kb/wiki/overview.md/overview.md"

  def fake_stat(_client, uri):
    if uri == overview_uri:
      return {"isDir": True}
    if uri == same_name_uri:
      return {"isDir": False}
    return None

  def fake_ls(uri, recursive=False):
    return [{"uri": same_name_uri, "isDir": False}]

  client = DummyOVFS()
  client.ls = fake_ls
  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    uri, create = resolve_write_target_uri(client, overview_uri)
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert uri == same_name_uri
  assert create is False


def test_write_target_is_dir_prefers_same_name_over_tmp() -> None:
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  same_name_uri = "viking://resources/my-kb/wiki/overview.md/overview.md"
  tmp_uri = "viking://resources/my-kb/wiki/overview.md/tmp123.md"

  def fake_stat(_client, uri):
    stats = {
      overview_uri: {"isDir": True},
      same_name_uri: {"isDir": False},
      tmp_uri: {"isDir": False},
    }
    return stats.get(uri)

  def fake_ls(uri, recursive=False):
    return [
      {"uri": tmp_uri, "isDir": False},
      {"uri": same_name_uri, "isDir": False},
    ]

  client = DummyOVFS()
  client.ls = fake_ls
  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    uri, create = resolve_write_target_uri(client, overview_uri)
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert uri == same_name_uri, f"同名 child 应优先于 tmp，got {uri}"
  assert create is False


def test_write_target_is_dir_falls_back_to_tmp() -> None:
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  tmp_uri = "viking://resources/my-kb/wiki/overview.md/tmpabc.md"

  def fake_stat(_client, uri):
    if uri == overview_uri:
      return {"isDir": True}
    if uri == tmp_uri:
      return {"isDir": False}
    return None

  def fake_ls(uri, recursive=False):
    return [{"uri": tmp_uri, "isDir": False}]

  client = DummyOVFS()
  client.ls = fake_ls
  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    uri, create = resolve_write_target_uri(client, overview_uri)
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert uri == tmp_uri, f"无同名 child 时应退回 tmp，got {uri}"
  assert create is False


def test_write_target_is_dir_skips_abstract_md() -> None:
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  abstract_uri = "viking://resources/my-kb/wiki/overview.md/abstract.md"
  content_uri = "viking://resources/my-kb/wiki/overview.md/other.md"

  def fake_stat(_client, uri):
    if uri == overview_uri:
      return {"isDir": True}
    if uri == abstract_uri:
      return {"isDir": False}
    if uri == content_uri:
      return {"isDir": False}
    return None

  def fake_ls(uri, recursive=False):
    return [
      {"uri": abstract_uri, "isDir": False},
      {"uri": content_uri, "isDir": False},
    ]

  client = DummyOVFS()
  client.ls = fake_ls
  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    uri, create = resolve_write_target_uri(client, overview_uri)
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert uri == content_uri, f"应选择非 abstract 的 md 文件，got {uri}"
  assert create is False


def test_write_target_is_dir_skips_same_name_directory() -> None:
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  tmp_uri = "viking://resources/my-kb/wiki/overview.md/tmpxxx.md"
  nested_dir_uri = "viking://resources/my-kb/wiki/overview.md/overview.md"

  def fake_stat(_client, uri):
    stats = {
      overview_uri: {"isDir": True},
      tmp_uri: {"isDir": False},
      nested_dir_uri: {"isDir": True},
    }
    return stats.get(uri)

  def fake_ls(uri, recursive=False):
    return [
      {"uri": tmp_uri, "isDir": False},
      {"uri": nested_dir_uri, "isDir": True},
    ]

  client = DummyOVFS()
  client.ls = fake_ls
  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    uri, create = resolve_write_target_uri(client, overview_uri)
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert uri == tmp_uri, f"同名目录应跳过，退回 tmp child，got {uri}"
  assert create is False


def test_write_target_is_dir_no_content_child_creates_same_name_child() -> None:
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  expected_child = "viking://resources/my-kb/wiki/overview.md/overview.md"

  def fake_stat(_client, uri):
    if uri == overview_uri:
      return {"isDir": True}
    return None

  def fake_ls(uri, recursive=False):
    return []

  client = DummyOVFS()
  client.ls = fake_ls
  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    uri, create = resolve_write_target_uri(client, overview_uri)
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert uri == expected_child, f"目录无子文件时应返回同名 child URI，got {uri}"
  assert create is True


# ===== resolve_canonical_markdown_uri 测试 =====

def test_canonical_uri_not_exists_returns_none() -> None:
  client = DummyOVFS()
  with patch.object(module, "get_uri_stat", return_value=None):
    result = resolve_canonical_markdown_uri(client, "viking://resources/my-kb/wiki/ghost.md")
  assert result is None


def test_canonical_uri_is_plain_file_returns_itself() -> None:
  same_name_uri = "viking://resources/my-kb/wiki/overview.md/overview.md"
  client = DummyOVFS()
  with patch.object(module, "get_uri_stat", return_value={"isDir": False}):
    result = resolve_canonical_markdown_uri(client, same_name_uri)
  assert result == same_name_uri


def test_canonical_uri_is_dir_prefers_same_name_child() -> None:
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  same_name_uri = "viking://resources/my-kb/wiki/overview.md/overview.md"
  tmp_uri = "viking://resources/my-kb/wiki/overview.md/tmpabc.md"
  nested_dir_uri = "viking://resources/my-kb/wiki/overview.md/overview.md"

  def fake_stat(_client, uri):
    stats = {
      overview_uri: {"isDir": True},
      same_name_uri: {"isDir": False},
      tmp_uri: {"isDir": False},
    }
    return stats.get(uri)

  def fake_ls(uri, recursive=False):
    return [
      {"uri": tmp_uri, "isDir": False},
      {"uri": same_name_uri, "isDir": False},
      {"uri": nested_dir_uri, "isDir": True},
    ]

  client = DummyOVFS()
  client.ls = fake_ls
  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    result = resolve_canonical_markdown_uri(client, overview_uri)
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert result == same_name_uri, f"应优先返回同名 child，got {result}"


def test_canonical_uri_skips_abstract_md() -> None:
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  abstract_uri = "viking://resources/my-kb/wiki/overview.md/abstract.md"
  content_uri = "viking://resources/my-kb/wiki/overview.md/other.md"

  def fake_stat(_client, uri):
    stats = {
      overview_uri: {"isDir": True},
      abstract_uri: {"isDir": False},
      content_uri: {"isDir": False},
    }
    return stats.get(uri)

  def fake_ls(uri, recursive=False):
    return [
      {"uri": abstract_uri, "isDir": False},
      {"uri": content_uri, "isDir": False},
    ]

  client = DummyOVFS()
  client.ls = fake_ls
  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    result = resolve_canonical_markdown_uri(client, overview_uri)
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert result == content_uri, f"应跳过 abstract.md，got {result}"


def test_canonical_uri_is_dir_no_content_child_returns_none() -> None:
  overview_uri = "viking://resources/my-kb/wiki/overview.md"

  def fake_stat(_client, uri):
    if uri == overview_uri:
      return {"isDir": True}
    return None

  def fake_ls(uri, recursive=False):
    return []

  client = DummyOVFS()
  client.ls = fake_ls
  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    result = resolve_canonical_markdown_uri(client, overview_uri)
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert result is None, f"无子文件应返回 None，got {result}"


# ===== write_page 测试 =====

def test_write_page_creates_via_write_text() -> None:
  target_uri = "viking://resources/my-kb/wiki/concepts/new-thing.md"

  add_resource_calls = []
  write_text_calls = []

  client = DummyOVFS()

  def fake_add_local_resource(file_path, to, reason="", instruction="", wait=False,
                              timeout=None, strict=False):
    add_resource_calls.append({"to": to, "reason": reason})
    return {}

  def fake_write_text(uri, content, create=False, append=False, wait=True, timeout=None):
    write_text_calls.append({"uri": uri, "content": content, "create": create})
    return {}

  def get_stat(_client, uri):
    return None

  client.add_local_resource = fake_add_local_resource
  client.write_text = fake_write_text

  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = get_stat
  try:
    write_page(client, target_uri, "# 新概念\n\n内容")
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert len(write_text_calls) == 1, "应调用 write_text(create=True) 创建"
  assert write_text_calls[0]["uri"] == target_uri
  assert write_text_calls[0]["create"] is True
  assert write_text_calls[0]["content"] == "# 新概念\n\n内容"
  assert len(add_resource_calls) == 0, "不应调用 add_local_resource"


def test_write_page_updates_existing_same_name_child() -> None:
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  same_name_uri = "viking://resources/my-kb/wiki/overview.md/overview.md"

  add_resource_calls = []
  write_text_calls = []

  client = DummyOVFS()

  def fake_add_local_resource(**kwargs):
    add_resource_calls.append(kwargs)
    return {}

  def fake_write_text(uri, content, create=False, append=False, wait=True, timeout=None):
    write_text_calls.append({"uri": uri, "content": content, "create": create})
    return {}

  def fake_stat(_client, uri):
    if uri == overview_uri:
      return {"isDir": True}
    if uri == same_name_uri:
      return {"isDir": False}
    return None

  def fake_ls(uri, recursive=False):
    return [{"uri": same_name_uri, "isDir": False}]

  client.add_local_resource = fake_add_local_resource
  client.write_text = fake_write_text
  client.ls = fake_ls

  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    write_page(client, overview_uri, "# 概况\n\n更新内容")
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert len(write_text_calls) == 1, "应调用 write_text 更新"
  assert write_text_calls[0]["uri"] == same_name_uri
  assert write_text_calls[0]["create"] is False
  assert write_text_calls[0]["content"] == "# 概况\n\n更新内容"
  assert len(add_resource_calls) == 0, "不应调用 add_local_resource"


def test_write_page_updates_plain_file_directly() -> None:
  same_name_uri = "viking://resources/my-kb/wiki/sources/foo.md/foo.md"

  add_resource_calls = []
  write_text_calls = []

  client = DummyOVFS()

  def fake_add_local_resource(**kwargs):
    add_resource_calls.append(kwargs)
    return {}

  def fake_write_text(uri, content, create=False, append=False, wait=True, timeout=None):
    write_text_calls.append({"uri": uri, "content": content})
    return {}

  def fake_stat(_client, uri):
    if uri == same_name_uri:
      return {"isDir": False}
    return None

  client.add_local_resource = fake_add_local_resource
  client.write_text = fake_write_text

  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    write_page(client, same_name_uri, "# 直接更新\n\n内容")
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert len(write_text_calls) == 1, "应调用 write_text 更新已有文件"
  assert write_text_calls[0]["uri"] == same_name_uri
  assert write_text_calls[0]["content"] == "# 直接更新\n\n内容"
  assert len(add_resource_calls) == 0, "不应调用 add_local_resource"
