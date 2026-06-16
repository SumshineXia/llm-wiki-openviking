---
name: wiki-profile
description: 当用户需要查看或切换 llm-wiki-openviking 配置 profile（list/current/use/show/bind/unbind）时使用。
---

# Wiki Profile

## 触发场景（自然语言）

- “列出当前有哪些 profile”
- “当前生效的是哪个 profile”
- “切到 profile xxx”
- “给这个目录绑定 profile xxx”

## 执行方式

必须使用本 skill 自带脚本。不要写死 skills 的安装根目录。

执行时，先将当前 skill 根目录记为 `<THIS_SKILL_DIR>`，也就是当前 `SKILL.md` 所在目录；然后调用：

```bash
bash "<THIS_SKILL_DIR>/scripts/run.sh" list --pretty
bash "<THIS_SKILL_DIR>/scripts/run.sh" current --pretty
bash "<THIS_SKILL_DIR>/scripts/run.sh" use <profile>
bash "<THIS_SKILL_DIR>/scripts/run.sh" show <profile> --pretty
bash "<THIS_SKILL_DIR>/scripts/run.sh" bind <profile> --dir .
bash "<THIS_SKILL_DIR>/scripts/run.sh" unbind --dir .
```

不要把 `<THIS_SKILL_DIR>` 替换成仓库路径，也不要替换成任何固定的 skills 安装目录。

通用可选参数：

- `--config <path>` 指定配置文件路径
- `--profile <name>` 仅影响本次命令的 profile 选择

## 强约束

- 仅实现 `list/current/use/show/bind/unbind`
- 不实现 `import`
- `show` 必须掩码 `api_key`
