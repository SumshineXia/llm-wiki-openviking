# llm-wiki-openviking

一个基于 **OpenViking 远端存储**、通过 **OpenCode skills + 本地 helper scripts** 驱动的远端版 llm-wiki 工作流。

---

## 1. 项目简介

`llm-wiki-openviking` 的目标，是把原始 `llm-wiki-agent` 那种“基于本地目录生成 wiki”的方式，改造成：

- **OpenViking** 部署在远端容器中，作为主存储和主检索层
- **OpenCode** 运行在每个用户本地，作为操作台
- **Skills** 运行在每个用户本地，负责约束 workflow
- **Helper scripts** 运行在每个用户本地，直接读写远端 `viking://resources/<kb>/...`



### 1.1 什么是 llm-wiki，有什么用

`llm-wiki` 可以理解为一种“让 Agent 持续维护知识库”的工作流，而不只是一个静态文档仓库。

它的核心思路是：

- 把原始资料放入 `raw/`
- 让 Agent 逐步把这些资料整理成结构化的 `wiki/` 页面
- 通过 `index.md`、`overview.md`、`log.md`、`sources/`、`entities/`、`concepts/`、`syntheses/` 这些层次，把知识沉淀成一个可持续扩展、可相互链接、可被再次查询和复用的 wiki

相比“把文件直接堆在知识库里然后检索”，llm-wiki 更强调两件事：

- **知识整理**：不是只保存原始材料，而是把材料转成更容易理解、复用和追踪的 wiki 页面
- **持续演化**：随着新 source 的加入，wiki 会不断补充实体页、概念页、综合页和图谱，而不是一次性生成后就不再更新

因此，llm-wiki 特别适合：

- 资料很多、但希望逐渐沉淀出知识结构的场景
- 不满足于“只做 RAG 检索”，而希望形成可阅读、可维护、可演化 wiki 的场景
- 希望让 Agent 按固定 workflow 持续维护知识库，而不是完全手工整理文档的场景

在本项目里，llm-wiki 的作用可以概括为：

**把远端 OpenViking 中的原始资料，逐步编译成一个结构化、可查询、可维护、可视化的远端 wiki。**

### 1.2 当前已实现能力

当前版本已经跑通以下主链路：

1. **Bootstrap**：初始化一个远端知识库目录结构
2. **Health**：检查知识库结构是否完整
3. **Ingest**：从远端 `raw/` 读取 source，生成或更新 `wiki/` 内容
4. **Query**：基于远端 wiki 回答问题
5. **Save synthesis**：把查询结果保存到 `wiki/syntheses/`
6. **Lint**：检查 wiki 的结构质量问题
7. **Graph**：从显式内部链接生成 `graph.json` 和 `graph.html`

---

## 2. 整体架构

### 2.1 逻辑架构

```text
OpenCode（本地）
  ├─ skills/wiki-health
  ├─ skills/wiki-ingest
  ├─ skills/wiki-query
  ├─ skills/wiki-lint
  └─ skills/wiki-graph
          ↓
本地 Python helper scripts
  ├─ wiki_health_remote.py
  ├─ wiki_ingest_remote.py
  ├─ wiki_query_remote.py
  ├─ wiki_lint_remote.py
  └─ wiki_graph_remote.py
          ↓
OVFS adapter（ovfs.py）
          ↓
OpenViking HTTP / WebDAV / Resource API
          ↓
远端 OpenViking 知识库
  viking://resources/<kb>/raw/
  viking://resources/<kb>/wiki/
  viking://resources/<kb>/graph/
```

### 2.2 关键设计原则

本项目遵循以下原则：

- **OpenViking 是主存储，不是同步目标**
- **本地 skills 只负责 workflow，不直接保存业务状态**
- **所有 wiki 内容都以远端 ****\`\`**** 为准**
- **本地 helper scripts 通过 ****\`\`**** 统一访问远端存储**



---

## 3. 目录结构说明

```text
llm-wiki-openviking/
├── config/
│   └── llm-wiki-config.json
├── schema/
│   └── wiki_schema.md
├── scripts/
│   ├── __init__.py
│   ├── ovfs.py
│   ├── kb_bootstrap.py
│   ├── wiki_health_remote.py
│   ├── wiki_ingest_remote.py
│   ├── wiki_query_remote.py
│   ├── wiki_lint_remote.py
│   └── wiki_graph_remote.py
├── skills/
│   ├── wiki-health/
│   │   └── SKILL.md
│   ├── wiki-ingest/
│   │   └── SKILL.md
│   ├── wiki-query/
│   │   └── SKILL.md
│   ├── wiki-lint/
│   │   └── SKILL.md
│   └── wiki-graph/
│       └── SKILL.md
├── bootstrap_seed/
└── README.md
```

### 3.1 核心文件说明

#### `schema/wiki_schema.md`

统一定义知识库结构、页面类型、workflow 规则。

这是整个项目的“单一真相（single source of truth）”。

#### `scripts/ovfs.py`

OpenViking 文件系统适配层。

负责：

- 读文本
- 写文本
- 建目录
- 列目录
- Tree
- stat / exists
- temp\_upload
- add\_resource / add\_local\_resource
- WebDAV fallback

#### `scripts/kb_bootstrap.py`

初始化一个新的远端知识库。

#### `scripts/wiki_*_remote.py`

真正执行 workflow 的 helper scripts：

- `wiki_health_remote.py`
- `wiki_ingest_remote.py`
- `wiki_query_remote.py`
- `wiki_lint_remote.py`
- `wiki_graph_remote.py`

#### `skills/wiki-*/SKILL.md`

供 OpenCode 读取的 skill 文档。

这些 skill 不直接替代脚本，而是把“如何用自然语言调用这些脚本”的规则告诉 OpenCode。

---

## 4. 远端知识库结构

每个知识库以如下 URI 作为根目录：

```text
viking://resources/<kb>/
```

例如：

```text
viking://resources/my-kb/
```

初始化后结构如下：

```text
viking://resources/<kb>/
├── raw/
├── wiki/
│   ├── index.md
│   ├── overview.md
│   ├── log.md
│   ├── sources/
│   ├── entities/
│   ├── concepts/
│   └── syntheses/
└── graph/
```

### 4.1 各目录含义

#### `raw/`

原始资料区。

放原始 source，例如：

- 原始 markdown
- 清洗后的网页文本
- 其他可被 ingest 的文本材料

#### `wiki/`

Wiki 主体内容区。

##### `wiki/index.md`

全局目录页。

##### `wiki/overview.md`

全局总览页。

##### `wiki/log.md`

操作日志页。

##### `wiki/sources/`

每份 source 对应的 source page。

##### `wiki/entities/`

实体页，例如工具、项目、公司、人名、术语等。

##### `wiki/concepts/`

概念页，例如方法、架构、流程、理论等。

##### `wiki/syntheses/`

问答后保存的综合结论页。

#### `graph/`

图谱产物区。

当前会生成：

- `graph.json`
- `graph.html`

---

## 5. 环境准备

## 5.1 前置条件

你需要准备好：

1. **一个可访问的 OpenViking 服务**
2. **本地 Python 运行环境 （ >= 3.10)**
3. **本地 OpenCode**
4. **一个可用的api-key （用于 ingest/query）**

### 5.2 OpenViking 服务要求

你应该已经有一个正在运行的 OpenViking 服务，例如：

```text
http://localhost:1933
```

或者公司内部地址，例如：

```text
http://openviking.your-company.internal:1933
```

### 5.3 配置 OpenViking 客户端地址

本项目默认会优先读取：

- 环境变量：
  - `OPENVIKING_URL`
  - `OPENVIKING_API_KEY`
  - `OPENVIKING_TIMEOUT`
- 或文件：
  - `~/.openviking/ovcli.conf`

最常见的本地配置方式：

```json
{"url":"http://localhost:1933"}
```

如果是公司远端环境，则改成：

```json
{"url":"http://你的-openviking-服务地址:1933"}
```

### 5.4 配置模型

本项目支持通过以下三层方式配置模型：

优先级从高到低：

1. 命令行参数
2. `config/*.json`
3. 环境变量

推荐使用统一配置文件：

`config/llm-wiki-config.json`

示例：

```json
{
  "openai_api_key": "",
  "openai_base_url": "",
  "openai_model": ""
}
```

如果你不想把密钥写在文件里，也可以用环境变量：

```bash
export OPENAI_API_KEY="你的key"
export OPENAI_BASE_URL="你的base_url"
export OPENAI_MODEL="gpt-4o-mini"
```

---

## 6. 安装与接入

### 6.1 克隆项目

```bash
git clone <你的仓库地址>
cd llm-wiki-openviking
```

### 6.2 Python 依赖

建议在虚拟环境中执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install requests openai
```

如果你的环境里已经安装过这些依赖，也可以直接使用现有环境。

### 6.3 验证 OpenViking 连接

最小验证：

```bash
python3 -m scripts.ovfs
```

如果输出 health JSON，说明本地 helper scripts 已经能连到远端 OpenViking。

---

## 7. 如何把 skills 接入 OpenCode

这一节非常重要。

你平时真正使用，不是手敲 Python 命令，而是通过 **OpenCode + skills**。

### 7.1 skills 的本质

本项目的 `skills/` 目录下，每个子目录就是一个 skill：

- `wiki-health`
- `wiki-ingest`
- `wiki-query`
- `wiki-lint`
- `wiki-graph`

每个 skill 目录里都有一个 `SKILL.md`，OpenCode 读取它后，就会知道：

- 这个 skill 的目的
- 什么时候该用
- 该执行什么命令
- 需要哪些参数

### 7.2 接入方式

你需要确保 **OpenCode 能扫描到本项目的 ****\`\`**** 目录**。

常见做法有两种：

#### 方式 A：把 skills 目录复制到 OpenCode 的 skills 搜索目录

适合不会改本地开发环境的人。

#### 方式 B：软链接到 OpenCode 的 skills 搜索目录

适合开发阶段，更新方便。

例如，你可以把本项目 `skills/` 下的各个 skill 目录，链接到你本机 OpenCode 的 skills 目录中。

> 具体 OpenCode 本地 skills 搜索路径，以你当前 OpenCode 的实际配置为准。\
> 核心要求只有一个：**让 OpenCode 能看到 ****\`\`**** 这些文件。**

### 7.3 建议的本地使用方式

推荐你这样开项目：

1. 在终端进入项目目录：

```bash
cd llm-wiki-openviking
```

2. 用 OpenCode 打开这个项目

3. 确保 OpenCode 当前能识别本项目里的 skills

4. 然后用**自然语言**或**显式引用 skill 名称**来驱动 workflow

---

## 8. 两种使用方式：脚本方式 vs OpenCode 方式

本项目支持两种使用方式。

### 8.1 方式一：直接脚本调用

这是最底层、最确定的方式，适合调试。

例如：

```bash
python3 -m scripts.kb_bootstrap --kb-name my-kb
```

### 8.2 方式二：OpenCode + skill / 自然语言

这是你平时真正应该使用的方式。

OpenCode 读取 skill 后，你可以：

- 显式让它用某个 skill
- 也可以直接用自然语言描述任务

这时 OpenCode 会根据 skill 说明，自己选择调用哪一个 helper script。

**也就是说：脚本是执行层，skill 是操作入口。**

---

## 9. 开箱即用：第一次完整跑通

下面是新手第一次使用时，最推荐的完整流程。

## 9.1 第一步：初始化知识库

### 脚本方式

```bash
python3 -m scripts.kb_bootstrap --kb-name my-kb
```

## 9.2 第二步：检查健康状态

### 脚本方式

```bash
python3 -m scripts.wiki_health_remote --kb-name my-kb --pretty
```

### OpenCode 里用 skill 的方式

- `请对 my-kb 执行 wiki-health。`
- `运行 wiki-health，检查 my-kb 的结构是否完整。`

### 结果解读

- `status: ok`：结构正常
- `status: warn`：结构没坏，但还有优化项
- `status: error`：有必要修复的问题

---

## 9.3 第三步：准备 raw source

在真正 ingest 之前，你需要先把 source 放到远端：

```text
viking://resources/my-kb/raw/
```

### 推荐做法

先通过你已有的 OpenViking 文件上传方式，把 `.md` 原始文本上传到：

```text
viking://resources/my-kb/raw/你的文件.md
```

例如：

```text
viking://resources/my-kb/raw/openviking-overview.md
```

或者：

```text
viking://resources/my-kb/raw/ov-是什么.md
```

> 当前项目的主流程假设：**raw 文件已经存在于 OpenViking 远端**。

---

## 9.4 第四步：执行 ingest

### 脚本方式

```bash
python3 -m scripts.wiki_ingest_remote \
  --kb-name my-kb \
  --source-uri viking://resources/my-kb/raw/ov-是什么.md \
  --pretty
```


### OpenCode 里自然语言方式

你可以直接说：

- `请使用 wiki-ingest 处理 viking://resources/my-kb/raw/ov-是什么.md`
- `把 my-kb 里的 raw/ov-是什么.md ingest 成 wiki 页面。`
- `对这个 source 执行远端 wiki ingest，并更新 index、overview、log。`

### ingest 完成后会更新的内容

- `wiki/sources/*.md`
- `wiki/entities/*.md`
- `wiki/concepts/*.md`
- `wiki/index.md`
- `wiki/overview.md`
- `wiki/log.md`

---

## 9.5 第五步：再跑一次 health

```bash
python3 -m scripts.wiki_health_remote --kb-name my-kb --pretty
```

OpenCode 自然语言：

- `对 my-kb 再执行一次 wiki-health。`
- `检查 ingest 之后知识库结构是否正常。`

---

## 9.6 第六步：执行 query

### 脚本方式

```bash
python3 -m scripts.wiki_query_remote \
  --kb-name my-kb \
  --question "OpenViking 是什么？它和传统知识库有什么区别？" \
  --pretty
```

### OpenCode 里自然语言方式

- `请使用 wiki-query 回答：OpenViking 是什么？它和传统知识库有什么区别？`
- `基于 my-kb 的远端 wiki 回答这个问题。`

### 这一步做了什么

- 从远端 `wiki/` 中选候选页面
- 把候选页面喂给模型
- 生成基于 wiki 内容的答案

---

## 9.7 第七步：保存 synthesis

### 脚本方式

```bash
python3 -m scripts.wiki_query_remote \
  --kb-name my-kb \
  --question "OpenViking 是什么？它和传统知识库有什么区别？" \
  --save \
  --pretty
```

### 自定义 synthesis slug

```bash
python3 -m scripts.wiki_query_remote \
  --kb-name my-kb \
  --question "OpenViking 是什么？它和传统知识库有什么区别？" \
  --save \
  --slug openviking-overview \
  --pretty
```

### OpenCode 自然语言方式

- `请把刚才的答案保存为 synthesis。`
- `对这个问题执行 wiki-query，并把结果保存到 syntheses。`
- `保存一个名为 openviking-overview 的 synthesis。`

### 保存后会更新

- `wiki/syntheses/*.md`
- `wiki/index.md`
- `wiki/log.md`

---

## 9.8 第八步：执行 lint

### 脚本方式

```bash
python3 -m scripts.wiki_lint_remote --kb-name my-kb --pretty
```

### OpenCode 自然语言方式

- `请对 my-kb 执行 wiki-lint。`
- `检查这个远端 wiki 的结构质量问题。`

### lint 目前会检查

- broken internal links
- orphan pages
- pages without outbound internal links
- duplicate page titles
- stub pages

---

## 9.9 第九步：生成 graph

### 脚本方式

```bash
python3 -m scripts.wiki_graph_remote --kb-name my-kb --pretty
```

### dry-run

```bash
python3 -m scripts.wiki_graph_remote --kb-name my-kb --dry-run --pretty
```

### OpenCode 自然语言方式

- `请为 my-kb 生成 wiki graph。`
- `使用 wiki-graph 构建 graph.json 和 graph.html。`

### graph 产物

- `graph/graph.json`
- `graph/graph.html`

---

## 10. 在 OpenCode 中推荐怎么说

这部分是最重要的“实战话术”。

### 10.1 最稳的方式：显式说 skill 名

推荐你在 OpenCode 里这样说：

- `请使用 wiki-health 检查 my-kb。`
- `请使用 wiki-ingest 处理 viking://resources/my-kb/raw/ov-是什么.md。`
- `请使用 wiki-query 回答：OpenViking 是什么？它和传统知识库有什么区别？`
- `请使用 wiki-lint 检查当前 wiki。`
- `请使用 wiki-graph 构建 graph。`

这样 OpenCode 更容易选对 skill。

### 10.2 也可以直接说自然语言

例如：

- `帮我初始化一个 my-kb 远端知识库。`
- `把这个 raw source 变成 wiki 页面。`
- `基于远端 wiki 回答这个问题并保存为 synthesis。`
- `帮我检查 wiki 有没有 orphan page。`
- `帮我生成 graph.html。`

### 10.3 建议的真实工作流话术

你平时可以这样用：

1. `先对 my-kb 跑一次 wiki-health。`
2. `把 viking://resources/my-kb/raw/xxx.md ingest 成 wiki。`
3. `再做一次 health。`
4. `回答这个问题，并保存为 synthesis。`
5. `对当前 wiki 做 lint。`
6. `生成新的 graph。`

这就是最完整的一轮闭环。

---

## 11. 常用命令速查

## 11.1 Bootstrap

```bash
python3 -m scripts.kb_bootstrap --kb-name my-kb
```

## 11.2 Health

```bash
python3 -m scripts.wiki_health_remote --kb-name my-kb --pretty
```

## 11.3 Ingest

```bash
python3 -m scripts.wiki_ingest_remote \
  --kb-name my-kb \
  --source-uri viking://resources/my-kb/raw/ov-是什么.md \
  --pretty
```

## 11.4 Ingest dry-run

```bash
python3 -m scripts.wiki_ingest_remote \
  --kb-name my-kb \
  --source-uri viking://resources/my-kb/raw/ov-是什么.md \
  --dry-run \
  --pretty
```

## 11.5 Query

```bash
python3 -m scripts.wiki_query_remote \
  --kb-name my-kb \
  --question "OpenViking 是什么？它和传统知识库有什么区别？" \
  --pretty
```

## 11.6 Query + Save

```bash
python3 -m scripts.wiki_query_remote \
  --kb-name my-kb \
  --question "OpenViking 是什么？它和传统知识库有什么区别？" \
  --save \
  --pretty
```

## 11.7 Lint

```bash
python3 -m scripts.wiki_lint_remote --kb-name my-kb --pretty
```

## 11.8 Graph

```bash
python3 -m scripts.wiki_graph_remote --kb-name my-kb --pretty
```

