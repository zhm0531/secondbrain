# SecondBrain 第八阶段：访问范围与记忆编号

每条记忆现在拥有稳定的用户引用编号，例如 `#000001`。UUID 仍作为内部主键，编号用于网页、Agent 和用户交流。

Core 支持按 `global`、`project`、`session` 和 `agent` 判断读取权限。越权读取不会直接返回正文，而会返回 `requires_confirmation: true`，由 Agent 或 Web UI 询问用户是否继续；确认后再带 `confirmed=true` 请求。

检索请求可以提供：

```text
request_agent_id
request_project_id
request_session_id
```

这样 Agent 的读取范围由 Core 判断，而不是只依赖 Skill 提示词。

验证结果：`10 passed`。
