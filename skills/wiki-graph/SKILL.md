---
name: wiki-graph
description: Use when the user asks to generate or refresh remote wiki graph artifacts, including graph.json and graph.html under viking://resources/<kb>/graph/. Trigger phrases include "为 my-kb 生成 wiki graph", "执行 wiki-graph", "构建 graph.json 和 graph.html", and "先 dry-run 再生成 graph 文件".
---

# Wiki Graph

## Purpose

Build a deterministic explicit-link graph from the remote OpenViking wiki namespace.

This skill scans pages under:

`viking://resources/<kb>/wiki/`

extracts internal links, and writes graph artifacts to:

- `graph/graph.json`
- `graph/graph.html`

## What this graph contains

- nodes: wiki markdown pages
- edges: explicit internal links such as `[[...]]` and markdown links

## How to run

```bash
python3 -m scripts.wiki_graph_remote --kb-name <kb-name> --pretty
```

## Example

```bash
python3 -m scripts.wiki_graph_remote --kb-name my-kb --pretty
```

## Dry run

```bash
python3 -m scripts.wiki_graph_remote --kb-name my-kb --dry-run --pretty
```

## Include root pages
By default, index.md, overview.md, and log.md are excluded.

```bash
python3 -m scripts.wiki_graph_remote --kb-name my-kb --include-root-pages --pretty
```

## Notes
- This is a deterministic graph build
- It does not call an LLM
- It writes final graph artifacts back to remote OpenViking storage
