# ADR 0013：取代链与关系有效期（让「纠正即进化」成为数据结构）

- 状态：Accepted
- 日期：2026-10-09
- 依赖：[ADR 0010](0010-recall-gate-relevance.md)（门禁判相关性）、[ADR 0011](0011-hit-boost-and-base-normalization.md)（命中增稳）

## 上下文

README 的头号承诺是**「纠正即进化」**：用户说「不对，应该是 X」→ 下次同类问题优先新版本。
但 0.10.1 之前，代码里没有任何东西表达「版本」：

- `MemoryRow` 没有 `version` / `superseded_by` / `valid_from` 等字段（全仓 `supersed*` 零命中）。
- 一次 `correct` 反馈实际做的是：**新增**一条 pinned 记忆（`_finalize_reflection`），
  再把相关旧记忆的 `weight` 减 0.1（`downvote_weight_delta`）。
- 于是**旧错仍然留在库里、仍然参与召回竞争**，只是权重低了 10%；
  两条记忆之间没有任何结构性联系，"旧版让路"完全靠打分排序碰运气。
- 关系表 `relations` 同样没有有效期，纠错只改了记忆，那条边还活着 ——
  `impact` 仍会回答「A 依赖 B」。

对一个主打「纠正即进化」的项目来说，这是**定位与实现之间最大的缺口**。

## 决策

### 1. 记忆的取代链

新增 `memories.version` / `superseded_by` / `superseded_at`。

- 纠正反射产生新记忆后，把被纠正的旧记忆标记 `superseded_by = <新记忆 id>`、
  `superseded_at = now`。
- **不删除**：历史仍可审计、可回滚（`version` 从 1 起，`superseded_by` 构成单向链）。
- 召回默认跳过已取代的记忆（`ERAHERM_RECALL_EXCLUDE_SUPERSEDED=true`，可关）：
  它们不再参与打分与门禁，但仍可被管理端点按 id 查到。
- 图谱侧：被取代记忆「带出来的」关系（`relations.source_memory_id ∈ 被取代 ids`）
  一并置 `valid_to = now`，于是 `impact` 不再回答已经作废的依赖。

### 2. 关系的时间有效性

新增 `relations.valid_from` / `valid_to`。

- 新建关系时写 `valid_from`；`valid_to IS NULL` = **当前有效**。
- 再次观察到同一条关系时清空 `valid_to`（"again true"）。
- `impact_paths` / `_load_graph` 只加载 `valid_to IS NULL` 的边。

这让系统至少能回答「以前是 X，现在是 Y」这类问题 —— 不是完整的时序知识图谱
（没有实体摘要、社区、episode 归属，也不做冲突消解），但比"只有当前状态"强，
而且是**可审计**的：作废的边还在表里。

## 后果

### 正面

- 「纠正即进化」从"排序碰运气"变成**结构保证**：被取代的旧事实不再出现在召回结果里，
  无论嵌入分数怎么算。README 里"数据结构层面的版本管理"这句话，现在是真的。
- 纠错是**可回滚**的：把 `superseded_by` 置空即可让旧版本重新参与召回（管理端点/直接改库），
  没有信息被销毁。
- 图谱与记忆的版本同步，`impact` 不会再指向已被纠正掉的依赖。

### 负面 / 已知限制

- 这**不是**双时态（bitemporal）数据库：没有「在 T 时刻我认为 X」的查询能力，
  `superseded_at` 只是"什么时候被取代"。
- 取代是**单向**的：A 被 B 取代后，如果 B 又被 C 取代，链是 A→B→C；
  没有做链上的收敛（例如"最终有效版本"），查询时只判断 `superseded_by IS NULL`，
  因此 C 有效、A/B 都失效 —— 语义正确，但没有"取最新版本内容"的便捷接口。
- 取代判定依赖调用方传入的 `related_memory_ids`：`AgentMemory.evolve()` 会在
  没先 recall 的情况下传空列表，`eraherm_evolve`（MCP）压根没有这个参数 →
  **Cursor 那条路径上的"旧事实让路"仍然不生效**。这是遗留项（见 KNOWN_ISSUES
  「纠正即进化比宣传弱」），修它需要 Host 侧先召回再纠正，或让服务端按语义自己找候选。
- 迁移：`0003_supersede_validity_tenant`（幂等；`0001` 同时在本次改为显式 DDL）。

## 参考

- 实现：`app/feedback/service.py`（取代 + 关系失效）、`app/memory/service.py`
  （`supersede_memories` / 召回过滤）、`app/adapters/networkx_graph_store.py`、
  `app/adapters/neo4j_graph_store.py`
- 迁移：`alembic/versions/0003_supersede_validity_tenant.py`
- 相关：[KNOWN_ISSUES.md](../KNOWN_ISSUES.md)
