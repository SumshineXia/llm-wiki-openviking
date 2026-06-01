# Query Rules

## Scope

- 本流程仅负责基于远端 `wiki/` 页面执行问答。
- 输出 `save_payload`，供 `wiki-save` 保存答案。
- 可选将答案保存为 synthesis 页面（兼容模式）。
- 本流程不负责 ingest 原始 source。

## Required Inputs

- `--kb-name`: 目标知识库名称。
- `--question`: 自然语言问题。

## Optional Flags

- `--save`: legacy 兼容路径；会重新检索并再次调用 LLM，然后写入 `wiki/syntheses/`、`wiki/index.md`、`wiki/overview.md`、`wiki/log.md`。
- `--slug`: 指定 synthesis 文件名 slug（仅在 `--save` 时生效）。
- `--save-payload-file`: 将 `wiki-save` payload 写入指定路径。
- `--no-save-payload-file`: 禁止自动写入临时 payload 文件。
- `--output-file`: 将完整 query JSON 写入指定路径。
- `--pretty`: 以格式化 JSON 输出执行结果。

## Save Target Rules

- 当 `--slug` 提供时，目标路径为 `wiki/syntheses/<slug>.md`。
- 当 `--slug` 未提供时，优先基于 normalize 后的 `synthesis_title` 生成 `<title-slug>-<timestamp>.md`。
- 如果 title 为空或不可用，使用 fallback 标题 `综合结论` 生成 `综合结论-<timestamp>.md`。

## Write Targets When Saved

- `wiki/syntheses/<slug-or-generated>.md`
- `wiki/index.md`
- `wiki/overview.md`
- `wiki/log.md`

## Interactive Save Rule

- 交互式“保存刚才答案”必须使用 `wiki-save`（消费 `save_payload`）。
- 不要在交互式保存场景使用 `wiki-query --save`。

## Query Output（成功时）

- 核心字段：`status`、`kb_name`、`question`、`selected_pages`、`used_pages`、`answer_markdown`、`synthesis_title`。
- 保存衔接字段：`recommended_save_skill=wiki-save`、`save_payload`、`save_payload_path`（未禁用自动写文件时）。
- `save_payload` 包含：`kb_name`、`kb_root`、`question`、`answer_markdown`、`synthesis_title`、`used_pages`、`selected_pages`、`created_at`。

## Legacy Save Semantics

- `--save` 输出 `save_deprecated=true` 与 `legacy_save_requeries=true`。
- `--save` 表示“再执行一次 query 并直接保存”，不是“保存当前已有答案”。
