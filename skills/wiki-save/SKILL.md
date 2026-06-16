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

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --payload-file <payload.json> \
  --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

或使用显式参数模式：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --answer-file <answer.md> \
  --question "<question>" \
  --title "<title>" \
  --used-page "viking://resources/<kb>/wiki/sources/x.md" \
  --pretty
```
