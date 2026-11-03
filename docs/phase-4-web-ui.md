# SecondBrain 第四阶段：本地 Web 界面

第四阶段把 Core 的 HTTP 接口连接到一个本地管理界面。界面由同一个 Python 服务提供，不需要额外的前端构建工具。

## 启动

最简单的方式是使用一条命令自动启动 Core 并打开浏览器：

```text
python -m secondbrain_core.cli --root memory open
```

如果 Core 已经运行，这条命令只会打开界面；如果没有运行，它会在后台启动 Core。

```text
python -m secondbrain_core.server --root memory --port 8765
```

然后在浏览器打开：

```text
http://127.0.0.1:8765/
```

## 当前功能

- 搜索有效记忆
- 可选显示候选记忆
- 按范围、Agent 和项目筛选
- 查看记忆详细内容、来源和可信度
- 编辑记忆正文
- 确认、拒绝和归档候选或有效记忆
- 从界面创建候选记忆
- 显示当前 Agent 和项目列表

## 设计边界

- 页面只通过 Core HTTP API 读写数据。
- 页面不直接打开 Markdown，也不直接修改 SQLite。
- 用户内容使用 DOM 文本节点渲染，避免把记忆内容当作 HTML 执行。
- 服务默认监听 `127.0.0.1`，只在本机开放。
- 第一版使用普通文本搜索，暂时没有向量检索和复杂关系图。

## 验收结果

测试覆盖了：

1. 根页面能够返回 Web 界面。
2. `/health` 能报告服务状态。
3. HTTP 创建记忆后可以搜索到它。
4. Agent 列表能够通过 API 返回。
5. Core 原有的创建、审核和索引重建测试继续通过。

