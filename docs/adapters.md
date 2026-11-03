# 适配层约定

SecondBrain 只维护一套 Core 与一套 MCP server。每个 Agent 集成目录（`codex-plugin/`、
`integrations/deepseek-harness/dsh-secondbrain-bridge/`）**只放该平台要求的清单与进程启动方式**，
不放任何业务实现。

## 唯一来源

| 内容 | 唯一来源 | 生成到 |
| --- | --- | --- |
| Core 服务 / 存储 / 索引 / CLI / Web UI | `secondbrain_core/` | —（两个适配层都通过 HTTP 使用，不复制） |
| MCP stdio server | `integrations/shared/secondbrain_mcp_server.py` | `codex-plugin/mcp/`、`dsh-secondbrain-bridge/scripts/` |
| Skill（SKILL.md、references、client 脚本） | `skills/secondbrain/` | `codex-plugin/skills/secondbrain/` |

适配层真正独有的只有：

- Codex：`.codex-plugin/plugin.json`、`.mcp.json`、`mcp.json`、`.agents/plugins/marketplace.json`
- DeepSeek Harness：`package.json`、`cordis.patch.yml`、`index.js`（bundle 加载器）

## 为什么是复制而不是 import

两个发行渠道都只安装适配目录本身（Codex 会缓存整个 plugin 目录，DSH 从 bundle 目录加载），
跨目录 import 会让安装后的包找不到 Core。因此共享文件以**复制**形式进入适配层，但复制是生成的：

```bash
python tools/sync_adapters.py           # 重新生成
python tools/sync_adapters.py --check   # 校验（CI 用，漂移时退出码 1）
python -m pytest -q tests/test_adapter_sync.py
```

`tests/test_adapter_sync.py` 是漂移守卫：直接手改适配层副本会让测试失败。

## 新增一个 Agent

1. 建目录 `integrations/<agent>/<bundle-name>/`；
2. 只写该平台需要的清单与启动器，MCP server 用 `python <bundle>/scripts/secondbrain_mcp_server.py`
   这样的相对路径启动；
3. 把目标路径加进 `tools/sync_adapters.py` 的 `MCP_TARGETS`；
4. 跑一次同步与测试，确保没有把 Core 代码复制进适配层（`test_adapters_only_add_transport_glue`）。
