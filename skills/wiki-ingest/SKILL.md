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

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --source-uri <full-raw-source-uri> \
  --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

可选参数：`--config <path>`、`--profile <name>`、`--max-context-chars <int>`、`--max-existing-page-names <int>`、`--long-doc-threshold <int>`、`--chunk-size <int>`、`--chunk-overlap <int>`、`--max-chunks <int>`、`--allow-partial-chunks`。

- `--max-context-chars`：用于控制注入 LLM prompt 的 `index/overview` 节选长度上限，默认 `12000`。
- `--max-existing-page-names`：用于控制注入 LLM prompt 的已存在 entity/concept 页文件名数量上限，默认 `100`。
- `--long-doc-threshold`：source 字符数超过该阈值时启用长文档 chunk/reduce 流程，默认 `30000`。
- `--chunk-size`：每个分块最大字符数，默认 `18000`。
- `--chunk-overlap`：相邻分块重叠字符数，默认 `1000`，必须小于 `--chunk-size`。
- `--max-chunks`：允许处理的最大分块数，默认 `20`；超过时默认直接失败，不做 source 截断。
- `--allow-partial-chunks`：仅允许跳过失败的 chunk summary（至少成功 1 块）；不允许 source truncation。

行为说明：

- `index.md` / `overview.md` 仍会完整读取并用于确定性更新。
- 传给 LLM 的上下文只使用节选（超长时保留头尾并标注截断）。
- 已存在 entity/concept 名称优先从 `index.md` 对应 section 提取（兼容中文 section 与 legacy 英文 section）；提取不到时才做一层目录列表 fallback（`recursive=false`）。
- 长文档模式先分块摘要，再基于 `schema/source_uri/source_slug/index_excerpt/overview_excerpt/existing page names/chunk summaries` 做 reduce，不会把完整 source 直接送入 reduce prompt。
- `--allow-partial-chunks` 开启后只影响分块摘要阶段：失败块可跳过并记录失败数；若所有分块都失败则整体失败。

仅预览（不写入）：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --source-uri <full-raw-source-uri> \
  --dry-run \
  --pretty
```

## Source Bundle 说明

当用户要求 ingest raw 中某个上传资源时，不要假设 raw/<name> 是单个文件。
OpenViking 可能把任意上传文件转换成 raw/<name>/ 目录 bundle。
该 bundle 下可能包含 .abstract.md、.overview.md、正文 md 和多层子目录。
wiki-ingest 会递归查找正文 md，并跳过 metadata md。

如果用户只给自然语言描述，没有给 source-uri，先浏览 raw/ 目录定位最匹配的 raw source bundle URI，再把该 URI 传给 --source-uri。

## 强约束

- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
