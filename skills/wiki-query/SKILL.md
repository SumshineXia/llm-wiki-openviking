---
name: wiki-query
description: Use when the user asks natural-language Q&A over a remote KB wiki, including follow-up asks to save the answer as synthesis. Trigger phrases include "基于 my-kb 回答这个问题", "执行 wiki-query", "请把刚才答案保存为 synthesis", "保存一个名为 <slug> 的 synthesis", and "--save/--slug" style requests.
---

# Wiki Query

## 触发场景（自然语言）

当用户表达以下意图时使用：

- “基于 my-kb 回答这个问题”
- “执行 wiki-query”
- “把刚才答案保存为 synthesis”

## 职责边界（不要做什么）

- 只处理问答（query），可选保存 synthesis
- 不做 ingest、不上传 source、不做 health/lint/graph
- 不修改与本次问答无关的 wiki 页面

## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-query/scripts/run.sh \
  --kb-name <kb-name> \
  --question "<your question>" \
  --pretty
```

保存为 synthesis：

```bash
bash ~/.config/opencode/skills/wiki-query/scripts/run.sh \
  --kb-name <kb-name> \
  --question "<your question>" \
  --save \
  --slug <optional-slug> \
  --pretty
```

## 回答后默认追问

- 每次成功返回问答结果后，默认追加一句：`是否保存为 synthesis？`
- 若用户同意保存，则执行带 `--save` 的命令
- 若用户提供名称，则追加 `--slug <slug>`

## 强约束

- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
