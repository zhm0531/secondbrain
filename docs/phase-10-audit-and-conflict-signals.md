# SecondBrain 第十阶段：检索冲突提示与记忆审计

检索结果现在包含：

```json
{
  "has_conflicts": true,
  "conflict_count": 1
}
```

网页列表会显示冲突提示。Agent 读取结果时应先说明冲突，再决定是否请求替换。

审计接口：

```text
POST /api/maintenance/audit
```

命令行：

```text
python -m secondbrain_core.cli --root memory audit
```

审计报告包含：

- active 记忆数量
- 互相冲突的记忆对
- 缺少 Agent、项目或会话归属的问题
- 缺少来源信息的潜在污染记录

审计只报告问题，不自动修改记忆。它可以由计划任务定期调用。

测试结果：`12 passed`。
