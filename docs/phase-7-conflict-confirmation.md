# 冲突检测、提醒和替换确认

SecondBrain 现在采用以下流程：

1. Agent 提交新记忆。
2. Core 在同一 `scope` 和 `memory_type` 的 active 记忆中检查潜在冲突。
3. 新记忆保持 `candidate`。
4. 响应返回 `conflicts` 和 `requires_confirmation: true`。
5. Agent 向用户展示新旧内容并询问是否替换。
6. 只有用户明确确认后，才调用 `/api/memories/<id>/replace`。

批量审核接口：

```text
GET  /api/reviews/conflicts
POST /api/reviews/resolve-all  {"action":"keep"|"reject"|"replace"}
POST /api/reviews/resolve  {"candidate_id":"...", "action":"keep"|"reject"|"replace", "old_memory_id":"..."}
```

其中 `resolve-all` 支持“全部保留”“全部拒绝”和“全部替换”。“全部替换”会对每条候选选择检测到的第一条冲突旧记忆；“逐条询问”使用 `GET /api/reviews/conflicts` 返回的队列逐条调用 `resolve`。

冲突不会自动替换旧记忆。确认替换后才会创建新的 active 版本，并将旧版本标记为 `superseded`。

测试结果：`9 passed`。
