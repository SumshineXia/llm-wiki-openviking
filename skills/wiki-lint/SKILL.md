---
name: wiki-lint
description: 当用户要求对远端 wiki 做质量 lint 检查（结构质量与链接卫生）时使用；中文触发描述优先。
---

# Wiki Lint

## 触发场景（自然语言）

当用户表达以下意图时使用：

- “对 my-kb 执行 wiki-lint”
- “执行 wiki-lint”
- “检查有没有孤儿页/重复标题/stub”
- “看下远端 wiki 的链接质量”

## 职责边界（不要做什么）

- 只做 lint 质量检查（链接与结构质量）
- 不调用 LLM，不做内容改写
- 不执行 bootstrap/ingest/query/health/graph

## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-lint/scripts/run.sh --kb-name <kb-name> --pretty
```

## 强约束

- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
