# SecondBrain 记忆策略

## 记忆范围

| scope | 适用内容 |
|---|---|
| `global` | 稳定的用户偏好、长期有效的工作规则 |
| `project` | 项目背景、架构决策、项目约束 |
| `session` | 当前会话的临时上下文和未完成事项 |
| `agent` | 指定 Agent 的私有工作习惯或笔记 |

## 记忆类型

- `preference`：用户偏好
- `fact`：已确认事实
- `decision`：项目决策
- `instruction`：持续有效的工作规则
- `context`：项目或主题背景
- `open_loop`：尚未解决的问题
- `summary`：会话或阶段摘要

## 生命周期

```text
candidate -> active -> superseded -> archived
         \-> rejected
```

- `candidate`：由用户或 Agent 提出的待审核内容。
- `active`：允许默认检索和注入上下文。
- `superseded`：被新记忆替代，保留来源以便追溯。
- `archived`：保留但不参与默认检索。
- `rejected`：明确拒绝，不参与检索。

## 提取规则

适合保存：

- 用户明确声明的长期偏好。
- 已经确认的项目事实和决策。
- 会影响多个后续会话的工作规则。
- 需要跨 Agent 继续处理的开放问题。

通常不适合保存：

- 一次性闲聊。
- Agent 的内部推理过程。
- 没有来源的猜测。
- 已经完成且不再有复用价值的临时步骤。
- 可能包含敏感信息但没有保存必要的内容。

## 冲突处理

当两条 active 记忆冲突时：

1. 检查 scope 是否相同。
2. 检查来源会话、更新时间和用户确认状态。
3. 不要静默覆盖旧记忆。
4. 创建一条新的候选或确认记忆，并将旧记忆标记为 superseded 或 archived。
5. 在回答中说明存在冲突，必要时请用户决定。

## 注入上下文

注入 Agent 的内容应包含：

- 简短正文
- scope
- status
- confidence
- source_session_id（如果有）
- updated_at

优先级建议：当前 session > 当前 project > global > agent 私有。这个顺序可以根据具体 Agent 的权限模型调整。
