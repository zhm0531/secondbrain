# SecondBrain 第三阶段：Core 服务

第三阶段已经有一个可运行的最小核心服务。它先提供稳定的文件读写、索引和接口，图形界面与 Agent 适配器将在后续阶段接入。

## 已实现能力

- 创建 Agent 和项目
- 创建会话并生成 Markdown 文件
- 创建候选、有效、归档或拒绝记忆
- 按文本搜索记忆
- 按范围、项目、Agent 和状态筛选
- 审核候选记忆
- 拒绝或归档记忆
- 更新记忆正文和部分元数据
- 从 Markdown 重建 SQLite 索引
- 原子写入 Markdown 文件，降低写入中断造成的损坏风险

## 命令行入口

当前可以从项目根目录运行：

```text
python -m secondbrain_core.cli --root memory create-agent --display-name "Codex"
python -m secondbrain_core.cli --root memory create-project --name "SecondBrain"
python -m secondbrain_core.cli --root memory search "Markdown"
python -m secondbrain_core.cli --root memory rebuild
```

记忆默认以 `candidate` 状态创建。搜索默认只返回 `active` 记忆；需要包含候选时使用 `--include-candidates`。

## 本地 HTTP 接口

启动：

```text
python -m secondbrain_core.server --root memory --port 8765
```

当前接口：

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/health` | 检查服务是否运行 |
| `GET` | `/api/memories/search?q=...` | 搜索有效记忆 |
| `GET` | `/api/memories/<id>` | 获取单条记忆 |
| `POST` | `/api/sessions` | 创建会话 |
| `POST` | `/api/memories` | 创建记忆 |
| `POST` | `/api/memories/<id>/approve` | 确认候选记忆 |
| `POST` | `/api/memories/<id>/reject` | 拒绝候选记忆 |
| `POST` | `/api/memories/<id>/archive` | 归档记忆 |
| `PATCH` | `/api/memories/<id>` | 更新记忆 |
| `POST` | `/api/index/rebuild` | 重建 SQLite 索引 |

## 当前限制

- 搜索使用 SQLite `LIKE`，还没有全文检索和向量检索。
- Core 还没有用户认证，服务默认只监听本机地址。
- 会话事件目前写入 Markdown，事件索引还没有完整重建逻辑。
- Web UI 和 Agent 适配器尚未实现。
- SQLite 表结构已经具备外键约束，但数据校验仍会继续加强。

## 阶段验收

第三阶段以以下结果作为完成标准：

1. Core 可以在全新目录中创建记录。
2. Markdown 文件可以被人直接阅读。
3. SQLite 可以从 Markdown 重建。
4. 候选记忆可以被确认、拒绝和归档。
5. 命令行和 HTTP 接口使用同一套服务逻辑。
6. 自动化测试覆盖创建、搜索、状态转换和索引重建。

