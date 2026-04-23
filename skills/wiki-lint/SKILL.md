---
name: wiki-lint
description: Use when the user asks for remote wiki quality lint checks after ingest/query/cleanup, especially for structure quality and link hygiene. Trigger phrases include "执行 wiki-lint", "检查远端 wiki 的结构质量问题", "看有没有孤儿页/重复标题/stub", and "再跑一次 lint".
---

# Wiki Lint

## Purpose

Run deterministic lint checks against a remote OpenViking-backed wiki knowledge base.

This skill inspects pages under:

`viking://resources/<kb>/wiki/`

and reports structural quality issues that go beyond basic health checks.

## What this checks

- broken internal links
- orphan pages
- pages without outbound internal links
- duplicate page titles
- stub or nearly empty pages

## How to run

```bash
python3 -m scripts.wiki_lint_remote --kb-name <kb-name> --pretty
```

## Example

```bash
python3 -m scripts.wiki_lint_remote --kb-name my-kb --pretty
```

## Note

- This is a deterministic lint pass only
- It does not call an LLM
- It operates directly against remote OpenViking storage
- Recommended order:
  1. bootstrap
  2. ingest
  3. query/save
  4. lint
