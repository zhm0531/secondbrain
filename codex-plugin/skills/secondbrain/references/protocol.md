# SecondBrain 适配协议

本文件定义 Agent 适配器与 SecondBrain Core 之间的最小协议。适配器可以使用 HTTP、命令行或其他工具实现，但数据字段应保持一致。

## 连接信息

默认本地地址：

```text
http://127.0.0.1:8765
```

也可以使用环境变量 `SECONDBRAIN_URL` 或宿主配置覆盖地址。默认服务只监听本机，不需要在请求中发送账号或令牌。

## 读取接口

### 健康检查

```text
GET /health
```

### 搜索记忆

```text
GET /api/memories/search?q=<query>&scope=<scope>&project_id=<id>&agent_id=<id>&include_candidates=<true|false>&limit=<n>
```

默认只返回 `active` 记忆。只有在审核或调试场景才请求候选记忆。

### 获取单条记忆

```text
GET /api/memories/<memory-id>
```

## 写入接口

### 创建会话

```text
POST /api/sessions
Content-Type: application/json
```

请求体示例：

```json
{
  "agent_id": "agent_codex",
  "project_id": "project_secondbrain",
  "title": "设计记忆适配器",
  "summary": "实现跨 Agent 记忆访问。"
}
```

### 创建候选记忆

```text
POST /api/memories
Content-Type: application/json
```

请求体示例：

```json
{
  "content": "用户希望先给出结论，再解释实现细节。",
  "memory_type": "preference",
  "scope": "global",
  "status": "candidate",
  "confidence": 0.8,
  "agent_id": "agent_codex",
  "project_id": null,
  "source_session_id": "session_123",
  "source_reference": "user-message-12",
  "tags": ["writing-style"]
}
```

### 修改记忆

```text
PATCH /api/memories/<memory-id>
Content-Type: application/json
```

允许提交 `content`、`confidence`、`tags`、`expires_at` 和 `source_reference`。

### 生命周期操作

```text
POST /api/memories/<memory-id>/approve
POST /api/memories/<memory-id>/reject
POST /api/memories/<memory-id>/archive
POST /api/memories/<memory-id>/replace

请求体示例：

```json
{
  "content": "新的事实或决策内容",
  "confidence": 0.95,
  "agent_id": "agent_codex",
  "project_id": "project_secondbrain",
  "source_session_id": "session_123"
}
```

该操作会创建一条新的 `active` 记忆，并把旧记忆标记为 `superseded`，保留两条记录及其历史。
```

## 上下文信封

适配器内部可以使用以下对象描述一次调用：

```json
{
  "agent_id": "agent_codex",
  "project_id": "project_secondbrain",
  "session_id": "session_123",
  "query": "当前任务涉及记忆系统的架构设计",
  "scopes": ["session", "project", "global"],
  "limit": 8
}
```

`scopes` 用于限制检索范围。没有项目或会话 ID 时，省略对应字段，不要伪造 ID。

## 命令行映射

当宿主可以运行仓库中的 Python 模块时，可以使用：

```text
python -m secondbrain_core.cli --root <memory-root> search <query>
python -m secondbrain_core.cli --root <memory-root> add-memory --content <text> --memory-type <type> --scope <scope>
python -m secondbrain_core.cli --root <memory-root> approve <memory-id>
python -m secondbrain_core.cli --root <memory-root> reject <memory-id>
python -m secondbrain_core.cli --root <memory-root> rebuild
```

命令行和 HTTP 接口都使用相同的 Core 服务逻辑。

## 错误处理

- `400`：请求字段不完整或值非法；修正请求后重试。
- `404`：记忆或路由不存在；不要把它当作成功。
- `500`：Core 内部错误；保留用户当前任务，提示稍后重试。
- 连接失败：说明 Core 未运行或地址不可达，不要声称已经加载或保存记忆。
