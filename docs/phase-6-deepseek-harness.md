# SecondBrain 第六阶段：DeepSeek Harness 接入

第六阶段提供了一个独立的 DeepSeek Harness bundle：

```text
integrations/deepseek-harness/dsh-secondbrain-bridge/
```

它使用 Harness 内置的 `@deepseek-ai/dsh-mcp-client`，通过 stdio 启动 SecondBrain MCP 服务，再由 MCP 服务访问本地 SecondBrain Core HTTP API。

## 结构

```text
DeepSeek Harness
  └─ dsh-mcp-client
      └─ secondbrain_mcp_server.py
          └─ http://127.0.0.1:8765
              └─ SecondBrain Core
```

Harness 不直接读写 Markdown，也不需要修改 Harness 源码。

## MCP 工具

- `secondbrain_load`
- `secondbrain_search`
- `secondbrain_propose`
- `secondbrain_get`
- `secondbrain_approve`
- `secondbrain_reject`
- `secondbrain_archive`
- `secondbrain_status`

## 配置变量

| 变量 | 默认值 | 作用 |
|---|---|---|
| `SECONDBRAIN_PYTHON` | `python` | 启动 MCP 服务的 Python |
| `SECONDBRAIN_HOME` | 当前工作目录 | MCP 子进程工作目录 |
| `SECONDBRAIN_URL` | `http://127.0.0.1:8765` | SecondBrain Core 地址 |
| `SECONDBRAIN_MCP_SERVER` | `secondbrain` | MCP 工具命名空间 |

工具名称通常显示为 `mcp__secondbrain__secondbrain_load` 等形式，具体前缀由 Harness 的 `serverName` 决定。

## 安装思路

使用 DeepSeek Harness 自带的插件管理器安装 bundle，而不是手动编辑 profile `package.json`：

```text
dsh plugin --profile desktop add <bundle-path>
```

安装后使用工作区提供的 profile 检查脚本验证 BOM、bundle 和依赖，再重启 DeepSeek Harness 让 MCP 行生效。

## 验证结果

- Core、Web UI 和适配器测试继续通过。
- MCP stdio 初始化、工具列表和候选记忆创建已经通过自动化测试。
- bundle 的 `package.json` 已通过 Node JSON 解析检查。
- `dsh-secondbrain-bridge` 已通过 DeepSeek Harness 官方插件管理器安装到 desktop profile。
- profile 检查结果为 `OK (0 warning(s))`。
- 本机 SecondBrain Core 已在 `127.0.0.1:8765` 启动，健康检查返回 200。

安装后需要重启 DeepSeek Harness，desktop profile 才会重新加载新增的 MCP 行。当前运行中的会话不应被强制关闭，以免丢失未保存内容。

