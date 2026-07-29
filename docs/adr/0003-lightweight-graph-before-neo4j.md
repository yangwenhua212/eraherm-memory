# ADR 0003：图谱 MVP 用边表 + NetworkX，不上 Neo4j

- 状态：Accepted
- 日期：2026-07-29

## 上下文

「改 A 会影响谁」需要图路径，但不需要一上来的图数据库运维。瓶颈通常在实体抽取质量，而非图引擎。

## 决策

- MVP：`entities` / `relations` 存 SQLite；查询侧用 NetworkX（或等价内存图）做 ≤2 跳。
- 抽象 `GraphStore` Port；将来可换 Neo4j 而不改 API。

## 后果

- 正面：实现快、依赖少、够演示结构推理。
- 负面：超大规模图或复杂 Cypher 级查询需后续迁移；需控制单用户边规模或按需加载。
