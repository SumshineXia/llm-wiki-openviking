# llm-wiki-openviking（用户使用版）

## 是什么

`llm-wiki-openviking` 是一套给 OpenCode 用的远端知识库工作流：

- 你的知识库存放在 OpenViking（`viking://resources/<kb>/`）
- 你在 OpenCode 里直接用自然语言发指令
- skills 会把你的自然语言请求路由到对应流程（health / ingest / query / lint / graph 等）

目标是把 `raw/` 里的原始资料，持续整理成结构化 wiki（`index.md`、`overview.md`、`log.md`、`sources/`、`entities/`、`concepts/`、`syntheses/`），并支持问答与图谱。

---

## 安装

你只需要安装 skills 和本地配置，不需要把这个仓库作为日常工作目录。

**明确说明：**

- 不需要 clone 项目
- 不需要在项目根目录打开 OpenCode

### 1) 安装 skills 到 OpenCode

把本仓库的 `skills/wiki-*` 目录复制到你的 OpenCode 实际加载 skills 的目录中。该目录可能是默认目录，也可能是你自定义的目录；llm-wiki 不依赖固定安装路径，只要求每个 skill 内部保持如下相对结构：

```text
wiki-xxx/
  SKILL.md
  scripts/
    run.sh
    xxx.py
```

建议同批安装以下 skills，尤其是 `wiki-query` 与 `wiki-save` 需要位于同一个 skills 父目录下，才能通过相对路径完成"query -> 确认 -> wiki-save"流程：

- `skills/wiki-bootstrap`
- `skills/wiki-health`
- `skills/wiki-ingest`
- `skills/wiki-query`
- `skills/wiki-upload-source`
- `skills/wiki-save`
- `skills/wiki-lint`
- `skills/wiki-graph`
- `skills/wiki-profile`

如果你只想用部分能力，也可以只复制对应 skill。

---

## 配置

推荐流程：

1. 在 AIHub 复制单系统完整 `config.json`。
2. 用户手工把多个系统合并为 `profiles[]`（`version: 2`）配置。
3. 用 `wiki-profile use/current` 选择并确认当前 profile。
4. 在 OpenCode 里直接用自然语言执行 wiki-bootstrap/health/ingest/query/lint/graph。

创建或修改配置文件：

`~/.config/llm-wiki-openviking/config.json`

示例（单 profile 简化版）：

```json
{
  "openviking_url": "http://localhost:1933",
  "openviking_api_key": "",
  "openviking_timeout": 20,
  "openai_api_key": "",
  "openai_base_url": "",
  "openai_model": "gpt-4o-mini"
}
```

最少要保证：

- `openviking_url` 可访问
- `openai_api_key`（或你实际使用的兼容模型密钥）可用

多 profile 用户可使用：

```bash
export OPENCODE_SKILLS_DIR="<你的 OpenCode skills 目录>"

bash "$OPENCODE_SKILLS_DIR/wiki-profile/scripts/run.sh" list --pretty
bash "$OPENCODE_SKILLS_DIR/wiki-profile/scripts/run.sh" use <profile>
bash "$OPENCODE_SKILLS_DIR/wiki-profile/scripts/run.sh" current --pretty
```

---

## 在 OpenCode 中自然语言使用

完成安装和配置后，你可以在任意目录打开 OpenCode，直接用自然语言描述目标。

### 中文优先约定

- 页面标题和正文默认生成中文
- 技术术语、路径、命令、API 名保留英文
- 保持 CLI 参数、目录结构、JSON 字段名不变。

推荐顺序：

1. 先 bootstrap 新知识库
2. 再 health 检查结构
3. 上传或准备 raw source
4. 执行 ingest
5. 执行 query
6. query 后确认是否保存，再执行 wiki-save
7. 执行 lint 与 graph

---

## 每个 skill 的典型说法

下面给出常用 skill 的自然语言示例说法（可直接改 `<kb>`、`<source>`、`<问题>` 后使用）：

1. `wiki-bootstrap`
   - 「帮我为 `<kb>` 初始化远端知识库结构」
2. `wiki-health`
   - 「对 `<kb>` 执行 wiki-health，检查结构是否完整」
3. `wiki-ingest`
   - 「把 `<kb>` 的 `raw/<source>.md` ingest 成 wiki 页面，并更新 index/overview/log」
   - 说明：`wiki-ingest` 默认快速异步写入，不等待 OpenViking 后台 semantic/embedding/indexing 完成；刚写完后可直接读取页面，但语义 search/query 可能需要等待后台处理完成。如必须 ingest 结束后立刻进行语义检索，可使用 `--wait-for-indexing`。
4. `wiki-query`
   - 「基于 `<kb>` 回答这个问题：`<问题>`」
5. `wiki-save`
   - 「把刚才答案保存为 synthesis，slug 用 `<slug>`」
6. `wiki-upload-source`
   - 「把本地 `./notes.md` 上传到 `<kb>` 的 `raw/notes.md`」
7. `wiki-lint`
   - 「对 `<kb>` 执行 wiki-lint，看看有没有孤儿页或重复标题」
8. `wiki-graph`
   - 「为 `<kb>` 生成 wiki graph，输出 graph.json 和 graph.html」

### query -> 确认 -> wiki-save（推荐）

1. 先执行 `wiki-query` 获取答案。
2. 成功返回后确认是否保存为 synthesis。
3. 需要保存时执行 `wiki-save`（消费 query 输出的 payload，不重新检索）。

说明：legacy `wiki-query --save` 会重新检索并再次调用 LLM，不是“保存刚才答案”的无损复用路径。

### 常见自然语言用法

- 「先帮我为 `team-a/project-x` 做 wiki-bootstrap，再跑一次 wiki-health」
- 「把 `team-a/project-x` 的 `raw/demo.md` ingest 成 wiki 页面，并更新 index/overview/log」
- 「基于 `team-a/project-x` 回答：这个知识库当前的核心概念是什么？回答后我再决定是否保存」
- 「把 `wiki-query` 刚才返回的 payload 保存为 synthesis，slug 用 `core-concepts`」
- 「对 `team-a/project-x` 执行 wiki-lint，重点看孤儿页和重复标题」
- 「为 `team-a/project-x` 构建 graph.json 和 graph.html，先 dry-run 再生成」

---

## 常见问题

### Q1：必须在本仓库目录里运行吗？

不用。只要 llm-wiki skills 已安装到 OpenCode 实际加载的 skills 目录中，并且 `~/.config/llm-wiki-openviking/config.json` 配置正确，就可以在任意目录用 OpenCode。

### Q2：必须先 clone 本项目吗？

不需要 clone 项目。日常使用只依赖你本机安装好的 skills 与配置。

### Q3：没有触发到预期 skill 怎么办？

先把请求说得更明确，带上关键动作词和 kb 名称，例如「执行 wiki-ingest」「对 my-kb 执行 wiki-health」。

### Q4：query 的回答怎么沉淀到知识库？

推荐流程是 `wiki-query` 后先确认，再调用 `wiki-save`。`wiki-query --save` 仅 legacy 兼容，会重新检索并再次调用 LLM。

### Q5：graph 文件在哪？

默认在远端：`viking://resources/<kb>/wiki/graph/graph.json` 与 `viking://resources/<kb>/wiki/graph/graph.html`。

### Q6：为什么 wiki-ingest 结束后马上 query 可能搜不到新内容？

`wiki-ingest` 默认不等待 OpenViking 后台 semantic/embedding/indexing 完成，因此页面已经写入后，语义检索索引可能还在后台更新。稍等后台处理完成后再 query 即可；如果必须同步等待，可在 ingest 时加 `--wait-for-indexing`，但会明显变慢。

---

## 脱离项目目录验证

可以先离开项目目录，再手动执行 `wiki-health` 的脚本验证配置与调用链：

```bash
cd /tmp
export OPENCODE_SKILLS_DIR="<你的 OpenCode skills 目录>"
bash "$OPENCODE_SKILLS_DIR/wiki-health/scripts/run.sh" --kb-name team-a/project-x --pretty
```

---

## debug：手动 run.sh（放在最后）

当你怀疑 skill 调用链有问题时，可以手动执行每个 skill 目录里的 `scripts/run.sh` 做排查。

示例（按你的实际路径替换）：

```bash
export OPENCODE_SKILLS_DIR="<你的 OpenCode skills 目录>"

bash "$OPENCODE_SKILLS_DIR/wiki-health/scripts/run.sh" --kb-name my-kb
bash "$OPENCODE_SKILLS_DIR/wiki-ingest/scripts/run.sh" --kb-name my-kb --source-uri raw/demo.md
bash "$OPENCODE_SKILLS_DIR/wiki-query/scripts/run.sh" --kb-name my-kb --question "解释这个知识库的核心主题"
bash "$OPENCODE_SKILLS_DIR/wiki-save/scripts/run.sh" --payload-file /tmp/wiki-query-save.json
bash "$OPENCODE_SKILLS_DIR/wiki-lint/scripts/run.sh" --kb-name my-kb
bash "$OPENCODE_SKILLS_DIR/wiki-graph/scripts/run.sh" --kb-name my-kb
```

如果 `scripts/run.sh` 报错，优先检查：

- `~/.config/llm-wiki-openviking/config.json` 是否存在且字段正确
- OpenViking 服务是否可达
- 模型密钥与模型名是否可用
