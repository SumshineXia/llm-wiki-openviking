from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from scripts.ovfs import OVFSClient, OVFSConfig, ensure_dir

DEFAULT_KB_NAME = "my-kb"


def build_seed_dir() -> Path:
    """
    Create a temporary local seed directory:

    <tmp>/wiki/
      - index.md
      - overview.md
      - log.md
    """
    tmp_root = Path(tempfile.mkdtemp(prefix="ovwiki-seed-"))
    wiki_dir = tmp_root / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    (wiki_dir / "index.md").write_text(
        "# Index\n\n"
        "## Sources\n\n"
        "## Entities\n\n"
        "## Concepts\n\n"
        "## Syntheses\n",
        encoding="utf-8",
    )

    (wiki_dir / "overview.md").write_text(
        "# Overview\n\n"
        "This knowledge base has been initialized.\n",
        encoding="utf-8",
    )

    (wiki_dir / "log.md").write_text(
        "# Log\n\n"
        "- bootstrap: knowledge base initialized\n",
        encoding="utf-8",
    )

    return wiki_dir


def import_seed_files(fs: OVFSClient, local_wiki_dir: Path, remote_wiki_root: str) -> None:
    for local_file in sorted(local_wiki_dir.glob("*")):
        if not local_file.is_file():
            continue
        remote_uri = remote_wiki_root + local_file.name
        fs.add_local_resource(
            file_path=str(local_file),
            to=remote_uri,
            reason="Bootstrap initial wiki files",
            wait=False,
        )
        print(f"[upload] {local_file} -> {remote_uri}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap OpenViking knowledge base")
    parser.add_argument(
        "--kb-name",
        default=DEFAULT_KB_NAME,
        help="Knowledge base name under viking://resources/ (default: my-kb)",
    )
    return parser.parse_args()


def build_kb_root(kb_name: str) -> str:
    normalized_name = kb_name.strip().strip("/")
    if not normalized_name:
        raise ValueError("--kb-name cannot be empty")
    if normalized_name.startswith("viking://"):
        raise ValueError("--kb-name should be a resource name, not a full URI")
    return f"viking://resources/{normalized_name}/"


def main() -> None:
    args = parse_args()
    kb_root = build_kb_root(args.kb_name)
    wiki_root = kb_root + "wiki/"

    config = OVFSConfig.load()

    fs = OVFSClient(config)

    try:
        print("[health]", fs.health())

        # 1. Ensure remote directory structure exists
        dirs = [
            kb_root,
            kb_root + "raw/",
            kb_root + "wiki/",
            kb_root + "wiki/sources/",
            kb_root + "wiki/entities/",
            kb_root + "wiki/concepts/",
            kb_root + "wiki/syntheses/",
            kb_root + "graph/",
        ]

        for uri in dirs:
            ensure_dir(fs, uri)
            print(f"[mkdir/exists] {uri}")

        # 2. If wiki/index.md already exists, skip seed import
        if fs.exists(wiki_root + "index.md"):
            print("[bootstrap] already initialized, skip seed import.")
            print("[tree]")
            print(fs.tree(kb_root, level_limit=3))
            return

        # 3. Build local temporary seed dir
        seed_wiki_dir = build_seed_dir()
        print(f"[seed] local seed dir: {seed_wiki_dir}")

        # 4. Import seed files into remote wiki/
        import_seed_files(fs, seed_wiki_dir, wiki_root)

        # 5. Verify
        print("[verify] index exists:", fs.exists(wiki_root + "index.md"))
        print("[verify] overview exists:", fs.exists(wiki_root + "overview.md"))
        print("[verify] log exists:", fs.exists(wiki_root + "log.md"))

        print("[tree]")
        print(fs.tree(kb_root, level_limit=3))

    finally:
        fs.close()


if __name__ == "__main__":
    main()
