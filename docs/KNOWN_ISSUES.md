# 已知问题与遗留项

> 本文是 2026-10-09 两轮审计 + 修复的收口记录：**修了什么**、**还开着什么**、**为什么**。
> 已修项的细节见 [CHANGELOG](../CHANGELOG.md) 的 Unreleased 段与
> [ADR 0012](adr/0012-api-auth-and-exposure-guard.md) /
> [0013](adr/0013-supersede-chain-and-relation-validity.md) /
> [0014](adr/0014-sensitive-content-remote-embedding.md)。

**审计方法**：逐文件静态阅读。本机缺 `sqlmodel`/`alembic` 且无网络，因此
**未运行完整测试套件**（不依赖 sqlmodel 的部分已跑通，见文末「验证状态」）。

---

## ✅ 已修

### 安全

| 问题 | 修复 |
|---|---|
| HTTP 面除 admin 外**无任何认证**，`user_id` 自报 → 任意用户记忆可读/可写/投毒 | `ERAHERM_API_TOKEN` + 路由级依赖（ADR 0012） |
| 无认证却可绑定 `0.0.0.0` | 默认绑 `127.0.0.1`；非回环 + 无 token → **拒绝启动** |
| admin 端点有可猜默认口令 + fail-open 回退 | 去掉默认值，未配置即 503，恒定时间比较 |
| L3 归档路径穿越（`user_id="../../evil"`） | `safe_filename()` + `resolve_within()`；`read()` 也做归档根收敛 |
| demo 存储型 XSS（`innerHTML`） | 改 `textContent` |
| **敏感内容外发到远端 embedding**（承诺「绝不出网」但未实现） | fail-closed 拒绝 + 三个出网点全部补守卫（ADR 0014） |
| `llm_reflection` 漏探 `answer_text` | 探测面覆盖所有进 prompt 的字段 |
| `LLMSummarizer` 是唯一没守卫的出网点 | 命中敏感词回落本地启发式 |
| 无任何限流 | 进程内令牌桶（600/min，可关），键为 token 的 sha256 |
| `pin_existing`/`adjust_weights`/`close_session`/L1 召回**无归属校验** | 全部带 `user_id` 校验（403 / 跳过） |

### 正确性

| 问题 | 修复 |
|---|---|
| `ERAHERM_RECALL_MIN_SCORE` 调高反而**放宽**门禁 | 按默认点比例折算（连续、单调）；回归测试会拿旧实现打脸 |
| `remember` 重要度不足且无 session 时**静默不落库**却返回 201 | 返回 `persisted`/`drop_reason` + 警告日志 |
| `memory_type` 接受任意字符串（正是静默丢弃的常见触发） | 按 `MemoryType` 枚举校验 |
| **「纠正即进化」没有版本概念**（只把旧条 weight 减 0.1） | 取代链：`superseded_by` + 召回跳过（ADR 0013） |
| 关系无有效期，纠错后 `impact` 仍答「A 依赖 B」 | `valid_from`/`valid_to` + 纠正时失效相关边 |
| recall 读路径整行回写 → **丢更新**（覆盖 feedback 改过的 weight）+ N+1 写 | 单条 `UPDATE`（`bump_access`/`add_weight`/`set_weight`/`set_weights_bulk`） |
| recall 逐条调用 embedding（openai 下每行一次 TLS + 一次计费） | 合并为一次批量 |
| 租户**事后过滤**向量结果 → 别的租户占满 top-k、本租户召回为空 | `embeddings.tenant_id` + `search(tenant_id=...)` 前置过滤 |
| 向量维度不匹配静默只用前 N 维 | （未改公式，但 README/DEPLOYMENT 已明确换模型必须重建；见下方遗留） |
| `apply_decay_deletions` 与召回路径**两套衰减语义** | 统一走 `decay_lambda_for` |
| SQLite 无 WAL / `busy_timeout` → 并发下 `database is locked` | `app/db.py` 统一挂 pragma |
| `impact` 路径枚举无上限 + 每条路径重建关系索引 | `ERAHERM_GRAPH_MAX_PATHS` + 索引外提 |
| Qdrant 适配器缺 `get_meta`/`list_memory_ids` → 静默全量重嵌、清理恒为 0 | 补齐（并把 `dim` 写进 payload） |
| `find_entity` 全表扫 + Python 归一化（每次 remember O(实体数²)） | `name_norm` 列 + 索引，快路径 O(1)，别名仍回退扫描 |

### 数据安全 / 可运维

| 问题 | 修复 |
|---|---|
| 整理是**不可逆**的破坏性操作，且**没有任何恢复接口** | `dry_run` + 删除前自动 L3 归档（归档失败即放弃删除）+ 两个恢复端点 |
| 多 worker 各自起 scheduler → 重复摘要、重复删原文 | `app/proclock.py` 跨进程文件锁 |
| 摘要会被再次摘要（语义逐轮漂移） | 摘要不再参与聚类 |
| 整理一次性 embed 全部候选 + O(N²) 全对全相似度 | 分批 embedding + 候选上限 |
| `InMemoryJobQueue` 无界、重启丢、lifespan 不 stop | `max_size` 溢出丢最旧并告警 + lifespan `stop()` |
| `InMemorySessionCache` 无界（远程 DoS 面） | 容量上限 + MRU 淘汰 |
| `RedisSessionCache.drop_lowest` 每次 append 都全量读写 | 先 `llen` 再决定 |
| 迁移路径不可信（`0001` 用 `create_all`，模型改动不产生迁移） | `0001` 改显式 DDL + 幂等 `0003`/`0004` + CI `alembic upgrade head` + 漂移测试 |
| `hermes-plugin/tests` 25 个测试从不进 CI | 纳入 `testpaths` |
| 缺 `py.typed` 却声明 `Typing :: Typed`；`evals/cases.json` 不进 wheel | package-data 补齐 |
| 依赖无上界（`apscheduler` 会装到不兼容的 4.x） | 补上界 |
| 评测只有 8 个 case、只做子串断言、无关查询不设负例 | 新增负例/排名/边界/跨用户隔离 case + `recall@k`/`MRR`/p50/p95 + `--strict` 延迟预算 |
| 无 Docker/Compose、无 Dependabot、无发布流程、无 lint/类型配置 | 全部补齐（lint/mypy 为 advisory，见下） |

---

## ❌ 仍然开着

### 1. 多租户 / 身份仍然是「自报」

`ERAHERM_API_TOKEN` 是**单租户共享密钥**：它认证「谁可以访问这个实例」，
**不**认证「你可以访问哪个 `user_id`」。拿到 token 的客户端仍可对任意 `user_id`
读写自己的数据（归属校验只挡住了"用别人的 memory_id 操作别人已有记忆"这条路）。

要真正修好：引入用户/凭据模型，`user_id` 从认证主体派生，请求体里不再接受 `user_id`。
这是一个产品级决策（要不要账号体系），没有在一次修复里做。

### 2. 检索栈仍然落后于同类项目

已做：租户前置过滤、`name_norm` 索引、批量嵌入。

**没做（刻意的）**：ANN/HNSW、BM25 混合检索、reranker、query rewrite、
chunking / contextual retrieval。默认后端仍是「全表 Python cosine」。

不做它的理由不是懒：ADR 0010/0011 的门禁阈值（`recall_rel_min=0.18` /
`recall_rel_min_no_lexical=0.55`）是**针对当前打分公式和当前 embedding 的分数分布手工标定的**。
换检索公式会让这些阈值失效，而重新标定必须跑真实评测
（本机跑不了，且 harness 默认用 hashing）。正确顺序是：
先让评测能在真实 embedding 上跑（`ERAHERM_EVAL_SEMANTIC=1` 已留出口）→ 再换检索栈 → 重新标定。

### 3. 知识图谱不是时间图 / 实体图

已做：`valid_from`/`valid_to`、纠正时失效相关边、`name_norm` 索引。

没做：实体摘要、社区检测、episode 归属、**自动别名合并**
（`merge_entities_by_alias` 依然不存在，POLICIES.md 已如实标注）。
关系仍只有 3 条正则（LLM 抽取默认关闭），置信度仍是硬编码。

### 4. 「纠正即进化」的 Host 侧路径仍有缺口 —— ⏸ 已决定暂缓

服务端现在会创建取代链（ADR 0013），但**前提是调用方传了 `related_memory_ids`**：

- `AgentMemory.evolve()` 依赖 `self._last_memory_ids`（必须先 `recall()` 过）；
- `eraherm_evolve`（MCP 工具）**没有这个参数** → Cursor 那条路径上
  "让旧事实让路"仍然不生效。

**决定（2026-10-09）：暂缓。** 两条修法都需要额外决策或标定，而当前没有实际调用方
依赖这个行为：

1. Host 侧保证「先召回再纠正」——需要改 Host 代码，属于集成方的事；
2. 服务端在纠正时自己按语义找候选旧记忆——更可靠，但要引入一次判定策略与阈值标定；
   在本机无法跑真实评测的前提下，标定出的阈值没有依据（同 §2 的问题）。

**重新考虑的触发条件**：真的有人在 Cursor / 外部 MCP 客户端上依赖「纠正后旧事实让路」。
在那之前，**通过 HTTP / SDK 调用并显式传 `related_memory_ids` 的路径是正常工作的**。

### 5. 整理仍是启发式

已做：dry-run、归档、恢复、锁、批量、摘要不递归。

仍是启发式：冲突判定是「3 组硬编码关键词 + 词法阈值」，误判现在**可恢复**但依然可能发生；
`run_for_user` 每个阶段都会重新全量加载；没有归纳型 `insight`（ROADMAP 挂了触发条件）；
没有权重在线学习（触发条件 `feedback_events ≥ 2000`）。

### 6. 工程化仍是「半成品」

- lint（ruff）与类型检查（mypy）在 CI 里是 **advisory**（`continue-on-error`），
  因为基线远未清干净；**不是**门禁。
- 无覆盖率门禁（只有配置）。
- `Dockerfile`/compose **没有被构建验证过**（本机无 docker）。
- `--workers > 1` 仍不安全：L1 缓存 / 调度器是进程内的（锁只解决重复整理），
  主库仍是单文件 SQLite。Redis 只解决 L1，不足以让多 worker 变安全。
- 全同步实现（Starlette 线程池，无按路由并发限制）。
- 无 `Idempotency-Key`；`content`/`query` 现有长度上限，但没有请求体大小上限。
- 可观测性仍是进程内计数器，无分位/Prometheus/OTel/跨进程聚合。

### 7. 未验证路径

- **Neo4j**：`graph_backend=neo4j` 没有可用测试（`test_phase6.py` 只覆盖 ImportError 分支，
  装了 neo4j 就 skip）。我加的方法（`invalidate_relations_for_memories`、`valid_to` 过滤）
  同样**未被执行过**。
- **Qdrant**：`get_meta`/`list_memory_ids`/租户 filter 未在真实 Qdrant 上验证。
- **Redis**：`drop_lowest` 的改动未在真实 Redis 上验证（fakeredis 覆盖了 happy path）。
- 迁移 `0003`/`0004`：本机无 alembic，**未执行**。`tests/test_migration_schema.py` 会在
  装了 alembic 的环境（CI）里验证「迁移结果 == 当前模型」。

---

## ⚠️ 需要更正的审计结论（避免误报留在文档里）

1. **撤回**「Neo4j 适配器对 `Node` 调 `.get()` 必然 `AttributeError`」：
   neo4j 5.x 的 `Entity` 实现了 `Mapping`，`get()` 存在；`name_norm` 的读写也是自洽的。
   未实测，所以仍列为「未验证路径」。
2. **撤回**「`tests/test_evals.py` 的 `passed >= 6` 允许 2 个 case 失败」：
   同测试第 15 行已要求全通过。
3. **撤回**「`min_score` 在 `gate_mode=score` 下被忽略」：它经 `threshold` 生效。
4. **撤回**「`redis_session_cache` 里 `def list` 遮蔽内置 `list` 有风险」：
   类命名空间不是方法的词法外层作用域。

## 验证状态

**已在本机真实跑通（2026-10-09 收口）** —— 沙箱封了出站 TLS 导致长期无法安装依赖，
提权后完整执行了一次：

```
alembic upgrade head              0001 → 0002 → 0003 → 0004 全部成功
python -m pytest -q               232 passed, 1 skipped in 12.61s
python -m evals.harness --strict  16/16 passed, recall_at_k=1.0, mrr=1.0, p50≈7ms
python scripts/check_eval_gates.py  0 problems
```

唯一 skip 的是 `requires_semantic_embedding` 用例（需真语义嵌入；
`ERAHERM_EVAL_SEMANTIC=1` 时执行），属设计如此。

**首次运行额外抓到 2 个产品缺陷并已修复**（详见 CHANGELOG「0.10.2 第三批」）：

1. `alembic/env.py` 的 `fileConfig()` 未关 `disable_existing_loggers` →
   **任何程序化执行迁移的进程会丢掉自己全部已有日志**；
2. `setup_logging()` 的 `root.handlers.clear()` → 会清空宿主进程的日志配置。

**仍未验证的**：只有环境依赖的部分（Docker 构建、真实 Neo4j/Qdrant/Redis）。
它们不影响测试套件，但上线前需在对应环境里各自跑一遍。

### 自己复现这套验证

```bash
python -m pip install -e ".[dev,mcp,scheduler]"
alembic upgrade head
python -m pytest -q
python -m evals.harness --strict --max-ms 500
python scripts/check_eval_gates.py       # 不需要 sqlmodel 的离线门禁校验
```

> 注意 `mcp` 必须满足 pyproject 的 `mcp>=1.9,<2`。装成 `mcp 2.x` 会报
> "MCP extra required"，因为 2.x 把 `FastMCP` 改名成了 `MCPServer`。
