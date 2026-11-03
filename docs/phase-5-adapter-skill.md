# SecondBrain 第五阶段：通用 Agent 适配器 Skill

第五阶段提供了一个平台无关的 `secondbrain` Skill。它不保存第二套记忆，也不依赖某个模型厂商；它只负责把 Agent 的记忆操作转换为 SecondBrain Core 请求。

## Skill 目录

```text
skills/secondbrain/
  SKILL.md
  agents/openai.yaml
  references/protocol.md
  references/memory-policy.md
  scripts/secondbrain_client.py
```

对外显示名是 `SecondBrain`，内部 Skill 名是 `secondbrain`。不同 Agent 可以把自己的触发方式映射到相同的 `@SecondBrain` 操作。

## 连接优先级

1. 本地 HTTP Core：`http://127.0.0.1:8765`
2. `scripts/secondbrain_client.py`
3. `python -m secondbrain_core.cli`
4. 手动导入导出

适配器在没有成功连接 Core 时，不得声称已经读取或保存了记忆。

## 已实现的适配操作

- 加载相关记忆
- 搜索记忆
- 创建候选记忆
- 获取单条记忆
- 确认、拒绝和归档记忆
- 更新记忆内容和元数据
- 健康检查

## 通用性边界

Skill 不假设宿主一定支持 HTTP、命令行或 MCP。它把这些能力作为连接模式，并保留手动 fallback。真正的宿主适配只需要提供：

- 当前 Agent ID
- 当前项目 ID（如果有）
- 当前会话 ID（如果有）
- 一种调用 Core 的方式

## 验证

Skill 已通过 Skill 结构验证，适配器客户端测试也覆盖了候选记忆创建和搜索。
