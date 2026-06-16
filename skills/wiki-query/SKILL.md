---
name: wiki-query
description: 当用户要求基于远端 KB wiki 进行自然语言问答（并可选保存为 synthesis）时使用；中文触发描述优先。
---

# Wiki Query

## 触发场景（自然语言）

当用户表达以下意图时使用：

- “请基于 my-kb 回答这个问题”
- “基于 my-kb 回答这个问题”
- “执行 wiki-query”
- “基于 my-kb 回答后，我再决定要不要保存”

## 职责边界（不要做什么）

- 只处理问答（query）并输出可供 `wiki-save` 使用的 payload
- 不做 ingest、不上传 source、不做 health/lint/graph
- 不修改与本次问答无关的 wiki 页面

## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --question "<your question>" \
  --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

可选参数：`--config <path>`、`--profile <name>`。

兼容模式（legacy，仅兼容保留，不建议交互式场景使用）：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --question "<your question>" \
  --save \
  --slug <optional-slug> \
  --pretty
```

## 回答后默认追问

- 每次成功返回问答结果后，默认追加一句：`是否保存为 synthesis？`
- `wiki-query` 成功输出会包含：`save_payload`、`save_payload_path`、`recommended_save_skill=wiki-save`
- 若用户同意保存，必须调用同级 `wiki-save` skill 的脚本。前提是 `wiki-query` 与 `wiki-save` 已作为 llm-wiki skills 同批安装在同一个 skills 父目录下。先将当前 `wiki-query` skill 根目录记为 `<THIS_SKILL_DIR>`，再调用：`bash "<THIS_SKILL_DIR>/../wiki-save/scripts/run.sh" --payload-file <save_payload_path> --pretty`
- 不要在交互式“保存刚才答案”场景调用 `wiki-query --save`
- `wiki-query --save` 会重新检索并再次调用 LLM，不是“保存刚才答案”的无损复用路径

## legacy 语义

- `--save` 是兼容保留路径（deprecated）
- 它仍会完整执行一次 query（检索 + LLM），然后直接写入 synthesis 与 index/overview/log
- 因此 `--save` 不是对已有答案的“仅保存”操作

## 强约束

- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
