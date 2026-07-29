# ADR 0002：存储以 SQLite 为权威真相，向量/图可外置

- 状态：Accepted
- 日期：2026-07-29

## 上下文

需要同时存事实记忆、反馈、实体关系。过早引入 Postgres + 独立向量库 + 图库会提高运维与心智负担。

## 决策

- **权威数据**（memories、feedback、entities、relations、sessions）落在 **SQLite**（SQLModel/SQLAlchemy）。
- 向量索引可为 sqlite-vec / Chroma 等，通过 `memory_id` 关联；可整体替换。
- 单机默认；数据量与并发成为瓶颈后再迁 Postgres，表语义保持不变。

## 后果

- 正面：零依赖可跑通；迁移路径清晰。
- 负面：超高并发与多写者不适合长期停留在 SQLite；需在阶段 6+ 设触发条件升级。
