# 数据模型规范

> 状态：Draft v0.1  
> 存储默认：SQLite；字段命名用 snake_case；时间一律 UTC ISO-8601。

---

## 1. 设计不变量

1. 所有业务行具备 `id`（UUID v4 字符串）与 `created_at`。
2. 多租户预留：`tenant_id` 可空；单机默认 `null` 表示本地单租户。
3. `user_id` / `session_id` 由 Host 传入；内核不做账号系统。
4. **删除**：L2 默认软删 `deleted_at`；`pinned=true` 禁止物理删除与衰减删除。
5. 向量与行通过 `memory_id` 关联；向量实现可外置，逻辑外键仍以 Memory 为准。

---

## 2. 实体关系概览

```text
User/Tenant (逻辑, Host 侧)
    │
    ├── Session
    │     └── Memory (L1 映射或已晋升 L2)
    │
    ├── Memory ◄──── Embedding(vector)
    │     ▲
    │     └── FeedbackEvent ──► ReflectionRecord ──► Memory(派生)
    │
    ├── Entity
    └── Relation (from_entity → to_entity, 可挂 source_memory_id)
```

---

## 3. 表定义

### 3.1 `sessions`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | session_id |
| tenant_id | TEXT NULL | |
| user_id | TEXT NULL | |
| status | TEXT | `open` / `closed` |
| meta_json | TEXT | 任意 JSON |
| created_at | TEXT | |
| closed_at | TEXT NULL | |

### 3.2 `memories`

长期记忆主表（L2）；L1 可仅存内存，晋升时写入本表。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | |
| tenant_id | TEXT NULL | |
| user_id | TEXT NULL | |
| session_id | TEXT NULL | 来源会话 |
| content | TEXT | 记忆正文 |
| memory_type | TEXT | `fact` / `preference` / `identity` / `episode` / `negative` / `reflection` |
| importance | REAL | 0–1，写入时评分 |
| weight | REAL | 当前有效权重（含反馈调整） |
| pinned | INTEGER | 0/1，钉死 |
| decay_lambda | REAL | 衰减系数，可空用全局默认 |
| source | TEXT | `ingest` / `promotion` / `reflection` / `manual` |
| meta_json | TEXT | |
| created_at | TEXT | |
| updated_at | TEXT | |
| last_accessed_at | TEXT NULL | |
| access_count | INTEGER NOT NULL DEFAULT 0 | 召回命中累加；Consolidation 重排用 |
| deleted_at | TEXT NULL | 软删 |

**约束：**

- `pinned=1` 时，`memory_type` 建议为 `identity` / `preference` / `fact`。
- `effective_score` 为计算字段，不落库（或物化为缓存列，非权威）。

### 3.3 `embeddings`

| 字段 | 类型 | 说明 |
|------|------|------|
| memory_id | TEXT PK/FK | |
| model | TEXT | embedding 模型名 |
| dim | INTEGER | |
| vector | BLOB / 外置 | 实现相关 |
| created_at | TEXT | |

若使用外部向量库，本表可只存 `memory_id + model + external_ref`。

### 3.4 `entities`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | |
| tenant_id | TEXT NULL | |
| user_id | TEXT NULL | |
| name | TEXT | 规范名 |
| entity_type | TEXT | `person` / `project` / `service` / `tech` / `other` |
| aliases_json | TEXT | 别名列表 |
| meta_json | TEXT | |
| created_at | TEXT | |
| updated_at | TEXT | |

唯一性建议：`(tenant_id, user_id, lower(name), entity_type)` 逻辑唯一。

### 3.5 `relations`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | |
| tenant_id | TEXT NULL | |
| user_id | TEXT NULL | |
| from_entity_id | TEXT | |
| to_entity_id | TEXT | |
| relation_type | TEXT | 如 `depends_on` / `owned_by` / `uses` |
| weight | REAL | 默认 1.0 |
| confidence | REAL | 抽取置信度 |
| source_memory_id | TEXT NULL | |
| created_at | TEXT | |
| deleted_at | TEXT NULL | |

### 3.6 `feedback_events`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | |
| tenant_id | TEXT NULL | |
| user_id | TEXT NULL | |
| session_id | TEXT NULL | |
| answer_id | TEXT | Host 侧回答 ID |
| feedback_type | TEXT | `upvote` / `downvote` / `correct` |
| correction_text | TEXT NULL | |
| related_memory_ids_json | TEXT NULL | 关联记忆 |
| created_at | TEXT | |

### 3.7 `reflection_records`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | |
| feedback_id | TEXT FK | |
| analysis | TEXT | 「为什么错了」分析 |
| summary | TEXT | 写入记忆用的摘要 |
| confidence | REAL | |
| derived_memory_id | TEXT NULL | 成功写入时回填 |
| status | TEXT | `pending` / `accepted` / `rejected_low_confidence` / `failed` |
| created_at | TEXT | |

### 3.8 `l3_archives`（元数据）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | |
| uri | TEXT | 文件或对象存储路径 |
| checksum | TEXT | |
| memory_count | INTEGER | |
| created_at | TEXT | |

---

## 4. 领域对象（内存 / API 映射）

### MemoryRecord

```text
id, content, memory_type, importance, weight, pinned,
session_id?, user_id?, score?, meta
```

### GraphPath

```text
nodes: Entity[]
edges: Relation[]
hops: int
```

### FeedbackResult

```text
feedback_id, reflection_id?, derived_memory_id?, status
```

---

## 5. 索引建议（SQLite）

- `memories(user_id, pinned, deleted_at)`
- `memories(session_id)`
- `relations(from_entity_id)`
- `relations(to_entity_id)`
- `entities(user_id, name)`
- `feedback_events(answer_id)`

---

## 6. 迁移策略

- 引入 Alembic；每次 schema 变更一个 revision。
- 向量后端替换不强制改 `memories` 表，只改 embedding 适配器与可选 `embeddings` 形态。
- 破坏性字段变更：双写或扩展列 → 迁移脚本 → 废弃列，并写 ADR。
