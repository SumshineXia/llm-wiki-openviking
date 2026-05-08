---
name: wiki-health
description: Use when the user asks to run wiki-health for a KB, re-check structural integrity after ingest/query, or verify remote wiki structure completeness (dirs, root pages, key-page validity, index targets, source-log coverage). Trigger phrases include "执行 wiki-health", "检查结构是否完整", "再执行一次 health", and "ingest 后检查知识库结构".
---

# Wiki Health

## 触发场景（自然语言）

当用户表达以下意图时使用：

- “执行 wiki-health”
- “检查结构是否完整”
- “ingest 后再做一次健康检查”

## 职责边界（不要做什么）

- 只做结构完整性检查（目录、根页面、索引链接、source-log 覆盖）
- 不调用 LLM，不做总结与润色
- 不执行 ingest/query/lint/graph

## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-health/scripts/run.sh --kb-name <kb-name> --pretty
```

## 强约束

- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
