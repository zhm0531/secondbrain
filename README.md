# SecondBrain

[![ci](https://github.com/zhm0531/secondbrain/actions/workflows/ci.yml/badge.svg)](https://github.com/zhm0531/secondbrain/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)

Local-first cross-agent memory: Markdown on disk, SQLite index, one HTTP core, and thin MCP
adapters for Codex and DeepSeek Harness.

SecondBrain 是一个本地优先的跨 Agent 记忆库：记忆以 Markdown 文件为准（可读、可 diff、可版本管理），
SQLite 只做索引与检索；所有 Agent 通过同一个本地 Core 服务（HTTP）读写，因此 Codex、DeepSeek Harness
看到的是同一份记忆。

## 架构

```text
                    ┌─────────────────────────────┐
                    │  secondbrain_core/          │  ← 唯一实现：存储 / 索引 / 服务 / Web UI
                    │  (storage, database,        │
                    │   service, server, cli, web)│
                    └──────────────┬──────────────┘
                                   │ HTTP 127.0.0.1:8765
              ┌────────────────────┴────────────────────┐
              │  integrations/shared/mcp_server.py      │  ← 唯一实现：MCP stdio 服务
              └───────┬─────────────────────────┬───────┘
                      │ 生成副本                 │ 生成副本
        ┌─────────────▼──────────┐   ┌──────────▼─────────────────────┐
        │ codex-plugin/          │   │ integrations/deepseek-harness/ │
        │  只有适配层清单与技能  │   │  只有 bundle 清单与加载器      │
        └────────────────────────┘   └────────────────────────────────┘
```

**规则：两个适配目录里不放任何业务实现。** Core、MCP server、skill 文档、参考协议都只有一份
（`secondbrain_core/`、`integrations/shared/`、`skills/`），适配层只提供各平台要求的清单文件和
进程启动方式。

## 目录

```text
secondbrain_core/                 Core 服务、存储、索引、CLI、Web UI
  web/                            单页前端（index.html / app.js / styles.css）
integrations/
  shared/                         共享源码（唯一来源）
    secondbrain_mcp_server.py     MCP stdio server
  deepseek-harness/
    dsh-secondbrain-bridge/       DSH bundle：package.json + index.js + cordis.patch.yml
      scripts/                    ← 由 tools/sync_adapters.py 生成
  codex-plugin/                   (见下) Codex 发行包
codex-plugin/                     Codex Plugin：.codex-plugin/plugin.json + .mcp.json + skills/
  mcp/                            ← 由 tools/sync_adapters.py 生成
  skills/secondbrain/             ← 由 tools/sync_adapters.py 生成
skills/secondbrain/               Skill 唯一来源（SKILL.md / references / scripts）
tools/sync_adapters.py            把共享源码同步进两个适配目录，--check 供 CI 使用
tests/                            单元测试（含适配层漂移检查）
docs/                             分阶段设计与打包文档
memory/                           运行时数据根（默认，已被 .gitignore 忽略）
```

## 快速开始

要求 Python 3.11+（仅标准库 + `PyYAML`）。

```bash
pip install -r requirements.txt

# 启动 Core 并打开 Web UI（自动在后台拉起服务）
python -m secondbrain_core.cli --root memory open

# 只启动服务（供 Agent / 适配层使用）
python -m secondbrain_core.server --root memory --host 127.0.0.1 --port 8765
```

打开 <http://127.0.0.1:8765/> 即为记忆管理界面：左侧筛选与新建候选记忆，中间列表，右侧详情与审核。

### 接入 Codex

`codex-plugin/` 是可安装的 Codex Plugin（`.codex-plugin/plugin.json` + `.mcp.json` + skill）。
安装后用 MCP 工具与 `@secondbrain` 指令访问同一 Core。

### 接入 DeepSeek Harness

`integrations/deepseek-harness/dsh-secondbrain-bridge/` 是一个 DSH bundle，用 Harness 内置的
`@deepseek-ai/dsh-mcp-client` 以 stdio 启动 MCP 服务：

```bash
dsh plugin install <path-to>/integrations/deepseek-harness/dsh-secondbrain-bridge
```

### 配置

| 环境变量 | 说明 | 默认 |
| --- | --- | --- |
| `SECONDBRAIN_URL` | Core 地址 | `http://127.0.0.1:8765` |
| `SECONDBRAIN_PROJECT` | 项目根目录 | 适配层所在仓库根 |
| `SECONDBRAIN_ROOT` | 数据根（相对项目） | `memory` |
| `SECONDBRAIN_AUTOSTART` | Core 未启动时是否自动拉起 | `true` |
| `SECONDBRAIN_PYTHON` | 调用 Core 的解释器 | `python` |

## 开发

```bash
python -m pytest -q                     # 全部测试
python tools/sync_adapters.py           # 修改 shared/ 或 skills/ 后同步到适配层
python tools/sync_adapters.py --check   # 校验适配层是否漂移（CI 用）
```

修改顺序固定为：**先改 `secondbrain_core/` 或 `integrations/shared/` / `skills/`，再跑同步脚本。**
直接改 `codex-plugin/mcp/` 或 `dsh-secondbrain-bridge/scripts/` 的副本会被 `tests/test_adapter_sync.py`
判为漂移并失败。

## 文档

- `docs/phase-1..11-*.md`：数据模型、存储格式、Core 服务、Web UI、适配层、冲突与质量、访问编号等设计记录
- `docs/codex-plugin-packaging.md`：Codex Plugin 打包说明

## 许可证

MIT，见 [LICENSE](LICENSE)。
