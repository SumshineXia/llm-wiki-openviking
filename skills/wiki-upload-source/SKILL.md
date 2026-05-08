---
name: wiki-upload-source
description: 当用户要求把本地文件上传到某个 KB 的 raw/ 路径时使用；中文触发描述优先。
---

# Wiki Upload Source

## 触发场景（自然语言）

当用户表达以下意图时使用：

- “把这个文件上传到 my-kb 的 raw/ 下”
- “把这个本地 md 上传到 my-kb 的 raw/”
- “执行 wiki-upload-source”
- “把文件放到某个 KB 的 raw 目录”

## 职责边界（不要做什么）

- 只负责把本地文件上传到目标 KB 的 `raw/` 路径
- 不做 ingest、query、health、lint、graph
- 不重写 wiki 页面结构

## 执行方式

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-upload-source/scripts/run.sh \
  --kb-name <kb-name> \
  --file <local-file-path> \
  --to raw/<target-file-name>.md \
  --pretty
```

## 强约束

- `--to` 必须以 `raw/` 开头
- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
