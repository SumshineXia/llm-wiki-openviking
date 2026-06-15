---
name: wiki-bootstrap
description: 当用户要初始化新的远端 OpenViking 知识库（创建 raw/wiki/graph 目录与 wiki 根页面）时使用；中文触发描述优先。
---

# Wiki Bootstrap

## 触发场景（自然语言）

当用户表达以下意图时使用：

- “请为 my-kb 初始化远端知识库结构”
- “初始化一个新的 KB”
- “给 my-kb 建好 raw/wiki/graph 目录”
- “执行 wiki-bootstrap”

## 职责边界（不要做什么）

- 只负责创建知识库基础目录与根页面骨架
- 不上传 source、不做 ingest、不做 query、不做 lint/health/graph
- 不修改其他知识库

## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-bootstrap/scripts/run.sh --kb-name <kb-name> --pretty
```

默认行为是基础目录和根页面创建请求会尽快返回，不等待 OpenViking 对页面完成语义处理。

显式等待索引完成：

```bash
bash ~/.config/opencode/skills/wiki-bootstrap/scripts/run.sh --kb-name <kb-name> --wait-for-indexing --pretty
```

可选参数：`--config <path>`、`--profile <name>`、`--wait-for-indexing`。

仅预览（不写入）：

```bash
bash ~/.config/opencode/skills/wiki-bootstrap/scripts/run.sh --kb-name <kb-name> --dry-run --pretty
```

## 强约束

- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
