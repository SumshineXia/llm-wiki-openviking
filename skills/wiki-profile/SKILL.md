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

必须使用本 skill 自带脚本（可在任意目录执行）：

```bash
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh list --pretty
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh current --pretty
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh use <profile>
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh show <profile> --pretty
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh bind <profile> --dir .
bash ~/.config/opencode/skills/wiki-profile/scripts/run.sh unbind --dir .
```

通用可选参数：

- `--config <path>` 指定配置文件路径
- `--profile <name>` 仅影响本次命令的 profile 选择

## 强约束

- 仅实现 `list/current/use/show/bind/unbind`
- 不实现 `import`
- `show` 必须掩码 `api_key`
