---
name: wiki-health
description: 当用户要求对 KB 执行 wiki-health（检查远端 wiki 结构完整性）时使用；中文触发描述优先。
---

# Wiki Health

## 触发场景（自然语言）

当用户表达以下意图时使用：

- "对 my-kb 执行 wiki-health"
- "执行 wiki-health"
- "检查结构是否完整"
- "ingest 后再做一次健康检查"
- "检查控制台直接改动造成的知识库漂移"
- "检查 index 和真实页面是否一致"
- "检查 raw 里有没有未 ingest 的资料"
- "帮我安全修复 wiki-health 能修的问题"
- "补录 log，但不要伪造真实操作时间"
- "执行 wiki-health repair-all"

## 职责边界（不要做什么）

- 默认只检查，不写远端
- 用户明确要求时可以执行安全修复（--repair-*）
- 不调用 LLM，不做总结与润色
- 不删除、不移动远端页面
- 不自动 ingest raw
- 不自动生成 overview 语义总结
- `index.md` 可以重建
- `log.md` 只能追加 `health-reconcile` 补录行
- `health-reconcile` 补录不代表原始操作时间
- 如果 `log.md` 缺失，`--repair-log` 会先创建初始 log，再补录已有 source/synthesis 页面
- 不执行 ingest/query/lint/graph

## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

### 基础检查

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" --kb-name <kb-name> --pretty
```

### 重建 index

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --repair-index \
  --pretty
```

### 修复缺失结构

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --repair-structure \
  --pretty
```

### 补录 log

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --repair-log \
  --pretty
```

### 执行全部安全修复

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" \
  --kb-name <kb-name> \
  --repair-all \
  --pretty
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

可选参数：`--config <path>`、`--profile <name>`。

## 强约束

- 不要调用项目根目录 `scripts/` 下的命令
- 不要使用项目级 `scripts` 模块调用方式
- 不要要求用户 clone 项目
