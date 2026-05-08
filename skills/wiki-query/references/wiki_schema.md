# Wiki 结构规范

## 1. 知识库根目录

每个知识库存储在：

`viking://resources/<kb>/`

必需结构：

- `raw/` - 原始资料目录
- `wiki/` - 结构化 wiki 页面目录
- `wiki/index.md` - wiki 页面的规范索引
- `wiki/overview.md` - 知识库全局概览
- `wiki/log.md` - 时间顺序操作日志
- `wiki/sources/` - 由 raw 资料抽取的来源页
- `wiki/entities/` - 实体页
- `wiki/concepts/` - 概念页
- `wiki/syntheses/` - 问答综合页
- `graph/` - 图谱产物目录（如 `graph.json`、`graph.html`）

## 2. 页面类型

### 2.1 来源页
用途：总结单个原始资料，提取关键实体、概念、论断与链接。

位置：
`wiki/sources/<slug>.md`

### 2.2 实体页
用途：描述具名实体，例如人物、公司、项目、论文、库、工具、数据集、组织。

位置：
`wiki/entities/<slug>.md`

### 2.3 概念页
用途：描述抽象概念、方法、流程、架构、原则或反复出现的主题。

位置：
`wiki/concepts/<slug>.md`

### 2.4 综合页
用途：保存基于多个 wiki 页面推导出的查询答案。

位置：
`wiki/syntheses/<slug>.md`

## 3. 命名规则

- 文件名使用小写 kebab-case。
- 页面建立后文件名保持稳定。
- 名称尽量简短且具区分性。
- 同一核心实体或概念尽量保持唯一规范页。

## 4. 链接规则

- 内部引用使用 `[[wikilinks]]`。
- 优先链接到规范页，避免在多处重复解释。
- 除初始化占位页外，每页至少应有一个外链到相关页面。

## 5. 页面基础模板

每个 wiki 页面应包含：

- Title（标题）
- Type（类型）
- Summary（摘要）
- Main content（正文）
- Related links（相关链接）
- Source references（来源引用，按需）

## 6. 语言与不翻译约束

- 页面正文与说明性内容使用简体中文。
- 页面标题使用简体中文。
- JSON 字段名保持英文。
- 文件路径和目录名保持英文。
- `slug`、文件名、目录名、扩展名保持原格式，不做本地化翻译。

## 7. 索引规则

`wiki/index.md` 是 wiki 页面的规范目录。

应按以下分组组织：
- Sources
- Entities
- Concepts
- Syntheses

所有真实页面都应出现在 `wiki/index.md`。

## 8. 概览规则

`wiki/overview.md` 应总结：
- 主要主题
- 关键实体
- 核心概念
- 已知缺口
- 最近变更

内容应简洁，并在关键 ingest 操作后更新。

## 9. 日志规则

`wiki/log.md` 记录时间顺序动作，例如：
- source ingested
- page created
- page updated
- synthesis saved
- structural refactor

每条日志应包含：
- timestamp
- action type
- target pages
- short note

## 10. Ingest 工作流

执行 raw 资料 ingest 时：

1. 读取 raw 源资料。
2. 读取 `wiki/index.md`、`wiki/overview.md` 及相关页面上下文。
3. 创建或更新一个来源页。
4. 创建或更新相关实体页。
5. 创建或更新相关概念页。
6. 更新 `wiki/index.md`。
7. 更新 `wiki/overview.md`。
8. 向 `wiki/log.md` 追加记录。

## 11. Query 工作流

回答查询时：

1. 读取 `wiki/index.md`。
2. 选择相关页面。
3. 阅读这些页面。
4. 基于 wiki 证据综合答案。
5. 可选：将结果保存到 `wiki/syntheses/`。
6. 若已保存，更新 `wiki/index.md` 与 `wiki/log.md`。

## 12. Health 工作流

健康检查应验证：
- 必需目录存在
- 必需根页面存在
- 索引条目指向真实页面
- 关键页面非空
- 来源页在日志中可追踪

## 13. Graph 工作流

图谱输出为可选。
可由显式 `[[wikilinks]]` 与推断语义边生成。
仅最终图谱产物写入远端存储。
临时图缓存应保留在本地。
