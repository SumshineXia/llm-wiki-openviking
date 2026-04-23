---
name: wiki-query
description: Use when the user asks natural-language Q&A over a remote KB wiki, including follow-up asks to save the answer as synthesis. Trigger phrases include "基于 my-kb 回答这个问题", "执行 wiki-query", "请把刚才答案保存为 synthesis", "保存一个名为 <slug> 的 synthesis", and "--save/--slug" style requests.
---

# Wiki Query

## Purpose

Answer a natural-language question using the remote OpenViking-backed wiki namespace.

This skill reads relevant pages from:

`viking://resources/<kb>/wiki/`

and produces a grounded answer.

It can also optionally save the answer into:

`wiki/syntheses/`

## Preconditions

Before running this skill:

1. The remote knowledge base must already be bootstrapped
2. At least one source should already have been ingested into the wiki
3. Environment variables or config for an OpenAI-compatible model must be available:
   - `OPENAI_API_KEY`
   - `OPENAI_BASE_URL` (optional)
   - `OPENAI_MODEL` (optional)

## How to run

```bash
python3 -m scripts.wiki_query_remote \
  --kb-name <kb-name> \
  --question "<your question>" \
  --pretty
```
## Example

```bash
python3 -m scripts.wiki_query_remote \
  --kb-name my-kb \
  --question "OpenViking 是什么？它和传统知识库有什么区别？" \
  --pretty
```

## Save a synthesis page

Use --save to persist the answer into wiki/syntheses/:

```bash
python3 -m scripts.wiki_query_remote \
  --kb-name my-kb \
  --question "OpenViking 是什么？它和传统知识库有什么区别？" \
  --save \
  --pretty
```
Optional custom synthesis slug:

```bash
python3 -m scripts.wiki_query_remote \
  --kb-name my-kb \
  --question "OpenViking 是什么？它和传统知识库有什么区别？" \
  --save \
  --slug openviking-overview \
  --pretty
```
## Notes

1. This script selects candidate pages from the remote wiki first
2. Then it uses an LLM to synthesize a grounded answer
3. When --save is used, it updates:
   - wiki/syntheses/*.md
   - wiki/index.md
   - wiki/log.md
