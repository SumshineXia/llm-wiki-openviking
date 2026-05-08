# Query Rules

## Scope

- 本流程仅负责基于远端 `wiki/` 页面执行问答。
- 可选将答案保存为 synthesis 页面。
- 本流程不负责 ingest 原始 source。

## Required Inputs

- `--kb-name`: 目标知识库名称。
- `--question`: 自然语言问题。

## Optional Flags

- `--save`: 将回答保存到 `wiki/syntheses/`。
- `--slug`: 指定 synthesis 文件名 slug（仅在 `--save` 时生效）。
- `--pretty`: 以格式化 JSON 输出执行结果。

## Save Target Rules

- 当 `--slug` 提供时，目标路径为 `wiki/syntheses/<slug>.md`。
- 当 `--slug` 未提供时，目标路径为 `wiki/syntheses/query-<timestamp>.md`。

## Write Targets When Saved

- `wiki/syntheses/<slug-or-generated>.md`
- `wiki/index.md`
- `wiki/log.md`
