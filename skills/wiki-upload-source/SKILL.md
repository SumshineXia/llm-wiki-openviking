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

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --file <local-file-path> \
  --to raw/<target-file-name>.md \
  --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

可选参数：`--config <path>`、`--profile <name>`。

## 上传后说明

上传成功后，返回结果中包含 suggested_ingest_uri 和 next_step。
OpenViking 可能会将上传的资源转换为同名目录 bundle。
使用 suggested_ingest_uri 调用 wiki-ingest 即可，wiki-ingest 会自动处理。

## 强约束

- `--to` 必须以 `raw/` 开头
- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
