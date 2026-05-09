import os
import sys
import tempfile
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch
from typing import Optional


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-ingest" / "scripts"
modulePath = scriptsDir / "ingest.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_ingest_ingest", modulePath)
if spec is None or spec.loader is None:
  raise RuntimeError("无法加载 skills/wiki-ingest/scripts/ingest.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)

resolve_write_target_uri = module.resolve_write_target_uri
resolve_canonical_markdown_uri = module.resolve_canonical_markdown_uri
write_page = module.write_page
get_uri_stat = module.get_uri_stat


class DummyOVFS:
  pass


# ===== resolve_write_target_uri 测试 =====

def test_write_target_not_exists_returns_uri_with_create_flag() -> None:
  """目标不存在：返回 (uri, True)，允许 add_local_resource 创建页面。"""
  client = DummyOVFS()
  with patch.object(module, "get_uri_stat", return_value=None):
    uri, create = resolve_write_target_uri(client, "viking://resources/my-kb/wiki/concepts/new-thing.md")
  assert uri == "viking://resources/my-kb/wiki/concepts/new-thing.md"
  assert create is True


def test_write_target_is_plain_file_returns_uri_without_create() -> None:
  """目标是普通文件：返回 (uri, False)，直接用 write_text 更新。"""
  client = DummyOVFS()
  with patch.object(module, "get_uri_stat", return_value={"isDir": False}):
    uri, create = resolve_write_target_uri(client, "viking://resources/my-kb/wiki/sources/foo.md/tmp123.md")
  assert uri == "viking://resources/my-kb/wiki/sources/foo.md/tmp123.md"
  assert create is False


def test_write_target_is_dir_finds_tmp_child() -> None:
  """目标目录下已有直接 tmp 正文子文件：直接返回该子文件。"""
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

  assert uri == tmp_uri
  assert create is False


def test_write_target_is_dir_skips_abstract_md() -> None:
  """目录下有 abstract.md 和非 tmp 的 .md 文件：选后者，跳过 abstract.md。"""
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


def test_write_target_is_dir_prefers_tmp_over_other() -> None:
  """目录下同时有 tmp 文件和非 tmp 文件：优先选 tmp。"""
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  tmp_uri = "viking://resources/my-kb/wiki/overview.md/tmp123.md"
  other_uri = "viking://resources/my-kb/wiki/overview.md/other.md"

  def fake_stat(_client, uri):
    if uri == overview_uri:
      return {"isDir": True}
    if uri == tmp_uri:
      return {"isDir": False}
    if uri == other_uri:
      return {"isDir": False}
    return None

  def fake_ls(uri, recursive=False):
    return [
      {"uri": other_uri, "isDir": False},
      {"uri": tmp_uri, "isDir": False},
    ]

  client = DummyOVFS()
  client.ls = fake_ls
  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    uri, create = resolve_write_target_uri(client, overview_uri)
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert uri == tmp_uri, f"tmp 文件应优先，got {uri}"
  assert create is False


def test_write_target_is_dir_skips_nested_same_name_dir() -> None:
  """目录下同时有 tmpxxx.md 和同名嵌套子目录 overview.md/：选 tmpxxx.md。"""
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

  assert uri == tmp_uri, f"应选直接正文子文件，got {uri}"
  assert create is False


def test_write_target_is_dir_no_content_child_allows_create() -> None:
  """目录存在但没有直接正文子文件：返回 (uri, True) 允许创建新内容。"""
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
    uri, create = resolve_write_target_uri(client, overview_uri)
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert uri == overview_uri, f"应返回原始 uri 允许创建，got {uri}"
  assert create is True


def test_write_target_never_returns_nested_same_basename() -> None:
  """任何情况下不应返回 overview.md/overview.md。"""
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  nested_uri = "viking://resources/my-kb/wiki/overview.md/overview.md"

  def fake_stat(_client, uri):
    if uri == overview_uri:
      return {"isDir": True}
    if uri == nested_uri:
      return {"isDir": True}
    return None

  def fake_ls(uri, recursive=False):
    return [{"uri": nested_uri, "isDir": True}]

  client = DummyOVFS()
  client.ls = fake_ls
  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    uri, create = resolve_write_target_uri(client, overview_uri)
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert nested_uri not in uri, (
    f"禁止返回同名嵌套路径，got {uri}"
  )


# ===== resolve_canonical_markdown_uri 测试 =====

def test_canonical_uri_not_exists_returns_none() -> None:
  client = DummyOVFS()
  with patch.object(module, "get_uri_stat", return_value=None):
    result = resolve_canonical_markdown_uri(client, "viking://resources/my-kb/wiki/ghost.md")
  assert result is None


def test_canonical_uri_is_plain_file_returns_itself() -> None:
  tmp_uri = "viking://resources/my-kb/wiki/overview.md/tmp123.md"
  client = DummyOVFS()
  with patch.object(module, "get_uri_stat", return_value={"isDir": False}):
    result = resolve_canonical_markdown_uri(client, tmp_uri)
  assert result == tmp_uri


def test_canonical_uri_is_dir_returns_first_direct_content_child() -> None:
  """目录时优先返回直接子内容文件（如 tmpxxx.md），而非同名嵌套。"""
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  direct_tmp_uri = "viking://resources/my-kb/wiki/overview.md/tmpabc.md"
  nested_dir_uri = "viking://resources/my-kb/wiki/overview.md/overview.md"

  def fake_stat(_client, uri):
    stats = {
      overview_uri: {"isDir": True},
      direct_tmp_uri: {"isDir": False},
      nested_dir_uri: {"isDir": True},
    }
    return stats.get(uri)

  def fake_ls(uri, recursive=False):
    return [
      {"uri": direct_tmp_uri, "isDir": False},
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

  assert result == direct_tmp_uri, f"应优先返回直接正文子文件，got {result}"


def test_canonical_uri_skips_abstract_md() -> None:
  """目录下的 abstract.md 不被当作正文文件返回。"""
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
  """目录存在但无可读正文子文件：返回 None。"""
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

def test_write_page_creates_new_resource_when_target_not_exists() -> None:
  """目标不存在时应调用 add_local_resource 创建新页面。"""
  target_uri = "viking://resources/my-kb/wiki/concepts/new-thing.md"

  add_resource_calls = []
  write_text_calls = []

  client = DummyOVFS()

  def fake_add_local_resource(file_path, to, reason="", instruction="", wait=False,
                              timeout=None, strict=False):
    add_resource_calls.append({"to": to, "reason": reason})
    return {}

  def fake_write_text(uri, content, create=False, append=False, wait=True, timeout=None):
    write_text_calls.append({"uri": uri, "create": create})
    return {}

  def get_stat(_client, uri):
    return None

  client.add_local_resource = fake_add_local_resource
  client.write_text = fake_write_text

  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = get_stat
  try:
    with patch("tempfile.NamedTemporaryFile") as mock_tmp:
      mock_file = mock_tmp.return_value.__enter__.return_value
      mock_file.name = "/tmp/fake_temp_file.md"
      write_page(client, target_uri, "# 新概念\n\n内容")
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert len(add_resource_calls) == 1, "应调用 add_local_resource 创建新资源"
  assert add_resource_calls[0]["to"] == target_uri
  assert len(write_text_calls) == 0, "不应调用 write_text"


def test_write_page_updates_existing_tmp_child() -> None:
  """目标目录有直接 tmp 正文子文件：应 write_text 更新该子文件。"""
  overview_uri = "viking://resources/my-kb/wiki/overview.md"
  tmp_uri = "viking://resources/my-kb/wiki/overview.md/tmpabc.md"

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
    if uri == overview_uri:
      return {"isDir": True}
    if uri == tmp_uri:
      return {"isDir": False}
    return None

  def fake_ls(uri, recursive=False):
    return [{"uri": tmp_uri, "isDir": False}]

  client.add_local_resource = fake_add_local_resource
  client.write_text = fake_write_text
  client.ls = fake_ls

  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    write_page(client, overview_uri, "# 概况\n\n更新内容")
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert len(write_text_calls) == 1, "应调用 write_text 更新已有内容文件"
  assert write_text_calls[0]["uri"] == tmp_uri, "应写入 tmpxxx.md 而非根目录"
  assert write_text_calls[0]["content"] == "# 概况\n\n更新内容"
  assert len(add_resource_calls) == 0, "不应调用 add_local_resource"


def test_write_page_updates_plain_file_directly() -> None:
  """目标已存在且为普通文件：直接 write_text 更新该文件。"""
  tmp_uri = "viking://resources/my-kb/wiki/sources/foo.md/tmp123.md"

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
    if uri == tmp_uri:
      return {"isDir": False}
    return None

  client.add_local_resource = fake_add_local_resource
  client.write_text = fake_write_text

  original_get_uri_stat = module.get_uri_stat
  module.get_uri_stat = fake_stat
  try:
    write_page(client, tmp_uri, "# 直接更新\n\n内容")
  finally:
    module.get_uri_stat = original_get_uri_stat

  assert len(write_text_calls) == 1, "应调用 write_text 更新已有文件"
  assert write_text_calls[0]["uri"] == tmp_uri
  assert write_text_calls[0]["content"] == "# 直接更新\n\n内容"
  assert len(add_resource_calls) == 0, "不应调用 add_local_resource"
