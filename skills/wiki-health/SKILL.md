---
name: wiki-health
description: 当用户要求对 KB 执行 wiki-health（检查远端 wiki 结构完整性）时使用；中文触发描述优先。
---

# Wiki Health

## 触发场景（自然语言）

当用户表达以下意图时使用：

- “对 my-kb 执行 wiki-health”
- “执行 wiki-health”
- “检查结构是否完整”
- “ingest 后再做一次健康检查”

## 职责边界（不要做什么）

- 只做结构完整性检查（目录、根页面、索引链接、source-log 覆盖）
- 默认只检查，不写远端
- 不调用 LLM，不做总结与润色
- 不执行 ingest/query/lint/graph

## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" --kb-name <kb-name> --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

可选参数：`--config <path>`、`--profile <name>`。

当用户明确要求“修复 index / 重建 index / repair index”时，可运行：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --profile <profile> \
  --repair-index \
  --pretty
```

`--repair-index` 只重建 `wiki/index.md`，不删除页面，不调用 LLM，并保留 index 中 managed section 之外的手工内容。

## 强约束

- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
