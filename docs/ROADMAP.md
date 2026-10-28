# 路线图

> 原则：每个阶段结束都有可演示增量；不一次做完「大而全」。

---

## 战略定位（为什么先做记忆内核）

EraHerm-Memory 不是某个 IDE 的插件，而是 **Hermes 的长期记忆层**——个人 AI 操作系统里最底层的那一块：

```
HxSync（多设备、多 Agent 同步 / 神经网络）
   │
   ▼
Hermes Agent Core（调度者：规划、工具、对话）
   │
   ├── Memory Kernel ──────┐
   ├── Tool System          │
   └── Planner              │
                            ▼
                     EraHerm-Memory（记忆内核）
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
         事实记忆        项目记忆        用户记忆
```

**优先级顺序（为什么 Memory 先于 Cursor）：**

```
① EraHerm-Memory   记忆内核稳定（本仓库）
② Hermes Agent     核心 Agent 学会使用记忆
③ Hermes Tools     接入 Cursor / 手机 / Web / 浏览器 / 本地电脑
④ HxSync           多设备、多 Agent 同步
```

不是「Cursor → Memory → 其他」——Cursor 只是一个工具接入端，边界固定；Hermes 是通用 Agent 大脑，需要调工具、规划任务、长期记忆、学习用户习惯、管理多个 Agent。所以 **Memory 先服务核心 Agent**，工具端排在后面。

**角色分工：**

| 组件 | 角色 |
|------|------|
| Hermes | 调度者（思考 / 规划 / 调工具） |
| 手机 Agent | 执行者（调本地工具干活） |
| EraHerm-Memory | 共享记忆（跨 Agent 不串味） |
| HxSync | 神经网络（连接所有端） |

### 阶段 1 验收：证明三个能力

不要急着做超级 Agent，先证明：

1. **Hermes 能记住用户** — 新会话问「我最近在做什么」→ 召回上次保存的项目上下文
2. **Hermes 能记住项目** — 项目技术栈、目标写一次，之后任务自动参考
3. **Hermes 能调用工具** — 查记忆 → 分析 → 调工具 → 执行 → 汇报

（对照：Hermes 端 `memory_recall` 换词能命中、`memory_remember` 写入后跨会话可召回、`memory_impact` 返回影响面。）

### Memory 工具包装方向（Agent 能力化）

底层接口不裸露，向 Host 暴露更像 Agent 能力的封装：

```python
memory.learn()      # 从对话/反馈中沉淀
memory.remember()   # 显式写入事实
memory.reflect()    # 整理 / 压缩 / 冲突处理
memory.recall()     # 语义召回
memory.evolve()     # 纠正即进化（新事实压过旧版）
```

### 自我进化循环（Agent 经验系统）

```
任务 → 执行 → 失败 → 分析原因 → 写入 Memory → 下次自动规避
```

例：第一次部署失败，记录「缺环境变量」；第二次自动检查 `.env`。这就是 Agent 经验系统。

---

## 阶段 0 — 文档与契约

- [x] 项目定位与三大支柱
- [x] 技术设计主文档
- [x] 数据模型 / API / 扩展指南
- [x] 首批 ADR
- [x] 文档评审通过（进入阶段 1）

**退出标准：** 契约足以指导脚手架与表结构，无未决「用不用 Neo4j」类摇摆。

---

## 阶段 1 — 可运行内核骨架

- [x] 仓库结构：`app/` + ports/adapters + 组合根
- [x] SQLite schema + 基础仓储
- [x] `POST /memories`、`POST /recall`、`POST /sessions`
- [x] 钉死记忆：`pinned` 永不为衰减删除
- [x] 健康检查与配置加载
- [x] 单元测试：衰减/钉死规则

**Demo：** 写入身份类钉死记忆 → 清空会话上下文后仍能 recall 到。 ✅

---

## 阶段 2 — 向量召回 + L1 晋升

- [x] Embedding Adapter + VectorStore
- [x] Recall：L1 + L2 top-k + pinned 合并排序
- [x] Session close 晋升策略
- [x] 基础 importance 启发式

**Demo：** 多轮对话后关闭会话，重要事实进入 L2 并可语义检索。 ✅

---

## 阶段 3 — 轻量图谱

- [x] 实体/关系表 + NetworkX GraphStore
- [x] Remember 后可选抽取
- [x] `POST /graph/impact`（≤2 跳）
- [x] 简单路径可视化（demo UI 或 JSON 即可）

**Demo：** 「改 A 会影响谁」返回路径。 ✅

---

## 阶段 4 — 反馈进化闭环

- [x] `POST /feedback`（upvote/downvote/correct）
- [x] ReflectionPipeline + confidence 阈值
- [x] 写回 L2（含 negative / reflection 类型）与权重更新
- [x] 防噪声：低置信度不晋升

**Demo：** 纠正一次后，同类问题召回命中修订事实。 ✅

---

## 阶段 5 — 硬化与可运营

- [x] Alembic 迁移
- [x] L3 dump 元数据与脚本
- [x] 结构化日志 / 基础指标
- [x] 契约测试（Fake vs SQLite）
- [x] 最小 demo 前端（赞踩纠正）

**退出标准：** 可迁移、可冷备、可观测、Demo 可演示反馈闭环。 ✅

---

## 阶段 6 — 可插拔升级与 SDK

- [x] Redis SessionCache（可选依赖）
- [x] Qdrant VectorStore（可选依赖）
- [x] Neo4j GraphStore（可选依赖）
- [x] 异步 Reflection（内存队列 + `GET /feedback/{id}`）
- [x] Python SDK（`eraherm_memory.MemoryClient`）
- [x] 组合根按配置切换 + ADR

**退出标准：** 默认仍可单机零额外中间件运行；升级后端可通过配置启用。 ✅

---

## 阶段 7 — 主动预警 + 关联推荐

- [x] Remember 后冲突/技术栈切换 `alerts[]`（Host 决定是否弹窗）
- [x] Recall / Impact 旁路 `recommendations[]`（类似改动经验）
- [x] 配置开关与阈值（`ERAHERM_PROACTIVE_*`）
- [x] 评测 case + Demo 展示

**Demo：** Java→Go 写入触发预警；impact/recall 返回相关经验推荐。 ✅

---

## 阶段 8 — MCP 标准化 + 遗忘/压缩

- [x] MCP Server（`remember` / `recall` / `impact` / `consolidate`）
- [x] `mcp.json` + [MCP.md](MCP.md) 接入说明
- [x] Consolidation：重要性重排、摘要压缩、冲突淘汰
- [x] 召回访问计数（`access_count` / `last_accessed_at`）
- [x] CLI `eraherm-consolidate` + `POST /v1/admin/consolidate`
- [x] 可选 APScheduler 夜间任务

**Demo：** Claude Desktop / Cursor 挂载 MCP 后召回「核心依赖」；整理后冗余库配置压成一条摘要。 ✅

---

## 阶段 8+ 已落地

| 项 | 状态 |
|----|------|
| `eraherm-reembed` 全量重嵌 | 已实现 |
| `HermesMemoryTools` 内置 tool | 已实现 |
| `AgentMemory` 五能力封装（learn/remember/reflect/recall/evolve） | 已实现 |
| `fastembed` + `recall_min_score` | 已实现（见 CHANGELOG） |
| **召回门禁改判相关性（ADR 0010，2026-10-08）** | 已实现：绝对分门禁 + `exp(-λ·age)` 会让 `age > 28d` 的记忆永远召不回（线上表现为全库召回为空）。门禁改判 `relevance`（0.18 / 零词法 0.55），pinned 不参与衰减，排序改相关性主导，长文词法按长度二次折扣；`recall_gate_mode=score` 可回滚。回归 `tests/test_recall_gate_age_decoupled.py` |
| **命中增稳 + base 归一化（ADR 0011，2026-10-08）** | 已实现：`access_count` 从「只写不读」变为有效信号——`boost = min(1+0.35·ln(1+n), 3.0)`、`lambda_eff = lambda/boost`（命中 10 次半衰期 13.9→25.5 天），`recall_max_half_life_days=365` 护栏；排序里 base 改为候选集内归一化（原来是 0.02~0.1 量纲、等于没参与排序）。两个开关可逐位回滚。回归 `tests/test_recall_hit_boost.py` |
| **主动感知看门狗（phase 9）** | 已实现：`POST /v1/admin/watchdog` 巡检（倒计时/被遗忘宝石/健康信号），零 LLM；敏感记忆（秘密/红线）绝不推送；Host 侧 cron 每 6h 巡检、有料才推飞书（`~/.hermes/scripts/eraherm-watchdog.sh`） |
| **LLM 图谱抽取/反射（生产启用）** | 已实现：`ERAHERM_LLM_BACKEND=openai`（DeepSeek `deepseek-chat`）。规则抽不出的人物/事实关系（「用户 related_to 合作方」）由 LLM 抽取；纠正反射走 LLM 分析。**敏感内容防护**：含 秘密/红线/不要告诉 等词的输入回落本地规则（`app/sensitive.py`）。⚠️ 这是中文**词表匹配**，不是可靠的防泄漏边界；`openai` embedding 路径不经过它 |
| **HTTP 面认证 + 暴露面守卫（ADR 0012，0.10.2）** | 已实现：此前 `/v1/*` 除 admin 外**无任何认证**、`user_id` 自报，`host` 默认 `0.0.0.0`，可匿名读写/投毒/全库导出。现在：`ERAHERM_API_TOKEN`（配了则除 health 外都要带）、默认绑定 `127.0.0.1`、非回环且无 token 时**拒绝启动**、admin 端点 fail-closed（无默认口令 + 恒定时间比较）。回归 `tests/test_security.py` |
| **门禁旧配置折算修复（0.10.2）** | 已实现：`rel=(score-0.15)/0.85` 在默认点不连续（`0.25→0.18` 而 `0.251→0.1188`，零词法 `0.38→0.55` 而 `0.39→0.2824`）——「调高门禁」反而放宽。改为按默认点比例折算，连续且单调。回归 `tests/test_recall_gate_mapping.py` |
| **读路径写放大 / 丢更新修复（0.10.2）** | 已实现：`_touch_access` 由「逐条 get + merge 整行」改为单条 UPDATE（同时消除「召回覆盖 feedback 改过的 weight」）；recall 的 pinned/L1 分支由逐条 embedding 改批量；SQLite 补 WAL/busy_timeout；impact 路径枚举加上限并外提关系索引 |
| **Qdrant 适配器补 `get_meta`/`list_memory_ids`（0.10.2）** | 已实现：此前 reembed 静默全量重嵌、悬空向量清理恒为 0 |
| **取代链 + 关系有效期（ADR 0013，0.10.2）** | 已实现：纠正后旧记忆标 `superseded_by` 并从召回让路（不删除、可回滚），被取代记忆带出来的关系置 `valid_to` 失效。**遗留**：MCP `eraherm_evolve` 仍无法传 `related_memory_ids` → Cursor 路径上的"旧事实让路"不生效 |
| **敏感内容 × 远端 embedding fail-closed（ADR 0014，0.10.2）** | 已实现：命中词表即拒绝外发（400），三个 LLM 出网点全部有守卫 |
| **整理安全网 + 恢复接口（0.10.2）** | 已实现：`dry_run`、删除前自动 L3 归档（失败即放弃删除）、跨进程文件锁、`/v1/admin/memories/restore`、`/v1/admin/l3/restore` |
| **迁移路径可信化（0.10.2）** | 已实现：`0001` 改显式 DDL、新增幂等 `0003`/`0004`、CI 跑 `alembic upgrade head`、`tests/test_migration_schema.py` 做漂移守卫 |

## 阶段 8+ 后续（有触发再做）

| 触发条件 | 动作 |
|----------|------|
| 多实例 + 可靠异步 | JobQueue → ARQ/Redis；Consolidation → Celery Beat |
| 多机 L3 归档 | ArchiveStore → S3 |
| 命中增稳出现「通胀」（被无关查询捞出的记忆也在攒 boost） | 新增 `hit_count` 列：只在 `relevance ≥ recall_hit_boost_min_rel`（默认 0.35）时 +1，boost 改用 `hit_count`（需一次 schema 迁移，见 ADR 0011） |
| **单用户活跃记忆 ≥ 50 条，且某主题下 ≥ 3 条事实可合并** | 归纳型偏好提炼：`app/consolidate/service.py` 在 compress 之后加一个 phase，产出 `memory_type="insight"`；**必须**带 `related_memory_ids` + `confidence`（< 0.7 不写）；只增不删；单次最多新增 3 条；写库前过 `llm_sensitive_guard`；API 可列出/可删（可人工审）。防「看着合理但没根据」的洞察污染排序 |
| **`feedback_events` ≥ 2000 条且覆盖 ≥ 30 天** | 记忆评分的**在线学习**：先做多臂老虎机式的 `weight` 更新（按「召回后被采纳/被纠正」调），**不是 RL**（样本量决定，术语别混） |
| 夜间重播加固 | 观察项：命中增稳已覆盖大半价值，先看 access 分布再决定要不要做 |
| 主库并发 | MemoryRepo → Postgres |
| 冲突判定要更准 | ✅ 已做：LLM 冲突判定 Adapter（`llm_reflection.py`，生产已启用，敏感内容自动回落 heuristic） |
| MCP 远程共享 | Streamable HTTP transport |
| 第二个真人用户 / 要宣传 | 再补开源承接（Issue 模板等） |
| **Cursor / MCP 路径上要真正"旧事实让路"** | ⏸ **暂缓（2026-10-09 决定）**。服务端取代链已就绪（ADR 0013），缺的是调用方拿不到 `related_memory_ids`：`eraherm_evolve` 没有这个参数，`AgentMemory.evolve()` 依赖先 `recall()`。两条路二选一：① Host 侧保证「先召回再纠正」；② 服务端在纠正时按语义自己找候选旧记忆（需要一次阈值标定）。**触发条件**：真的有人在 Cursor / 外部 MCP 客户端上依赖「纠正后旧事实让路」这个行为 |
| 检索栈升级（ANN / BM25 混合 / reranker / query rewrite） | ⏸ **暂缓，且有前置条件**。ADR 0010/0011 的门禁阈值（0.18 / 0.55）是针对当前打分公式与当前 embedding 分数分布**手工标定**的；换检索公式会让阈值全部失效。**必须先**让评测能在真实 embedding 上跑（`ERAHERM_EVAL_SEMANTIC=1` 已留出口）→ 再换检索栈 → 重新标定阈值。详见 [KNOWN_ISSUES §2](KNOWN_ISSUES.md) |

---

## 版本号建议

| 版本 | 含义 |
|------|------|
| 0.x | 内核打磨，允许破坏性变更（文档同步） |
| 1.0 | API `/v1` 稳定，有迁移承诺 |
| 1.x | 新增 Adapter / 策略，向后兼容 |

---

## 近期下一步（按战略定位，Hermes 优先）

**重心：Hermes 自用跑通 + 记忆内核稳定**，不是开源社区运营。

1. 按 [HERMES_INTEGRATION.md §8 服务器上线检查表](HERMES_INTEGRATION.md) 勾完  
2. 本机：`python examples/correct_to_evolve.py`（纠正即进化一键验）  
3. Hermes 端三能力 Demo：记住用户 / 记住项目 / 调用工具  
4. **上线前必做（0.10.2 起）**：确认 `ERAHERM_HOST` + `ERAHERM_API_TOKEN` 组合正确
   （非回环地址必须配 token，否则启动失败），并设置 `ERAHERM_ADMIN_TOKEN`  
5. 可选：把 Unreleased 收成版本 tag，方便服务器 pin 版本

远程仓库：https://github.com/yangwenhua212/eraherm-memory
