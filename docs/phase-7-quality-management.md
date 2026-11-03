# SecondBrain 第七阶段：记忆质量管理

第七阶段加入了记忆生命周期的质量控制能力：

- `expires_at` 到期的 active 记忆不会继续出现在默认搜索结果中。
- 可以检测规范化文本完全相同的重复记忆。
- 可以根据同一范围内的词语重叠发现潜在冲突，供用户审核。
- 每次创建、更新、确认、拒绝和归档都会写入 `memory_history`。
- 维护接口可以批量归档已经过期的记忆。

## Core 接口

```text
GET  /api/memories/duplicates?content=...
GET  /api/memories/conflicts?content=...&scope=project
GET  /api/memories/<id>/history
POST /api/maintenance/expire
```

重复检测采用规范化后的精确文本匹配；冲突检测是启发式提示，不会自动覆盖或删除任何记录。过期处理使用归档状态，保留原文件和历史。

## MCP 工具

DeepSeek Harness bundle 增加：

- `secondbrain_find_duplicates`
- `secondbrain_find_conflicts`

## 验证

质量管理测试覆盖了重复检测、潜在冲突检测、到期归档、默认搜索排除和历史记录，共同测试结果为 `6 passed`。
