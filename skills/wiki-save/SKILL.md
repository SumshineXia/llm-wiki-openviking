---
name: wiki-save
description: 当用户要求把已有答案保存为远端 KB 的 synthesis（更新 index/overview/log）时使用；中文触发描述优先。
---

# Wiki Save

## 触发场景（自然语言）

- “把刚才答案保存为 synthesis”
- “执行 wiki-save”
- “根据 payload 文件写入 wiki/syntheses”

## 职责边界（不要做什么）

- 只保存已有答案，不重新 query
- 不做 ingest/upload/health/lint/graph
- 不调用 LLM
- 不读取 OpenAI 配置（`openai_api_key` / `openai_base_url` / `openai_model`）
- 冲突策略默认 `on-conflict=update`

## 执行方式

```bash
bash ~/.config/opencode/skills/wiki-save/scripts/run.sh \
  --payload-file <payload.json> \
  --pretty
```

或使用显式参数模式：

```bash
bash ~/.config/opencode/skills/wiki-save/scripts/run.sh \
  --kb-name <kb-name> \
  --answer-file <answer.md> \
  --question "<question>" \
  --title "<title>" \
  --used-page "viking://resources/<kb>/wiki/sources/x.md" \
  --pretty
```
