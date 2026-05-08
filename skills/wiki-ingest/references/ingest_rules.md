# Ingest Rules

## Scope

- 本流程仅负责将 `raw/` 下的单个 source ingest 到 `wiki/`。
- 本流程不负责 query 与 synthesis。

## Required Inputs

- `--kb-name`: 目标知识库名称。
- `--source-uri`: source 的完整 viking URI，通常位于 `raw/`。

## Optional Flags

- `--dry-run`: 仅输出写入计划，不执行远端写入。
- `--pretty`: 以格式化 JSON 输出执行结果。

## Write Targets

- `wiki/sources/<slug>.md`
- `wiki/entities/<slug>.md`
- `wiki/concepts/<slug>.md`
- `wiki/index.md`
- `wiki/overview.md`
- `wiki/log.md`
