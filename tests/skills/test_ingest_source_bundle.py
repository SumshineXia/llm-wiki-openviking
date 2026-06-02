from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-ingest" / "scripts"
modulePath = scriptsDir / "ingest.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_ingest_bundle", modulePath)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载 skills/wiki-ingest/scripts/ingest.py")
module = module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

IngestSourceError = module.IngestSourceError
IngestSourceBundle = module.IngestSourceBundle
resolve_ingest_source_bundle = module.resolve_ingest_source_bundle
is_ignored_source_markdown = module.is_ignored_source_markdown


class FakeBundleClient:
    def __init__(
        self,
        dirs: dict[str, list[dict[str, object]]] | None = None,
        files: dict[str, str] | None = None,
    ) -> None:
        self.dirs = dirs or {}
        self.files = files or {}

    def stat(self, uri: str) -> dict:
        key = uri.rstrip("/")
        if key in self.files:
            return {"isDir": False}
        if key in self.dirs or uri in self.dirs:
            return {"isDir": True}
        if uri.endswith("/") and uri.rstrip("/") in self.dirs:
            return {"isDir": True}
        raise module.OVFSHTTPError("404 not found")

    def ls(self, uri: str, recursive: bool = False) -> list:
        key = uri.rstrip("/") + "/"
        if key in self.dirs:
            return self.dirs[key]
        if uri.rstrip("/") in self.dirs:
            return self.dirs[uri.rstrip("/")]
        return []

    def read_text(self, uri: str) -> str:
        key = uri.rstrip("/")
        if key in self.files:
            return self.files[key]
        raise module.OVFSHTTPError(f"404 not found: {uri}")


BASE = "viking://resources/demo/raw"


def test_md_directory_bundle_with_subdirs() -> None:
    root = f"{BASE}/ingest超时记录.md"
    dirs = {
        root: [
            {"uri": f"{root}/.abstract.md", "isDir": False},
            {"uri": f"{root}/.overview.md", "isDir": False},
            {"uri": f"{root}/OpenCode_会话记录知识库初始化", "isDir": True},
            {"uri": f"{root}/Skill_wiki-upload-source_853763ae.md", "isDir": False},
        ],
        f"{root}/OpenCode_会话记录知识库初始化": [
            {"uri": f"{root}/OpenCode_会话记录知识库初始化/.abstract.md", "isDir": False},
            {"uri": f"{root}/OpenCode_会话记录知识库初始化/.overview.md", "isDir": False},
            {"uri": f"{root}/OpenCode_会话记录知识库初始化/part1.md", "isDir": False},
            {"uri": f"{root}/OpenCode_会话记录知识库初始化/part2.md", "isDir": False},
        ],
    }
    files = {
        f"{root}/.abstract.md": "abstract",
        f"{root}/.overview.md": "overview",
        f"{root}/OpenCode_会话记录知识库初始化/.abstract.md": "abstract",
        f"{root}/OpenCode_会话记录知识库初始化/.overview.md": "overview",
        f"{root}/OpenCode_会话记录知识库初始化/part1.md": "content1",
        f"{root}/OpenCode_会话记录知识库初始化/part2.md": "content2",
        f"{root}/Skill_wiki-upload-source_853763ae.md": "content3",
    }
    client = FakeBundleClient(dirs=dirs, files=files)
    bundle = resolve_ingest_source_bundle(client, root)

    assert bundle.source_kind == "directory_bundle"
    assert len(bundle.markdown_uris) == 3
    assert f"{root}/OpenCode_会话记录知识库初始化/part1.md" in bundle.markdown_uris
    assert f"{root}/OpenCode_会话记录知识库初始化/part2.md" in bundle.markdown_uris
    assert f"{root}/Skill_wiki-upload-source_853763ae.md" in bundle.markdown_uris
    assert not any(".abstract.md" in u for u in bundle.markdown_uris)
    assert not any(".overview.md" in u for u in bundle.markdown_uris)
    assert len(bundle.ignored_metadata_uris) >= 2


def test_sh_directory_bundle() -> None:
    root = f"{BASE}/install-llm-wiki.sh"
    dirs = {
        root: [
            {"uri": f"{root}/.abstract.md", "isDir": False},
            {"uri": f"{root}/.overview.md", "isDir": False},
            {"uri": f"{root}/install-llm-wiki_1.md", "isDir": False},
            {"uri": f"{root}/install-llm-wiki_2.md", "isDir": False},
        ],
    }
    files = {
        f"{root}/.abstract.md": "abstract",
        f"{root}/.overview.md": "overview",
        f"{root}/install-llm-wiki_1.md": "c1",
        f"{root}/install-llm-wiki_2.md": "c2",
    }
    client = FakeBundleClient(dirs=dirs, files=files)
    bundle = resolve_ingest_source_bundle(client, root)

    assert bundle.source_kind == "directory_bundle"
    assert len(bundle.markdown_uris) == 2


def test_json_directory_single_markdown() -> None:
    root = f"{BASE}/llm-wiki-config-ZH-0737.json"
    dirs = {
        root: [
            {"uri": f"{root}/.abstract.md", "isDir": False},
            {"uri": f"{root}/.overview.md", "isDir": False},
            {"uri": f"{root}/llm-wiki-config-ZH-0737.md", "isDir": False},
        ],
    }
    files = {
        f"{root}/.abstract.md": "abstract",
        f"{root}/.overview.md": "overview",
        f"{root}/llm-wiki-config-ZH-0737.md": "content",
    }
    client = FakeBundleClient(dirs=dirs, files=files)
    bundle = resolve_ingest_source_bundle(client, root)

    assert bundle.source_kind == "directory_single_markdown"
    assert bundle.markdown_uris == [f"{root}/llm-wiki-config-ZH-0737.md"]


def test_single_md_file() -> None:
    uri = f"{BASE}/manual.md"
    files = {uri: "manual content"}
    client = FakeBundleClient(files=files)
    bundle = resolve_ingest_source_bundle(client, uri)

    assert bundle.source_kind == "single_markdown_file"
    assert bundle.markdown_uris == [uri]


def test_no_trailing_slash_resolves_to_directory() -> None:
    root = f"{BASE}/install-llm-wiki.sh"
    dirs_with_slash = {
        root + "/": [
            {"uri": f"{root}/install-llm-wiki_1.md", "isDir": False},
        ],
    }
    files = {
        f"{root}/install-llm-wiki_1.md": "c1",
    }
    client = FakeBundleClient(dirs=dirs_with_slash, files=files)
    bundle = resolve_ingest_source_bundle(client, root)

    assert bundle.source_kind == "directory_single_markdown"
    assert len(bundle.markdown_uris) == 1


def test_directory_only_metadata_raises() -> None:
    root = f"{BASE}/empty.md"
    dirs = {
        root: [
            {"uri": f"{root}/.abstract.md", "isDir": False},
            {"uri": f"{root}/.overview.md", "isDir": False},
        ],
    }
    files = {
        f"{root}/.abstract.md": "abstract",
        f"{root}/.overview.md": "overview",
    }
    client = FakeBundleClient(dirs=dirs, files=files)

    with pytest.raises(IngestSourceError, match="只有 metadata markdown"):
        resolve_ingest_source_bundle(client, root)


def test_non_md_file_raises() -> None:
    uri = f"{BASE}/a.json"
    files = {uri: "{}"}
    client = FakeBundleClient(files=files)

    with pytest.raises(IngestSourceError, match="不是可 ingest 的 markdown"):
        resolve_ingest_source_bundle(client, uri)


def test_source_not_found_raises() -> None:
    client = FakeBundleClient()

    with pytest.raises(IngestSourceError, match="Source not found"):
        resolve_ingest_source_bundle(client, f"{BASE}/nonexistent.md")


def test_is_ignored_source_markdown() -> None:
    assert is_ignored_source_markdown("foo/.abstract.md")
    assert is_ignored_source_markdown("foo/.overview.md")
    assert is_ignored_source_markdown("foo/abstract.md")
    assert is_ignored_source_markdown("foo/overview.md")
    assert not is_ignored_source_markdown("foo/real-content.md")
    assert not is_ignored_source_markdown("foo/Abstract.md")
