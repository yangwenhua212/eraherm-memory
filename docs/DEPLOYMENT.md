# 部署与升级对照

> 原则：**默认保持单机零中间件**；只在触发条件出现时打开对应后端。  
> 不要一次性全开 Redis + Qdrant + Neo4j。

---

## 1. 两套画像

| | 默认开发 / 单机 Demo | 生产升级（按需叠加） |
|--|----------------------|----------------------|
| 目标 | 跑通三大支柱、联调 Agent | 多实例 / 更大数据量 / 更强图查询 |
| 依赖 | Python + SQLite 文件 | 按开关增加 Redis / Qdrant / Neo4j |
| 运维 | 几乎为零 | 每开一个后端 +1 运维面 |
| 配置 | `.env.example` 原样即可 | 只改触发到的那几项 |

---

## 2. 最小配置对照

### 默认（推荐起步）

```env
ERAHERM_DATABASE_URL=sqlite:///./storage/eraherm.db
ERAHERM_SESSION_CACHE_BACKEND=memory
ERAHERM_VECTOR_BACKEND=sqlite
ERAHERM_GRAPH_BACKEND=networkx
ERAHERM_EMBEDDING_BACKEND=hashing
ERAHERM_FEEDBACK_ASYNC=false
ERAHERM_ADMIN_TOKEN=dev-admin-token
```

对应栈：

| 层 | 实现 |
|----|------|
| L1 | 进程内 dict |
| L2 事实 | SQLite |
| 向量 | SQLite BLOB |
| 图 | SQLite 边表 + NetworkX |
| Embedding | 本地 hashing（可改 openai） |
| Reflection | 同步启发式 |
| L3 | `storage/l3/` 本地文件 |

启动：

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

---

### 生产升级（按触发条件逐项打开）

| 触发条件 | 只改这些 | 安装 | 备注 |
|----------|----------|------|------|
| **多实例 / 多进程**，L1 要共享 | `ERAHERM_SESSION_CACHE_BACKEND=redis`<br>`ERAHERM_REDIS_URL=redis://...` | `pip install 'eraherm-memory[redis]'` | 先上 Redis，别急着动向量/图 |
| **记忆量大 / 召回 QPS 高** | `ERAHERM_VECTOR_BACKEND=qdrant`<br>`ERAHERM_QDRANT_URL=http://...`<br>或本地 `ERAHERM_QDRANT_PATH=./storage/qdrant` | `pip install 'eraherm-memory[qdrant]'` | `embedding_dim` 须与集合维度一致 |
| **多跳图查询变慢 / 要 Cypher** | `ERAHERM_GRAPH_BACKEND=neo4j`<br>`ERAHERM_NEO4J_URI=bolt://...`<br>`ERAHERM_NEO4J_USER=...`<br>`ERAHERM_NEO4J_PASSWORD=...` | `pip install 'eraherm-memory[neo4j]'` | 图权威源二选一，避免双写无迁移 |
| **Reflection 拖慢请求** | `ERAHERM_FEEDBACK_ASYNC=true` | 无需新依赖（内存队列） | 用 `GET /v1/feedback/{id}` 轮询；要可靠队列再换 ARQ |
| **要更好语义** | `ERAHERM_EMBEDDING_BACKEND=openai`<br>`ERAHERM_EMBEDDING_API_KEY=...` | 已有 httpx | 与 hashing 向量空间不兼容，换后端需重建向量 |
| **关掉主动预警/推荐** | `ERAHERM_PROACTIVE_ALERTS_ENABLED=false`<br>`ERAHERM_PROACTIVE_RECOMMEND_ENABLED=false` | 无 | Host 也可忽略返回的空数组字段 |
| **夜间记忆整理** | `ERAHERM_CONSOLIDATION_ENABLED=true` | `pip install 'eraherm-memory[scheduler]'` | 或手动 `eraherm-consolidate` / admin API |
| **IDE 一键挂载** | 配置 `mcp.json` | `pip install 'eraherm-memory[mcp]'` | 见 [MCP.md](MCP.md) |
| **冷备多机** | （后续）S3 ArchiveStore | 未默认内置 | 现阶段 `python -m app.ops.l3_dump` + 拷贝 `storage/l3` |

**不建议的「一次开满」示例（会突然变复杂）：**

```env
# ❌ 除非你已有运维能力，否则别一上来全开
ERAHERM_SESSION_CACHE_BACKEND=redis
ERAHERM_VECTOR_BACKEND=qdrant
ERAHERM_GRAPH_BACKEND=neo4j
ERAHERM_FEEDBACK_ASYNC=true
ERAHERM_EMBEDDING_BACKEND=openai
```

---

## 3. 推荐升级顺序

```text
单机默认
  → ① 多实例时：Redis（L1）
  → ② 召回压力：Qdrant（向量）
  → ③ 图查询压力：Neo4j
  → ④ 反馈变慢：feedback_async（再 ARQ）
  → ⑤ 主库并发：Postgres（尚未做，预留 Port）
```

每一步都应能单独回滚到上一项配置。

---

## 4. 验收清单（每开一个后端）

1. `GET /v1/health` 正常  
2. 对应能力冒烟：remember / recall / impact / feedback  
3. `GET /v1/metrics` 有计数增长  
4. 写一条 ADR 或变更说明：为何开、如何回滚  

---

## 5. 与文档关系

- 政策语义：`docs/specs/POLICIES.md`  
- 扩展点：`docs/specs/EXTENSION.md`  
- 决策记录：`docs/adr/0006-pluggable-backends.md`  
