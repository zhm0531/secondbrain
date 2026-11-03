# SecondBrain 第九阶段：跨 Agent 项目授权

项目访问现在由 `agent_projects` 授权表控制。Agent 只有在被授予项目访问权后，才能读取该项目范围的记忆。

## CLI

```text
python -m secondbrain_core.cli --root memory grant-project-access --agent-id agent_deepseek --project-id project_secondbrain
python -m secondbrain_core.cli --root memory revoke-project-access --agent-id agent_deepseek --project-id project_secondbrain
```

## HTTP

```text
GET    /api/projects/access?project_id=...
POST   /api/projects/access  {"agent_id":"...", "project_id":"..."}
DELETE /api/projects/access?agent_id=...&project_id=...
```

项目记忆读取必须同时提供请求 Agent 和项目上下文；没有授权时返回需要确认的访问结果。

测试结果：`11 passed`。
