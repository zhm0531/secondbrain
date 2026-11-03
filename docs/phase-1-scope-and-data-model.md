# SecondBrain 第一阶段设计：范围、调用方式与数据模型

> 状态：初稿，可随着实际使用修改。

## 1. 产品与命名

- 对外名称：`SecondBrain`
- 内部 Skill 标识：`secondbrain`
- 用户可读调用前缀：`@SecondBrain`
- 记忆核心服务名称：`SecondBrain Core`

Skill 目录使用小写名称，是为了兼容常见的开源 Skill 命名规则；用户界面、文档和命令帮助中使用 `SecondBrain`。

`@SecondBrain` 是跨 Agent 的统一调用约定。具体平台如果不支持这种 mention 语法，可以由适配器把它映射到平台自己的 Skill、工具或命令调用方式。

## 2. 第一版范围

第一版采用以下默认边界：

- 单用户
- 本机优先
- 多 Agent 共用一套记忆库
- Markdown 作为人类可读的持久化格式
- SQLite 作为索引和状态查询的数据源
- 本地 Web 界面
- 先支持显式调用，再逐步增加自动建议
- 不默认保存完整聊天原文
- 不默认上传到云端
- 不在第一版实现多用户权限、跨设备同步和复杂向量检索

完整聊天原文可以由用户另行保存。SecondBrain 默认保存会话摘要、重要事件、已确认记忆和待审核候选，避免把所有对话噪音都变成长期记忆。

## 3. 调用方式

### 3.1 统一调用语法

```text
@SecondBrain
@SecondBrain load
@SecondBrain load project:project-id
@SecondBrain search <query>
@SecondBrain propose
@SecondBrain review
@SecondBrain approve <memory-id>
@SecondBrain reject <memory-id>
@SecondBrain status
@SecondBrain help
```

### 3.2 默认行为

- 单独输入 `@SecondBrain`：根据当前会话的 Agent、项目和用户问题，加载相关记忆。
- `load`：读取记忆，不修改记忆库。
- `search`：搜索并返回匹配内容，不修改记忆库。
- `propose`：从当前会话提取候选记忆，写入候选区，不直接成为长期记忆。
- `review`：查看待审核候选。
- `approve`：将候选记忆转为已生效记忆。
- `reject`：拒绝候选记忆，并保留拒绝记录。
- `status`：显示当前 Agent、项目、会话和记忆库状态。

### 3.3 自动行为

第一版默认不自动把每轮对话写入长期记忆。适配器可以在以下时机提出候选：

- 用户明确要求保存
- 会话中出现明确决策
- 一个任务阶段完成
- 会话结束

自动提取只产生候选，是否进入长期记忆由规则或用户确认决定。

## 4. 组件边界

SecondBrain 分成三层：

### 4.1 SecondBrain Core

负责：

- 创建和更新会话
- 保存 Markdown 文件
- 更新 SQLite 索引
- 搜索和筛选记忆
- 管理候选、确认、归档和废弃状态
- 返回适合注入 Agent 上下文的记忆片段

### 4.2 Web UI

负责：

- 查看 Agent、项目、会话和记忆
- 搜索和筛选
- 审核候选记忆
- 编辑、归档和恢复
- 查看来源和修改历史

Web UI 不直接实现自己的记忆规则，所有修改通过 Core 完成。

### 4.3 Agent Adapter / Skill

负责：

- 识别当前 Agent、项目和会话
- 把 Agent 的调用转成 Core 请求
- 把搜索结果整理成 Agent 能理解的上下文
- 把 Agent 产生的记忆建议提交到候选区

适配器不保存自己的第二套记忆库，也不把某个 Agent 的特殊行为写成全局规则。

## 5. 核心对象

### 5.1 Agent

表示一个记忆使用者，例如 Codex、DeepSeek harness 或其他 Agent。

建议字段：

- `agent_id`
- `display_name`
- `adapter_type`
- `created_at`
- `last_seen_at`
- `settings`

### 5.2 Project

表示一个长期工作的项目或主题。

建议字段：

- `project_id`
- `name`
- `description`
- `root_path`
- `created_at`
- `updated_at`

### 5.3 Session

表示一次 Agent 会话。

建议字段：

- `session_id`
- `agent_id`
- `project_id`
- `title`
- `summary`
- `status`
- `created_at`
- `updated_at`
- `archived_at`

会话的 Markdown 文件用于人类阅读；SQLite 保存索引和状态。

### 5.4 Memory

表示可以被跨会话引用的信息。

建议字段：

- `memory_id`
- `content`
- `memory_type`
- `scope`
- `status`
- `confidence`
- `agent_id`
- `project_id`
- `source_session_id`
- `source_reference`
- `tags`
- `created_at`
- `updated_at`
- `expires_at`
- `supersedes_memory_id`

### 5.5 Memory 类型

第一版先支持以下类型：

- `preference`：用户偏好
- `fact`：已经确认的事实
- `decision`：项目决策
- `instruction`：持续有效的工作规则
- `context`：项目或主题背景
- `open_loop`：尚未解决的问题
- `summary`：会话或阶段摘要

## 6. 记忆范围

每条记忆必须有范围：

| 范围 | 含义 | 默认可见对象 |
|---|---|---|
| `global` | 用户级长期记忆 | 所有允许访问的 Agent |
| `project` | 项目级记忆 | 同一项目的 Agent |
| `session` | 当前会话记忆 | 当前会话 |
| `agent` | Agent 私有记忆 | 指定 Agent |
| `candidate` | 待审核内容 | 管理界面和产生它的 Agent |

查询时优先返回当前会话、当前项目和全局记忆；Agent 私有记忆只有匹配 Agent 才能读取。

## 7. 记忆生命周期

```text
candidate -> active -> superseded -> archived
         \-> rejected
```

- `candidate`：模型或用户提出，但尚未确认。
- `active`：当前有效，可以被检索和注入上下文。
- `superseded`：已经被新记忆替代，保留来源以便追溯。
- `archived`：不参与默认检索，但仍然保存。
- `rejected`：明确拒绝，不参与检索。

第一版不直接物理删除重要记忆，优先使用归档和拒绝状态，方便恢复和排查错误。

## 8. 文件组织草案

```text
memory/
  sessions/
    <session-id>/
      README.md
      metadata.json
      events.md
  long-term/
    <memory-id>.md
  candidates/
    <memory-id>.md
  archive/
  index.sqlite3
```

Markdown 是可读的持久化记录；SQLite 是可重建的索引。任何关键内容都应该能够从 Markdown 重新建立索引。

## 9. 第一阶段验收标准

完成第一阶段后，应该能够明确回答：

1. `@SecondBrain` 在不同 Agent 中如何映射。
2. 哪些内容属于会话记忆、项目记忆和全局记忆。
3. Agent 何时只能提出候选，何时可以写入已生效记忆。
4. 一条记忆如何追溯到来源会话。
5. 多个 Agent 如何共享项目记忆，同时保留 Agent 私有记忆。
6. Markdown 和 SQLite 各自负责什么。

## 10. 当前保留的可调整项

- 是否在后续版本保存完整聊天原文。
- 是否加入向量检索。
- 是否支持多设备同步。
- 是否为本地数据增加加密。
- 是否允许某些低风险记忆自动确认。
- 是否把 `@SecondBrain` 设计成严格命令，还是同时接受自然语言触发。

