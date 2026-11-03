# SecondBrain 第二阶段设计：存储格式与索引结构

> 状态：初稿，可随着实际实现和测试修改。

## 1. 存储原则

SecondBrain 使用两种存储：

- Markdown：人类可读的持久化记录，也是唯一的主数据源。
- SQLite：可重建的索引、筛选和状态查询数据。

所有由 Web UI 或 Agent 发起的修改，都应该先由 SecondBrain Core 写入 Markdown，再更新 SQLite 索引。SQLite 不作为独立的第二套事实来源。

如果 SQLite 损坏，可以扫描 Markdown 重新建立索引。这样可以避免记忆库被某个界面或数据库格式锁定。

## 2. 编码、时间和 ID

- 所有文本文件使用 UTF-8 编码。
- 所有持久化时间使用 UTC 的 ISO 8601 格式，例如 `2026-11-01T13:30:00Z`。
- 图形界面根据用户本地时区显示时间。
- ID 使用带类型前缀的 UUID 字符串：

```text
agent_<uuid>
project_<uuid>
session_<uuid>
memory_<uuid>
event_<uuid>
```

文件路径只使用稳定 ID，不使用标题。标题可以修改，ID 不应因重命名而改变。

## 3. 目录结构

```text
memory/
  sessions/
    <session-id>/
      README.md
      events.md
  memories/
    active/
      <memory-id>.md
    candidates/
      <memory-id>.md
    archived/
      <memory-id>.md
    rejected/
      <memory-id>.md
  system/
    agents.yaml
    projects.yaml
  index.sqlite3
```

### 3.1 为什么移除固定的 `metadata.json`

阶段一的目录草案中包含 `metadata.json`。阶段二改为在 Markdown 文件顶部使用 YAML front matter 保存元数据，避免同一条记录在 `README.md` 和 `metadata.json` 中重复维护。

如果未来某个 Agent 需要保存不能放入人类可读记录的运行时状态，可以额外增加适配器自己的状态文件，但它不属于记忆主数据。

## 4. Markdown 通用格式

每个记录文件由两部分组成：

1. YAML front matter：程序需要的结构化元数据。
2. Markdown 正文：人类可读的内容。

示例：

```markdown
---
record_type: memory
schema_version: 1
memory_id: memory_12345678-1234-4abc-8def-1234567890ab
scope: project
memory_type: decision
status: active
confidence: 0.95
agent_id: agent_12345678-1234-4abc-8def-1234567890ab
project_id: project_12345678-1234-4abc-8def-1234567890ab
source_session_id: session_12345678-1234-4abc-8def-1234567890ab
created_at: 2026-11-01T13:30:00Z
updated_at: 2026-11-01T13:30:00Z
expires_at: null
supersedes_memory_id: null
tags:
  - architecture
  - storage
---

SecondBrain 的 Markdown 文件是记忆的主数据源，SQLite 只保存索引。
```

## 5. 会话文件格式

路径：

```text
memory/sessions/<session-id>/README.md
```

示例结构：

```markdown
---
record_type: session
schema_version: 1
session_id: session_12345678-1234-4abc-8def-1234567890ab
agent_id: agent_12345678-1234-4abc-8def-1234567890ab
project_id: project_12345678-1234-4abc-8def-1234567890ab
title: 设计 SecondBrain 的记忆架构
status: active
created_at: 2026-11-01T13:00:00Z
updated_at: 2026-11-01T13:30:00Z
archived_at: null
tags:
  - design
  - memory
---

# 会话目标

定义跨 Agent 记忆系统的基础架构。

# 当前摘要

采用本地 Web 应用、Markdown、SQLite 和 Agent 适配器的组合。

# 已确认决策

- Markdown 是主数据源。
- SQLite 是可重建索引。
- 候选记忆需要审核后才能成为长期记忆。

# 未解决问题

- 是否保存完整聊天原文。
- 是否加入向量检索。

# 相关记忆

- `memory_...`

# 相关会话

- `session_...`
```

会话正文允许人工编辑，但 front matter 中的 ID、类型和状态应由 Core 维护。

## 6. 记忆文件格式

路径由状态决定：

```text
memory/memories/active/<memory-id>.md
memory/memories/candidates/<memory-id>.md
memory/memories/archived/<memory-id>.md
memory/memories/rejected/<memory-id>.md
```

示例：

```markdown
---
record_type: memory
schema_version: 1
memory_id: memory_12345678-1234-4abc-8def-1234567890ab
scope: global
memory_type: preference
status: candidate
confidence: 0.8
agent_id: agent_12345678-1234-4abc-8def-1234567890ab
project_id: null
source_session_id: session_12345678-1234-4abc-8def-1234567890ab
source_reference: user-message-12
created_at: 2026-11-01T13:30:00Z
updated_at: 2026-11-01T13:30:00Z
expires_at: null
supersedes_memory_id: null
tags:
  - writing-style
---

用户偏好先给出结论，再解释实现细节。

## 证据

用户在多个会话中表达过类似要求，但尚未在管理界面确认。

## 审核记录

- 2026-11-01：由 Agent 提交为候选。
```

### 6.1 内容和元数据的边界

- 稳定字段放在 front matter 中。
- 记忆正文放在 Markdown 正文中。
- 证据、解释和人工审核记录放在正文中。
- 不把长篇原始对话嵌入长期记忆正文；使用来源引用或单独的原文存档。

## 7. 事件日志格式

路径：

```text
memory/sessions/<session-id>/events.md
```

事件日志采用追加方式保存，不覆盖旧事件。

示例：

```markdown
# Events

## 2026-11-01T13:30:00Z · decision

- actor: user
- agent_id: agent_...
- summary: 确定采用本地 Web 应用和统一适配器。
- related_memory_ids:
  - memory_...

## 2026-11-01T13:35:00Z · memory-proposed

- actor: agent
- memory_id: memory_...
- summary: 提交一条用户写作偏好作为候选记忆。
```

事件日志用于追溯，不作为默认上下文直接注入 Agent。

## 8. SQLite 索引草案

SQLite 表只保存搜索和管理所需的数据，并保留原始文件路径。

### 8.1 `agents`

| 字段 | 说明 |
|---|---|
| `agent_id` | 主键 |
| `display_name` | 显示名称 |
| `adapter_type` | 适配器类型 |
| `settings_json` | 适配器配置 |
| `created_at` | 创建时间 |
| `last_seen_at` | 最近使用时间 |

### 8.2 `projects`

| 字段 | 说明 |
|---|---|
| `project_id` | 主键 |
| `name` | 项目名称 |
| `description` | 项目描述 |
| `root_path` | 项目目录，可为空 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### 8.3 `sessions`

| 字段 | 说明 |
|---|---|
| `session_id` | 主键 |
| `agent_id` | 所属 Agent |
| `project_id` | 所属项目，可为空 |
| `title` | 标题 |
| `summary` | 摘要 |
| `status` | 会话状态 |
| `file_path` | README 相对路径 |
| `content_hash` | 用于检测文件变化 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |
| `indexed_at` | 最近索引时间 |

### 8.4 `memories`

| 字段 | 说明 |
|---|---|
| `memory_id` | 主键 |
| `scope` | global、project、session 或 agent |
| `memory_type` | preference、fact、decision 等 |
| `status` | candidate、active、archived 等 |
| `content` | 纯文本检索内容 |
| `confidence` | 0 到 1 |
| `agent_id` | 来源或私有 Agent，可为空 |
| `project_id` | 所属项目，可为空 |
| `source_session_id` | 来源会话，可为空 |
| `source_reference` | 来源消息或外部引用 |
| `file_path` | Markdown 相对路径 |
| `content_hash` | 用于检测文件变化 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |
| `expires_at` | 过期时间，可为空 |
| `supersedes_memory_id` | 被替代的记忆，可为空 |
| `indexed_at` | 最近索引时间 |

### 8.5 `memory_tags`

| 字段 | 说明 |
|---|---|
| `memory_id` | 记忆 ID |
| `tag` | 标签文本 |

主键为 `(memory_id, tag)`。

### 8.6 `events`

| 字段 | 说明 |
|---|---|
| `event_id` | 主键 |
| `session_id` | 所属会话 |
| `event_type` | 事件类型 |
| `actor_type` | user、agent 或 system |
| `summary` | 事件摘要 |
| `file_path` | 事件所在 events.md |
| `created_at` | 事件时间 |

事件正文仍然以 Markdown 为准，SQLite 只保存用于时间线和筛选的摘要。

## 9. 索引规则

- 首次启动时扫描所有 Markdown 文件并建立 SQLite 索引。
- 文件修改后，通过 `content_hash` 判断是否需要重新解析。
- 文件被移动到其他状态目录时，更新 `status` 和 `file_path`。
- SQLite 中没有对应 Markdown 文件的记录，标记为失效并进入重建报告。
- Markdown 文件格式错误时，不覆盖原文件；记录解析错误并在界面中显示。
- Web UI 不直接写 SQLite，所有修改都经过 Core。

## 10. 第二阶段验收标准

完成本阶段后，应该能够：

1. 根据文件路径找到任意会话和记忆。
2. 仅通过 Markdown 读懂一条记录。
3. 从 Markdown 重建 SQLite 索引。
4. 通过状态目录区分候选、有效、归档和拒绝记忆。
5. 从一条记忆追溯到来源会话和来源 Agent。
6. 允许标题变化而不改变记录 ID。
7. 让 Web UI 和 Agent 适配器共享同一套数据格式。

