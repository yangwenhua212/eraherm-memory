# 部署与升级对照

> 原则：**默认保持单机零中间件**；只在触发条件出现时打开对应后端。  
> 不要一次性全开 Redis + Qdrant + Neo4j。

---

## 1. 两套画像

| | 默认开发 / 单机 Demo | **挂真 Agent / 生产** |
|--|----------------------|----------------------|
| 目标 | 跑通三大支柱、联调骨架 | 语义召回可信、给用户用 |
| Embedding | `hashing`（离线零依赖） | **`fastembed`（本地中文）或 `openai` / 兼容端点（强制）** |
| 依赖 | Python + SQLite 文件 | + Embedding API；按需 Redis / Qdrant / Neo4j |
| 运维 | 几乎为零 | 密钥与维度管理；换模型需重建向量 |
| 配置 | `.env.example` 可原样跑 Demo | **必须改掉 hashing** |

> **口碑红线**：对外演示「记得住」或接入 Hermes 时，若仍用 `hashing`，中文语义召回会偏弱，用户会以为记忆坏了。开发默认保留 hashing 是为了 CI/离线，不是生产推荐。

---

## 2. 最小配置对照

### 默认（仅开发 / CI / 离线 Demo）

```env
ERAHERM_DATABASE_URL=sqlite:///./storage/eraherm.db
ERAHERM_SESSION_CACHE_BACKEND=memory
ERAHERM_VECTOR_BACKEND=sqlite
ERAHERM_GRAPH_BACKEND=networkx
ERAHERM_EMBEDDING_BACKEND=hashing
ERAHERM_FEEDBACK_ASYNC=false
ERAHERM_ADMIN_TOKEN=dev-admin-token
```

### 生产 / Hermes（Embedding 写死，先改这一项）

**方案 A — 本地中文（推荐，与 Hermes 服务器一致）：**

```bash
pip install 'eraherm-memory[fastembed]'
```

```env
ERAHERM_EMBEDDING_BACKEND=fastembed
ERAHERM_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
ERAHERM_EMBEDDING_DIM=512
# 可选缓存目录；也可用环境变量 FASTEMBED_CACHE_PATH
# ERAHERM_EMBEDDING_CACHE_DIR=./storage/fastembed
```

**方案 B — OpenAI 兼容 API：**

```env
ERAHERM_EMBEDDING_BACKEND=openai
ERAHERM_EMBEDDING_API_KEY=sk-...
ERAHERM_EMBEDDING_BASE_URL=https://api.openai.com/v1
ERAHERM_EMBEDDING_MODEL=text-embedding-3-small
ERAHERM_EMBEDDING_DIM=1536
# 其余可仍用 SQLite；有需要再按下面表格叠加 Redis/Qdrant/Neo4j
```

对应栈：

| 层 | 实现 |
|----|------|
| L1 | 进程内 dict |
| L2 事实 | SQLite |
| 向量 | SQLite BLOB |
| 图 | SQLite 边表 + NetworkX |
| Embedding | 本地 hashing（**仅开发**；生产见上节） |
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
| **挂真 Agent / 要语义召回准** | `ERAHERM_EMBEDDING_BACKEND=fastembed` + `MODEL=BAAI/bge-small-zh-v1.5` + `DIM=512`<br>或 `openai` + API Key + 维度一致 | `pip install 'eraherm-memory[fastembed]'` 或已有 httpx | **生产必改**；与 hashing 向量空间不兼容，换后端需重建向量 |
| **压制硬拉低分命中** | `ERAHERM_RECALL_MIN_SCORE=0.25`（默认）；请求可传 `min_score` 覆盖 | 无 | 不相关查询应返回空 `items[]`；语料多了可略调高 |
| **换 embedding 后端 / 维度** | 先改 `.env` 的 backend/model/dim，再跑迁移 | 见下节 | **禁止双轨**；旧向量空间一次性覆盖 |
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

## 3.1 换 Embedding：全量重嵌（必做）

切 `hashing` → `fastembed` / `openai`，或改模型维度后，**不要**保留双轨哈希兜底。用当前后端一次性覆盖向量：

```bash
# 1) 先改 .env（示例：中文本地）
# ERAHERM_EMBEDDING_BACKEND=fastembed
# ERAHERM_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
# ERAHERM_EMBEDDING_DIM=512

# 2) dry-run 看报告
eraherm-reembed --dry-run --orphan-user-id <你的稳定 user_id>

# 3) 执行（把 user_id=None 的孤儿归到指定用户，并删悬空向量）
eraherm-reembed --orphan-user-id <你的稳定 user_id>

# Qdrant 且维度变了：加 --recreate-collection
# eraherm-reembed --orphan-user-id ... --recreate-collection --force
```

等价 Admin API：`POST /v1/admin/reembed`（Header `X-Admin-Token`）。

| 孤儿策略 | 含义 |
|----------|------|
| `assign`（默认） | 要求 `--orphan-user-id`，写入 memory + 向量后的 `user_id` |
| `skip` | 不迁孤儿（仍是召回孤岛） |
| `fail` | 发现孤儿直接失败退出 |

已对齐 model/dim/user_id 的行会跳过；`--force` 强制全量重算。可重复执行，适合以后每次换模型。

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
