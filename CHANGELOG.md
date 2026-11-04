# 更新日志

## [未发布] 2026-11-04：解除关联后的过期上下文提示（方案 B）

- `unlink` 现在把调用方 `--session` 记进 `memory_history.after_json`，读取时（`load`/`search`/`get`）按会话派生 `unlink_notice`：只有执行过 unlink 的那个会话会看到「本次会话已解除关联，内容可能过时」。
- 不做任何持久化标记：同一会话重新 `link` 后提示自动消失；不带 `--session` 的 unlink 不产生提示；记忆条数与 `check` 的污染统计都不受影响。
- 契约（`skills/secondbrain/SKILL.md`）新增提示行的固定文案与「提示无法清除已读入上下文」的边界说明。

## [未发布] 2026-11-03：手动增删与关联命令

- 新增 `@SecondBrain add <内容>`：直接写入一条生效记忆，支持 `--scope` / `--target` / `--type` / `--force`。写入前自动扫描同范围的生效记忆，命中重复或冲突时只返回警告、不落盘，`--force` 才强制写入。
- 新增 `@SecondBrain delete <编号>`：物理删除 Markdown 记录并重建索引；不带 `--confirm` 时只返回确认询问，不执行删除。
- 新增 `@SecondBrain link <编号> --scope=<范围> --target=<id>`：把记忆加入会话/项目/Agent 的生效范围，写入 front-matter 的 `links` 与索引表 `memory_links`，不复制正文。
- 新增 `@SecondBrain unlink <编号> --scope=<范围> --target=<id>`：解除关联；若目标是记忆自身的存储范围则拒绝（改存储范围请用 `replace`）。
- 关联语义：全局记忆对所有范围可见，无需关联；会话已通过项目归属看到某条记忆时拒绝关联（`already-visible`）；跨项目会话关联项目记忆报 `scope-mismatch`；目标不存在报 `target-not-found`。
- Core 新增 `POST /api/memories/add`、`POST /api/memories/{id}/link`、`POST /api/memories/{id}/unlink`、`DELETE /api/memories/{id}`；业务错误统一携带 `code`，MCP 层据此输出规范化的四行提示。
- 新增 `memory_links` 索引表与 `search_memories(include_linked=True)`：关联后的记忆在会话/项目/Agent 视图里也能被检索到。
- `search` / `load` 支持 `session_id`（MCP 参数与 `--session=`），Core 搜索路由开启 `include_linked`，`can_access_memory` 先检查记忆的 `links`。修掉“关联写进去了但检索不到”的缺口：会话关联的记忆现在对该会话立即可见，解除后立即不可见。
- `link` / `unlink` 写完 Markdown 与索引后会回读校验（`_verify_links`）：索引漂移则自动 `rebuild_index()` 自愈，仍不一致才报 `internal-error`，避免出现「界面说解除、实际仍可见」的残留。
## [未发布] 2026-11-03：参数校验与规范化报错

- MCP 桥接新增统一参数校验（命令、必填项、取值范围、记忆编号格式），非法调用不再抛裸异常。
- 非法调用返回 linux 风格三行消息：`secondbrain: <原因>` / `用法: ...` / `尝试 '@SecondBrain help' 获取完整用法。`
- `@SecondBrain help` 输出全部命令、选项与用法；`load/search` 支持 `--scope` / `--limit` / `--all`，编号支持 `#000014` 或 UUID。
- `find_conflicts` 在未指定 scope 时改为扫描全部生效范围，修正 `@SecondBrain conflicts <内容>` 永远为空的问题。
- `review` 用 `limit=100` 拉候选记忆，避免候选被大量 active 记忆挤出默认窗口后显示“候选 0 条”。
- `duplicates <内容>` 结果补 `kind`/`similarity`，渲染层可统一显示“(100%)”。
- Core 的 HTTP 请求串行化（`server.py` 加 `_REQUEST_LOCK`）：SQLite 连接以 `check_same_thread=False` 共享，并发进入会偶发 `bad parameter or other API misuse` / `tuple index out of range`。
- 修复 `next_memory_number()` 用 `ORDER BY rowid DESC` 在 `rebuild_index()` 后重号的问题，改为按编号数值取最大值 +1。
- 冲突理由里的类型/范围改为中文（`事实类型`、`（全局）`）。
- 修复历史重号：老库走 `ALTER TABLE` 迁移时 `memory_number` 没有 UNIQUE 约束，`rebuild_index()` 会因重号抛 `UNIQUE constraint failed` 并**静默丢记忆**。
  - `rebuild_index()` 现在重建前先按 `created_at` 保留最早一条、其余顺延重编号（`repaired_numbers` 计入报告），任何重建都不会再丢数据。
  - 新增 `repair_memory_numbers()`、`POST /api/maintenance/repair-numbers`、CLI `repair-numbers`，修复后补建唯一索引 `idx_memories_number_unique`。
  - `audit_memories()` 返回 `duplicate_numbers`，`check all` 能直接看到重号分组。
  - 已对真实库执行：`#000004` 的两条重复分别改为 `#000014` / `#000015`，15 条记忆编号全唯一。
## [未发布] 2026-11-03：冲突判定算法与卡片布局

### 判定算法

- 冲突/重复判定改为只比较正文：先剥离 `## 审核记录` 审计尾注，再做 casefold、去标点、字符 3-gram（对中文无需分词）。
- 相似度同时计算 Dice 与 containment：完全一致或 Dice ≥ 0.8 或（Dice ≥ 0.6 且 containment ≥ 0.9）判为“重复”；Dice ≥ 0.4 判为“冲突”。
- `find_conflicts` 结果新增 `kind`（duplicate/conflict）与 `similarity` 字段，`overlap` 保留为同值兼容；理由文案区分“可能重复”与“可能互相矛盾”。
- `audit_memories` 的 conflicts 只收真正的冲突，近似重复统一进 duplicates；`find_duplicate_groups` 支持扩写类近似重复（并查集分组）。
- 修复旧算法把审计尾注、短文本基数和标点切词当成相似度的三重误报：示例库 13 条记忆中 2 对误报降为 0，真实冲突仍可命中。

### 网页端

- 记忆卡片标题行改为：左上角生效状态徽章、右侧 #编号，下方保留正文摘要（摘要会剥掉 `## 审核记录` 尾注，不把审计信息当正文展示）。
- 冲突弹窗每条警告前显示类型标签：`重复`（蓝）或 `冲突`（橙）。
- `@SecondBrain` 指令回复改为固定模板（`SKILL.md` 新增 Command reply contract）：一句结果 + 最多 5 行明细，≤8 行/120 字，禁止解释、复述与客套；失败与需确认两种例外单独定义。

### 验证

- `python -m pytest -q` → 21 passed（新增 `tests/test_similarity.py`：无关记忆不误报、扩写判重复、kind/similarity/reason、审计尾注剥离）。

## [未发布] 2026-11-03：`open` 指令与冲突文案

### 用户可调用指令

新增：

```text
@SecondBrain open
```

打开 Web UI；如果本地 Core 没有运行，会先自动启动再打开，不会打开一个死页面。启动失败时返回明确错误，并提示改用 `open_secondbrain.cmd` 或 `python -m secondbrain_core.cli --root memory open`。

- 新增 MCP 工具 `secondbrain_open`（无参数），返回 `{ok, url, core_started, browser_opened}`。
- 未配置 `SECONDBRAIN_PROJECT` 时，自动启动所需的项目根目录由适配器自身路径推导，因此在 DeepSeek Harness 里无需额外配置即可生效。
- MCP 帮助信息与 SecondBrain skill（含 Codex Plugin 副本）已同步新增该指令。

### 网页端

- 记忆列表中的冲突警示由“⚠ 可能冲突（N）”改为“⚠ 可能的冲突或重复（N）”。
- 冲突弹窗的标题、引导语、空状态和保存提示统一改为“可能的冲突或重复”措辞。

### 验证

- `python tools/sync_adapters.py --check`：`adapters in sync`
- `python -m pytest -q`：`17 passed`
- `node --check secondbrain_core/web/app.js`：通过
- 在线验证：停止 Core 后调用 `secondbrain_open`，返回 `core_started: true`，随后 `/health` 恢复 200

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
