---
name: wiki-ingest
description: 当用户要求把远端 raw source ingest 成 wiki 页面（并更新 index/overview/log）时使用；中文触发描述优先。
---

# Wiki Ingest

## 触发场景（自然语言）

当用户表达以下意图时使用：

- “对 my-kb 执行 wiki-ingest”
- “把 raw/*.md ingest 成 wiki 页面”
- “对这个 source 做远端 ingest”
- “更新 index/overview/log”

## 职责边界（不要做什么）

- 只处理 ingest：从 `raw/` 生成或更新 wiki 页面
- 不回答问答请求（query）
- 不做 health/lint/graph，不上传本地文件

## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-ingest/scripts/run.sh \
  --kb-name <kb-name> \
  --source-uri <full-raw-source-uri> \
  --pretty
```

仅预览（不写入）：

```bash
bash ~/.config/opencode/skills/wiki-ingest/scripts/run.sh \
  --kb-name <kb-name> \
  --source-uri <full-raw-source-uri> \
  --dry-run \
  --pretty
```

## 强约束

- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
