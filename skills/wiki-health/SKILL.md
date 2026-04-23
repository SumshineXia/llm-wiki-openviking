---
name: wiki-health
description: Use when the user asks to run wiki-health for a KB, re-check structural integrity after ingest/query, or verify remote wiki structure completeness (dirs, root pages, key-page validity, index targets, source-log coverage). Trigger phrases include "执行 wiki-health", "检查结构是否完整", "再执行一次 health", and "ingest 后检查知识库结构".
---

# Wiki Health

## Purpose

Run deterministic structural health checks against a remote OpenViking knowledge base.

This skill verifies that the remote KB under:

`viking://resources/<kb>/`

has the expected wiki structure and that key root pages are valid.

## What this checks

- required directories exist
- required root pages exist
- key root pages are not empty
- links referenced by `wiki/index.md` point to real files
- source pages are reflected in `wiki/log.md`

## How to run

Use the helper script:

```bash
python3 -m scripts.wiki_health_remote --kb-name <kb-name> --pretty
```

## Example

```bash
python3 -m scripts.wiki_health_remote --kb-name my-kb --pretty
```

## Expected behavior
- If the KB is healthy, the script returns status ok
- If required structure is missing or broken, it returns status error
- Warnings are returned for softer issues such as missing source log coverage

## Notes
- This is a deterministic structural check only
- It does not call an LLM
- It operates directly against the remote OpenViking storage
