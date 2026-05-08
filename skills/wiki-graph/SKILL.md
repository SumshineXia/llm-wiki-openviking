---
name: wiki-graph
description: 当用户要求生成或刷新远端 wiki 图谱产物（graph.json/graph.html）时使用；中文触发描述优先。
---

# Wiki Graph

## 触发场景（自然语言）

当用户表达以下意图时使用：

- “请为 my-kb 生成 wiki graph”
- “为 my-kb 生成 wiki graph”
- “构建 graph.json 和 graph.html”
- “执行 wiki-graph”

## 职责边界（不要做什么）

- 只负责生成图谱产物（`graph.json`、`graph.html`）
- 不调用 LLM
- 不执行 bootstrap/ingest/query/health/lint

## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-graph/scripts/run.sh --kb-name <kb-name> --pretty
```

## 强约束

- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
