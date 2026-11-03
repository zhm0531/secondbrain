# 更新日志

## [未发布] 2026-11-03：记忆审查与冲突可视化

本次更新面向 Codex 和 DeepSeek Harness 增加了记忆质量审查能力，重点解决“只能看到冲突数量、无法继续定位”和“没有统一的全库审查指令”两个问题。

### 用户可调用指令

新增以下 `@SecondBrain` 指令：

```text
@SecondBrain check all
@SecondBrain check conflicts
@SecondBrain check duplicates
```

也接受自然变体，例如 `check conflict`、`check repetition` 和 `check repetitions`。它们分别对应全量审查、潜在冲突审查和完全重复审查。

### 审查结果

- `check all` 返回生效记忆数量、完全重复分组、潜在冲突记忆对和来源污染记录。
- `check conflicts` 返回冲突双方的记忆编号、记忆 ID、词语重叠比例和简短理由。
- `check duplicates` 按正文规范化后的完全相同内容分组，并列出每组记忆编号。
- 重复检查默认针对 `active` 记忆；候选记忆仍可通过原有的单条重复查询工具检查。
- 冲突检测继续使用现有启发式规则：同一生效范围和记忆类型内，正文词语重叠达到阈值且内容并非完全相同，就标记为潜在冲突。审查只报告问题，不自动修改、替换或删除记忆。

### 网页端

- 记忆列表中的“⚠ 可能冲突（N）”现在是可点击控件。
- 点击后弹出逐条冲突详情，显示对方记忆编号、正文摘要和“同一生效范围/类型、词语重叠比例”等简短理由。
- 弹窗提供“查看记忆”按钮，可直接打开对应记忆；支持关闭按钮、点击遮罩关闭和 `Esc` 关闭。

### 适配层与文档

- 新增 MCP 工具 `secondbrain_check`，参数 `check` 支持 `all`、`conflicts`、`duplicates`。
- MCP 帮助信息和 SecondBrain skill 已同步新增审查指令。
- Codex Plugin 与 DeepSeek Harness 的 MCP 副本均由 `tools/sync_adapters.py` 从共享源码生成并保持一致。
- 更新了审计协议、冲突审查设计文档和使用说明。

### 验证

- `python tools/sync_adapters.py --check`：`adapters in sync`
- `python -m pytest -q`：`17 passed`
- `node --check secondbrain_core/web/app.js`：通过
- 在线 Core 验证：13 条 active 记忆、0 组完全重复、2 对潜在冲突
