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
- 正文规范化后完全相同的重复记忆分组及其编号
- 互相冲突的记忆对
- 缺少 Agent、项目或会话归属的问题
- 缺少来源信息的潜在污染记录

审计只报告问题，不自动修改记忆。它可以由计划任务定期调用。

用户指令：

```text
@SecondBrain check all
@SecondBrain check conflicts
@SecondBrain check duplicates
```

网页列表中的“⚠ 可能冲突（N）”可以点击查看每条冲突记忆的编号、正文摘要和词语重叠理由。

测试结果：`12 passed`。
