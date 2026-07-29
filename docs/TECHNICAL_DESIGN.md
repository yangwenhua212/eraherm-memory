# EraHerm-Memory 技术设计

> 状态：Draft v0.1  
> 更新日期：2026-07-29  
> 范围：内核架构、模块边界、运行时生命周期；不含具体业务 UI。

---

## 1. 目标与非目标

### 1.1 目标

- 提供可长期迭代的 **Memory Kernel**，以 HTTP/SDK 形式嵌入任意 Agent。
- 保证三类能力可独立演进、可替换实现：
  1. **分层记忆**：L1 会话 / L2 长期 / L3 休眠
  2. **知识图谱**：实体 + 关系 + 有限跳数路径查询
  3. **反馈进化**：点赞 / 点踩 / 纠正 → Reflection → 写回 L2
- 默认单机可跑通；存储与推理后端通过接口抽象，支持平滑升级。

### 1.2 非目标（阶段 0–1 不做）

- 完整 Agent 编排框架（规划、工具调用总线等）
- 多租户 SaaS 控制台、计费、权限体系（仅预留 `tenant_id` / `user_id`）
- 一上来引入 Redis / Neo4j / 分布式队列
- 自动「唤醒」L3 参与在线检索

---

## 2. 系统上下文

```text
┌─────────────┐     remember / recall / feedback      ┌──────────────────────┐
│  Host Agent │ ─────────────────────────────────────►│  EraHerm-Memory      │
│  (任意)      │ ◄─────────────────────────────────────│  Kernel (本项目)      │
└─────────────┘     memories / paths / ack             └──────────┬───────────┘
                                                                  │
                    ┌──────────────┬──────────────────────────────┼──────────────┐
                    ▼              ▼                              ▼              ▼
               LLM Provider   Embedding                      Storage        Object Store
               (抽取/反思)     (向量化)                    (SQLite+vec)      (L3 dump)
```

Host Agent 只依赖稳定 API；内核内部实现可换。

---

## 3. 逻辑架构（三大支柱）

```text
                    ┌─────────────────────────────────────────┐
                    │              API Gateway                 │
                    │         (FastAPI / 未来 gRPC)            │
                    └───────────────┬─────────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
   ┌─────────────┐          ┌─────────────┐           ┌──────────────┐
   │ Memory      │          │ Graph       │           │ Feedback     │
   │ Scheduler   │◄────────►│ Builder     │◄─────────►│ Loop         │
   │ L1/L2/L3    │          │ & Query     │           │ Reflection   │
   └──────┬──────┘          └──────┬──────┘           └──────┬───────┘
          │                        │                         │
          └────────────────────────┼─────────────────────────┘
                                   ▼
                    ┌─────────────────────────────────────────┐
                    │         Ports (可替换适配器)              │
                    │  VectorStore | GraphStore | LLM | Clock │
                    └─────────────────────────────────────────┘
```

### 3.1 分层记忆（Memory Scheduler）

| 层级 | 默认实现 | 职责 | 在线检索 |
|------|----------|------|----------|
| L1 | 进程内会话缓存 | 当前会话片段、临时上下文 | 是（本会话） |
| L2 | SQLite + 向量索引 | 长期事实、偏好、钉死项 | 是 |
| L3 | 文件系统 / 对象存储 dump | 冷归档 | **否**（MVP） |

**MVP 调度硬规则（不可随意增加复杂度）：**

1. `pinned=true`（身份、项目名、核心偏好等）→ 永驻 L2，衰减不得删除。
2. 会话内容先进 L1；会话结束按 `importance` + 时间衰减决定晋升 L2 或丢弃。
3. L3 只归档，不参与 recall。

衰减示意：

```text
effective_score = importance * exp(-λ * age_days) * feedback_boost
```

- `importance`：写入时评分（规则 + 可选 LLM）
- `feedback_boost`：点赞抬升、点踩/纠正调整
- `pinned` 项跳过删除路径，可仍参与排序

### 3.2 知识图谱（Graph Builder & Query）

- **写入**：对话/记忆入库后，异步或同步调用 LLM 抽取实体与关系，落边表。
- **查询**：给定实体，BFS / Dijkstra（权重）返回 ≤K 跳路径（MVP 默认 K=2）。
- **默认实现**：SQLite 边表 + NetworkX 内存视图；大数据量后换 Neo4j，**GraphStore Port 不变**。

### 3.3 反馈进化（Feedback Loop）

| 反馈类型 | 行为 |
|----------|------|
| `upvote` | 提高相关记忆权重，不新增事实 |
| `downvote` | 触发 Reflection，写入负例/禁忌类记忆 |
| `correct` | 触发 Reflection：分析错误原因 → 摘要写入 L2，更新相关权重 |

**噪声防护：**

- Reflection 产出需带 `confidence`；低于阈值只记 `feedback` 日志，不晋升钉死记忆。
- `correct` 默认生成「修订事实」；是否 `pinned` 由策略配置（默认：用户显式身份类纠正可钉死）。

---

## 4. 模块边界

| 模块 | 目录（约定） | 对外职责 | 不得做 |
|------|--------------|----------|--------|
| `api` | `app/api` | HTTP 契约、校验、鉴权钩子 | 业务算法 |
| `memory` | `app/memory` | 分层写入、召回、衰减、晋升 | 直接调图 DB |
| `graph` | `app/graph` | 抽取编排、路径查询 | 管理 L1 会话 |
| `feedback` | `app/feedback` | 反馈入库、触发 Reflection | 自己实现向量索引 |
| `ports` | `app/ports` | 抽象接口 | 具体 SDK 细节 |
| `adapters` | `app/adapters` | SQLite/Chroma/OpenAI/... | 泄漏到 API 层 |
| `models` | `app/models` | 领域模型与持久化 schema | HTTP schema 混用（可映射） |

依赖方向：**api → 领域模块 → ports ← adapters**。禁止 adapters 依赖 api。

---

## 5. 核心生命周期

### 5.1 Remember（写入）

```text
Host --remember(session, content, meta)-->
  L1.append
  optional: extract entities/relations --> GraphStore
  optional: if importance high or pinned --> L2.upsert + embed
```

### 5.2 Recall（召回）

```text
Host --recall(query, session, filters)-->
  merge:
    L1 session hits
    L2 vector top-k
    L2 pinned always include (可配置 cap)
  optional: graph expand (seed entities from query)
  rank by effective_score --> return
```

### 5.3 Feedback（反馈）

```text
Host --feedback(answer_id, type, correction?)-->
  persist FeedbackEvent
  if upvote: bump weights
  if downvote|correct: Reflection(LLM) --> MemoryCandidate
    if confidence >= threshold: L2.write + reweight related
    graph patch if entities changed
```

### 5.4 Session Close（会话结束）

```text
promote or drop L1 items by policy
optional: batch extract graph from session transcript
optional: schedule L3 dump (cron / admin)
```

---

## 6. 技术选型（默认栈）

| 能力 | MVP | 可替换升级 |
|------|-----|------------|
| 语言 | Python 3.12+ | — |
| API | FastAPI | gRPC / SDK only |
| 主存储 | SQLite + SQLModel | PostgreSQL |
| 向量 | sqlite-vec 或 Chroma | Qdrant / pgvector |
| 图 | NetworkX + 边表 | Neo4j |
| L1 | 进程内 / diskcache | Redis |
| L3 | 本地目录 dump | S3 兼容 |
| LLM / Embedding | OpenAI 兼容 API | 本地模型 |
| 异步任务 | 同步优先 | ARQ + Redis |

选型理由与否决项见 [ADR](adr/README.md)。

---

## 7. 配置与多环境

- 配置用环境变量 + `.env`（本地）；密钥不入库。
- 关键配置块：`storage`、`vector`、`graph`、`llm`、`memory_policy`、`feedback_policy`。
- `memory_policy` / `feedback_policy` 必须可版本化（写入 ADR 或 `docs/specs/POLICIES.md`），避免「黑盒越用越怪」。

---

## 8. 质量与可观测

| 项 | MVP | 后续 |
|----|-----|------|
| 测试 | 单元（调度规则、路径查询）+ API 契约测试 | 评测集（召回命中、纠正确认） |
| 日志 | 结构化 JSON：request_id, session_id, op | 接入 tracing |
| 指标 | 写入/召回延迟、Reflection 次数、L2 条数 | 仪表盘 |
| 迁移 | SQLAlchemy/Alembic 预留 | 强制版本迁移 |

---

## 9. 安全与隐私（基线）

- 记忆可能含 PII：默认单租户本地；多租户时强制 `user_id` 隔离查询。
- Feedback 纠正文本同样按用户隔离存储。
- L3 dump 视为敏感备份，权限与加密策略在进入多机部署前补齐 ADR。

---

## 10. 文档与演进约定

1. **行为变更**先改 `docs/specs/*`，再改代码。
2. **不可逆选型**写 ADR（模板见 `docs/adr/`）。
3. **路线图**只改 `docs/ROADMAP.md`；完成项打勾并注明版本。
4. 破坏性 API 变更：升主版本，并在 API 规范写迁移说明。

---

## 11. 相关文档

- [数据模型](specs/DATA_MODEL.md)
- [API 规范](specs/API.md)
- [扩展指南](specs/EXTENSION.md)
- [路线图](ROADMAP.md)
- [ADR 索引](adr/README.md)
