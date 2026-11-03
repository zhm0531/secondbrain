# SecondBrain 第十一阶段：名称同步与 MCP UTF-8

DeepSeek Harness 的 MCP stdio 服务现在显式把 stdin、stdout、stderr 固定为 UTF-8，避免 Windows GBK locale 导致中文查询乱码、emoji 编码失败或请求超时。

项目和会话名称现在通过 Core 的真实记录维护：

```text
PATCH /api/projects/<project-id>  {"name":"新项目名"}
PATCH /api/sessions/<session-id>  {"title":"新会话名", "summary":"..."}
```

更新后会同步 Markdown、SQLite 索引和 Web UI 显示。索引重建时会保留已有项目名称，不再用 `project_id` 覆盖显示名称。

测试结果：`12 passed`。
