# Architecture Decision Records

架构决策记录（ADR）用于把「为什么这样选」固化下来，方便长期迭代时回看与推翻。

## 格式

每个 ADR 文件：`NNNN-title.md`

状态：`Proposed` | `Accepted` | `Deprecated` | `Superseded`

## 索引

| 编号 | 标题 | 状态 |
|------|------|------|
| [0001](0001-kernel-not-full-agent.md) | 做成记忆内核而非完整 Agent 框架 | Accepted |
| [0002](0002-sqlite-first-storage.md) | 存储以 SQLite 为权威真相，向量/图可外置 | Accepted |
| [0003](0003-lightweight-graph-before-neo4j.md) | 图谱 MVP 用边表 + NetworkX，不上 Neo4j | Accepted |
| [0004](0004-ports-and-adapters.md) | 用 Port/Adapter 保证可替换后端 | Accepted |
| [0006](0006-pluggable-backends.md) | 阶段 6 可插拔升级后端（Redis/Qdrant/Neo4j/异步） | Accepted |
| [0007](0007-python-sdk.md) | 提供 Python HTTP SDK | Accepted |
| [0008](0008-agpl-commercial-dual-license.md) | AGPL-3.0 与商业双许可 | Superseded |
| [0009](0009-mit-license.md) | 许可改为 MIT（生态扩散） | Accepted |

## 何时必须写 ADR

- 引入/替换核心存储或中间件（Redis、Neo4j、Qdrant 等）
- 改变记忆删除、钉死、Reflection 写入等政策语义
- 破坏性 API 变更
- 否决一条曾 Accepted 的决策
