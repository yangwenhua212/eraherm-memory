# 扩展指南

> 目标：长期迭代时，**换实现不换契约**。

---

## 1. Port / Adapter 模式

所有可变后端通过 Port（接口）注入，默认 Adapter 可替换。

```text
app/ports/
  vector_store.py      # upsert / search / delete
  graph_store.py       # upsert_entities / upsert_relations / impact_paths
  llm_client.py        # complete / extract_json
  embedding_client.py  # embed(texts) -> vectors
  session_cache.py     # L1 get/set/clear
  archive_store.py     # L3 put/list
  clock.py             # 可测试时间

app/adapters/
  sqlite_memory_repo.py
  sqlite_vec_store.py | chroma_store.py
  networkx_graph_store.py
  openai_compatible_llm.py
  openai_compatible_embedding.py
  memory_session_cache.py
  filesystem_archive.py
```

组装位置：`app/main.py` 或 `app/container.py`（组合根）。业务模块只依赖 ports。

---

## 2. 扩展点清单

| 扩展点 | 接口职责 | MVP Adapter | 升级路径 |
|--------|----------|-------------|----------|
| MemoryRepo | CRUD memories / soft delete | SQLite | Postgres |
| VectorStore | 向量写入与 top-k | sqlite-vec / Chroma | Qdrant |
| GraphStore | 实体关系与路径 | SQLite + NetworkX | Neo4j |
| SessionCache | L1 | dict / diskcache | Redis |
| ArchiveStore | L3 | 本地目录 | S3 |
| LLMClient | 抽取与 Reflection | OpenAI 兼容 | 本地 vLLM |
| EmbeddingClient | 向量化 | OpenAI 兼容 | bge-m3 本地 |
| ImportanceScorer | 重要性评分 | 规则启发式 | LLM 评分 |
| DecayPolicy | 衰减与删除 | 指数衰减 | 可插拔策略表 |
| ReflectionPipeline | 反馈后处理 | 单 prompt | 多步 + 人工审核队列 |

---

## 3. 如何替换向量后端（示例流程）

1. 实现 `VectorStore` 新 Adapter（如 `QdrantVectorStore`）。
2. 在配置增加 `vector.backend=qdrant`。
3. 组合根按配置注入；**不改** `memory` 模块召回逻辑。
4. 提供一次性迁移脚本：从旧库读 `memory_id + content` → 重新 embed → 写入新库。
5. 写 ADR 记录迁移窗口与回滚方式。

---

## 4. 如何替换图后端

1. 实现 `GraphStore.impact_paths(seed, max_hops, direction)`。
2. 保证边语义与 `relations.relation_type` 一致。
3. NetworkX → Neo4j 时保留相同 `entity_id`，避免 Host 侧缓存失效。

---

## 5. 策略插件（政策可版本化）

策略不应散落魔法数：

```text
docs/specs/POLICIES.md    # 人类可读政策
config/memory_policy.yaml # 机器可读（实现阶段引入）
```

建议可配置项：

- `decay_lambda_default`
- `promotion_importance_threshold`
- `recall_pinned_cap`
- `reflection_confidence_threshold`
- `graph_max_hops_default`
- `extract_on_remember`（bool）

变更政策若影响线上行为，记入 CHANGELOG，并视情况新增 ADR。

---

## 6. Host 集成方式

### 6.1 HTTP

任意语言通过 `/v1` 调用（见 [API.md](API.md)）。

### 6.2 未来 Python SDK（规划）

```python
from eraherm_memory import MemoryClient

client = MemoryClient(base_url="http://localhost:8000")
client.remember(session_id, content, pinned=False)
hits = client.recall(user_id, query="...")
client.feedback(answer_id, type="correct", correction_text="...")
```

SDK 仅为 API 薄封装，不复制业务逻辑。

---

## 7. 禁止事项（保持可演进）

1. 在路由层直接 `import openai` / `import neo4j`。
2. 在 Adapter 内调用 FastAPI Request 对象。
3. 无 ADR 引入第二套「并行真相」存储（例如同时双写两套无迁移计划的图库）。
4. 在未抽象 Port 前把 LangChain 等框架状态机嵌进内核（可在 Adapter 内局部使用）。

---

## 8. 测试扩展点

每个 Port 提供：

- Fake 实现（内存）供单元测试
- 契约测试：同一组用例在 Fake 与默认 Adapter 上行为一致（关键路径）

新增 Adapter 必须通过对应契约测试才可称为「可替换实现」。
