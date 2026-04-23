---
name: wiki-ingest
description: Use when the user asks to ingest a remote raw source into wiki pages, such as turning viking://resources/<kb>/raw/*.md into sources/entities/concepts and updating index/overview/log. Trigger phrases include "执行 wiki-ingest", "把 raw/*.md ingest 成 wiki 页面", "对这个 source 做远端 ingest", and "更新 index、overview、log".
---

# Wiki Ingest

## Purpose

Ingest one remote raw source from OpenViking into the wiki namespace of the same knowledge base.

This skill reads a source under:

`viking://resources/<kb>/raw/...`

and generates or updates:

- `wiki/sources/*.md`
- `wiki/entities/*.md`
- `wiki/concepts/*.md`
- `wiki/index.md`
- `wiki/overview.md`
- `wiki/log.md`

## Preconditions

Before running this skill:

1. The remote knowledge base must already be bootstrapped
2. The source file must already exist under `raw/`
3. Environment variables for an OpenAI-compatible model must be available:
   - `OPENAI_API_KEY`
   - `OPENAI_BASE_URL` (optional)
   - `OPENAI_MODEL` (optional)

## How to run

```bash
python3 -m scripts.wiki_ingest_remote \
  --kb-name <kb-name> \
  --source-uri <full-raw-source-uri> \
  --pretty
```

## Example

```bash
python3 -m scripts.wiki_ingest_remote \
  --kb-name my-kb \
  --source-uri viking://resources/my-kb/raw/openviking-notes.md \
  --pretty
```


## Dry run

Use --dry-run to preview the write plan without writing:

```bash
python3 -m scripts.wiki_ingest_remote \
  --kb-name my-kb \
  --source-uri viking://resources/my-kb/raw/openviking-notes.md \
  --dry-run \
  --pretty
```

## Notes
- This script uses an LLM to generate page content
- It writes directly to remote OpenViking storage
- It is the first real content-producing workflow in the remote wiki pipeline
