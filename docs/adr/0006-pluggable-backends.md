# ADR 0006：阶段 6 引入可插拔升级后端

- 状态：Accepted
- 日期：2026-07-29

## 上下文

阶段 1–5 已用 SQLite + NetworkX + 进程内缓存跑通内核。生产扩展需要 Redis / Qdrant / Neo4j，但不能破坏 Port 契约。

## 决策

通过配置切换 Adapter，默认保持轻量栈：

| 配置 | 默认 | 升级值 |
|------|------|--------|
| `session_cache_backend` | `memory` | `redis` |
| `vector_backend` | `sqlite` | `qdrant` |
| `graph_backend` | `networkx` | `neo4j` |
| `feedback_async` | `false` | `true`（内存队列，可换 ARQ） |

可选依赖：`pip install 'eraherm-memory[redis,qdrant,neo4j]'`。

## 后果

- 正面：按触发条件升级，不改业务模块。
- 负面：需维护多 Adapter；Neo4j/Qdrant 需独立运维。
