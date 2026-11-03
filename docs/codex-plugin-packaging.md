# SecondBrain Codex Plugin 包

`codex-plugin/` 是 SecondBrain 的 Codex Plugin 发行包，包含：

```text
codex-plugin/
  .codex-plugin/plugin.json
  .mcp.json
  skills/secondbrain/
  mcp/secondbrain_mcp_server.py
```

插件清单声明了 Skill 目录和 MCP 服务。MCP 服务通过 stdio 运行，并连接本机的 SecondBrain Core：

```text
http://127.0.0.1:8765
```

安装插件后，需要先启动 Core：

```text
python -m secondbrain_core.server --root memory --port 8765
```

插件包目前可以作为本地插件源导入 Codex。插件目录中的 Skill 和 MCP 配置都使用相对路径，便于迁移到其他机器。
