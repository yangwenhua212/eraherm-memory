# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)（`0.x` 允许破坏性变更，见 [API 规范](docs/specs/API.md)）。

## [Unreleased]

> 本段包含**破坏性**变更：默认绑定地址、admin 端点行为、`remember` 语义可见性都变了。
> 升级前请读 [ADR 0012](docs/adr/0012-api-auth-and-exposure-guard.md)。

### Fixed

- **召回门禁量纲错配：记忆超过约 28 天后全库召回为空**（2026-10-08 生产实测）。`score = base × (0.15+0.85·rel)` 且 `base` 含 `exp(-decay_lambda·age)`，门禁却卡绝对分（0.25/0.38）——**分数上限等于 `base`**，`age > 27.7 天` 时即使 `relevance=1.0` 也过不了门禁。生产库 9 条活跃记忆 `base` 全在 0.025~0.099，recall 对任何查询（含同义换词问法）都返回空；线上用户唯一能过门禁的是一条 3 天前的 2920 字镜像长文，导致不同查询返回同一条。修复见 [ADR 0010](docs/adr/0010-recall-gate-relevance.md)：门禁改判**相关性**（`recall_rel_min=0.18` / `recall_rel_min_no_lexical=0.55`），`score` 退居排序。回归测试 `tests/test_recall_gate_age_decoupled.py`
- **pinned 记忆参与年龄衰减**：与「钉死记忆不因衰减删除」的承诺矛盾——没被删，但已召不回。改为 `recall_pinned_no_decay=true`（pinned 走 `decay=0`）
- **长文「大杂烩」绕过词法门禁**：一条几千字的记忆与几乎所有查询都有词法重叠。词法信号改为按内容长度**二次折扣**（`recall_lexical_len_norm=300`，折扣后低于 `_LEX_EVIDENCE_MIN=0.02` 视为零词法，走从严门禁）。实测把 2920 字镜像长文从「所有查询都命中」压回门禁之下

### Changed

- **二段重排：排序由相关性主导**。排序键从 `score`（=base×rel）改为 `relevance + 0.2×base + pinned_boost`，否则又长又 pinned 的记忆会压过更相关的短记忆（实测：更相关的短记忆被那条又长又 pinned 的定案记忆挤到第二）
- `recall_gate_mode` 新增（默认 `relevance`）。旧绝对分门禁保留为 `recall_gate_mode=score` 回滚开关；旧配置 `recall_min_score` / `recall_min_score_no_lexical` 在 `relevance` 模式下按 `rel = (score-0.15)/0.85` 换算（**该换算在默认点不连续 —— `0.25→0.18` 而 `0.251→0.1188`，即「调高反而放宽」；已在 0.10.2 改为按默认点比例折算，见下方 Fixed**）；`min_score<=0` 仍表示关闭门禁
- **排序键 base 项改为候选集内相对归一化**（`recall_rank_base_normalize=true`）：`base` 是 0.02~0.1 量纲，原来乘 0.2 后比 relevance 低两个数量级、等于没参与排序。归一化后 base 项铺满 `[0, 0.2]`，只做破平、永不压过相关性（见 [ADR 0011](docs/adr/0011-hit-boost-and-base-normalization.md)）
- **命中增稳**（`recall_hit_boost_enabled=true`）：`boost = min(1 + 0.35·ln(1+access_count), 3.0)`，`lambda_eff = lambda / boost`。被召回过的记忆衰减变慢（命中 10 次半衰期 13.9 天 → 25.5 天），`pinned` 仍在 boost 之前短路，另有 `recall_max_half_life_days=365` 硬护栏防「永生条目」。`access_count` 从「只写不读」变为有效信号

### Added

- `/v1/recall` 响应项新增诊断字段 `relevance` / `lexical` / `vector_sim` / `base`（排查「为什么这条召回不到」不必在客户端重算）
- `/v1/recall` 响应项新增诊断字段 `hit_boost` / `decay_lambda_eff`（命中增稳的可见性：这条记忆当前的稳定性倍数与实际衰减系数）。回归测试 `tests/test_recall_hit_boost.py`（10 例：单调性/有界性/开关等价/半衰期护栏/常用者排前/相关性仍压过 base）
- 主动感知看门狗（phase 9）：`POST /v1/admin/watchdog` 巡检记忆库，产出「值得说的事」——倒计时事件（D-7/D-3/D-1/当天）、被遗忘的高价值记忆（importance≥0.8 且从未被 recall）、健康信号。**零 LLM / 零外部 API**（SQLite + 正则 + 标准库）。敏感记忆（秘密/红线类）绝不进入推送。回归测试 `tests/test_watchdog.py`（5 例）
- 生产启用 LLM 图谱抽取/反射（`ERAHERM_LLM_BACKEND=openai`，DeepSeek `deepseek-chat`）：规则抽取器抽不出的人物/事实关系（「用户 related_to 合作方」）现在由 LLM 抽取，图谱支柱真正兑现
- **敏感内容防护**（`app/sensitive.py`）：LLM 抽取/反射的输入命中敏感词（秘密/红线/不要告诉/不能提 等）→ 直接走本地规则/heuristic，**内容绝不出网**。watchdog 的敏感推送过滤改复用同一词表（一份定义，三处生效）。回归测试 `tests/test_llm_sensitive_guard.py`（10 例）

### Security

- **整个 HTTP 面此前没有任何认证**，`user_id` 由调用方自报 → 任何能访问端口的人都能读写、
  篡改、删除任意用户的记忆（含 `/v1/memories/pin` 改 pin、`/v1/feedback` 的
  `related_memory_ids` 调权重）。新增 `ERAHERM_API_TOKEN`：设置后 `/v1/*`（除 `/v1/health`）
  一律要求 `X-API-Token` 或 `Authorization: Bearer`。见 [ADR 0012](docs/adr/0012-api-auth-and-exposure-guard.md)
- **启动守卫（fail-fast）**：`ERAHERM_HOST` 不是回环地址、且没有配置 `ERAHERM_API_TOKEN` 时
  进程**拒绝启动**，而不是安静地把无认证记忆库暴露到网络。`ERAHERM_ALLOW_INSECURE_PUBLIC=true`
  可显式覆盖（不推荐）
- **默认绑定地址 `0.0.0.0` → `127.0.0.1`**（无认证时唯一安全的取值）
- **admin 端点去掉可猜默认口令**：不再有 `dev-admin-token` 兜底，也不再有 `settings` 缺失时
  fallback 到默认值的 fail-open 路径；未配置一律 503，比较改用 `secrets.compare_digest`
- **L3 归档路径穿越**：`POST /v1/admin/l3/dump` 的 `user_id` 会拼进归档文件名，
  `user_id="../../evil"` 可写到归档根目录之外。现在文件名经 `safe_filename()` 收敛，
  写入前再由 `resolve_within()` 断言路径未逃出归档根
- **demo 存储型 XSS**：`setStatus()` 用 `innerHTML` 渲染，而其中的实体名、记忆正文摘要、
  纠正文本都来自用户可写数据；配合"无鉴权"就是无需受害者输入的存储型 XSS。
  改为 `textContent`（需要换行的地方新增 `setStatusLines()`）
- 敏感内容守卫的表述修正：`app/sensitive.py` 只是**中文关键词表**，且只覆盖 LLM 抽取/反射。
  `openai` embedding 路径、`LLMSummarizer`、以及 `llm_reflection` 的 `answer_text`
  都不经过它。`.env.example` / README 不再宣称"绝不出网"

### Fixed（0.10.2 加固）

- **`ERAHERM_RECALL_MIN_SCORE` 调高反而放宽门禁**（ADR 0010 的换算公式在默认值处不连续）：
  旧实现 `rel=(score-0.15)/0.85` 且默认值特判，导致 `0.25 → rel_min=0.18` 而
  `0.251 → 0.1188`，零词法档 `0.38 → 0.55` 而 `0.39 → 0.2824`。改为按默认点比例折算
  `rel = rel_default × (score/score_default)`，**连续且单调**。回归测试
  `tests/test_recall_gate_mapping.py`（旧实现会在 0.251 处失败）
- **`remember` 静默不落库**：重要度低于提升阈值且没有 `session_id` 时（例如
  `memory_type="episode"`、闲聊内容），API 依然返回 201 + 一个 id，但其实什么都没写。
  现在返回 `persisted` / `drop_reason` 并打 `memory_not_persisted` 警告
- **`memory_type` 不再接受任意字符串**：未知类型会落到 importance 兜底基线 0.5（< 0.6），
  正是上面那条静默丢弃的常见触发方式。现在按 `MemoryType` 枚举校验（422）
- **召回是"读路径整行回写"**：`_touch_access` 逐条 `get → save_memory(merge 整行)`，
  默认 top_k=8 即 8 次 SELECT + 8 个写事务，并且会把并发写者（如 feedback 改过的
  `weight`）用陈旧快照覆盖回去。改为单条 `UPDATE`（新增 `bump_access` /
  `add_weight` / `set_weight` 三个定向更新方法，契约测试的 fake 实现同步补齐）
- **recall 逐条调用 embedding**：pinned 补充分支与 L1 分支都是每行一次
  `embed([...])`（openai 后端下每行一次 TLS 握手 + 一次计费调用）。改为一次批量
- **SQLite 缺 WAL / busy_timeout**：默认 rollback journal 下写事务会锁住整个库文件
  （连读都阻塞），并发下 `database is locked`。新增 `app/db.py` 统一建引擎并挂
  `journal_mode=WAL` / `synchronous=NORMAL` / `busy_timeout=30000` / `foreign_keys=ON`
- **`impact` 路径枚举无上限 + 每条路径重建关系索引**：`max_hops=5`、度 30 时可达
  30^5 条简单路径，且 `_build_path` 每条路径都重建一次 `rel_index`（O(路径×关系)）。
  新增 `ERAHERM_GRAPH_MAX_PATHS`（默认 200）并把索引提到 BFS 之外
- **Qdrant 适配器缺 `get_meta` / `list_memory_ids`**（协议要求的两个方法）：导致
  `eraherm-reembed` 每次都全量重嵌、悬空向量清理恒为 0，且静默无报错。已补齐，
  并把 `dim` 写进 payload

### Changed（0.10.2 加固）

- 旧绝对分配置 `ERAHERM_RECALL_MIN_SCORE*` 在 relevance 模式下按比例折算（见上）；
  默认值下行为与之前完全一致，只有**非默认值**的语义被修正
- `POST /v1/memories`（以及 `/v1/memories/pin` 的新建分支）响应新增
  `persisted` / `drop_reason`；MCP `remember`（本地模式）同步返回这两个字段
- 日志 JSON 白名单补上 `detail` / `reason` / `user_id` / `memory_type` / `layer` / `memory_id`
  （此前这些 `extra` 字段会被静默丢弃）
- `app/memory/__init__.py` 改为惰性导入（PEP 562）：`app.memory.gate` 这类纯逻辑模块
  不再因为导入同包而把 sqlmodel 和整个 service 拉起来
- 依赖补上界：`redis<7` / `qdrant-client<2` / `neo4j<7` / `fastembed<2` /
  `apscheduler<4`（4.x 是不兼容重写）
- 补齐 `sdk/eraherm_memory/py.typed` 与 `evals/cases.json` 的 package-data
  （pyproject 声明了 `Typing :: Typed` 却没有 `py.typed`；`eraherm-eval` 装完缺 cases.json）
- `pyproject.toml` 的 `testpaths` 纳入 `hermes-plugin/tests`（25 个测试此前从不进 CI）

### Added（0.10.2 加固）

- `app/security.py`：纯标准库的安全原语（占位口令判定、恒定时间比较、暴露面守卫、
  文件名净化、路径收敛），`app/api/auth.py` 是它的 FastAPI 装配层
- `app/memory/gate.py`：把门禁/词法信号从 `service.py` 抽成无 IO 的纯模块，
  终于可以被便宜地单测
- `app/db.py`：SQLite 引擎单点构造 + pragma
- 测试：`tests/test_security.py`、`tests/test_recall_gate_mapping.py`、
  `tests/test_sqlite_pragmas.py`（均不依赖 sqlmodel）
- [ADR 0012](docs/adr/0012-api-auth-and-exposure-guard.md)

### Removed

- `RecallRequest.expand_graph`：文档承诺、模型里有字段，但**路由从不传、service 也不接收**
  —— 一个静默 no-op。要么实现要么删掉，这里选择删掉（pydantic 默认忽略多余字段，
  老客户端不会因此报错）

### Security（0.10.2 第二批）

- **敏感内容不再外发到远端 embedding**（[ADR 0014](docs/adr/0014-sensitive-content-remote-embedding.md)）：
  `ERAHERM_EMBEDDING_BACKEND=openai` 时，命中敏感词表的记忆/查询/摘要**不再静默外发**，
  而是返回 400 并说明两条出路（换本地 embedding，或显式
  `ERAHERM_SENSITIVE_REQUIRES_LOCAL_EMBEDDING=false` 接受风险）。
  之前 `.env.example` 宣称的「绝不出网」只覆盖 LLM 抽取/反射，**embedding 路径完全不经过词表** —— 承诺是假的
- `LLMSummarizer.summarize` 补上敏感守卫（LLM 压缩是第三个出网点，此前唯一漏掉的一处）；
  命中即回落本地启发式摘要
- `llm_reflection` 的探测面补上 `answer_text`：以前「correction_text 干净 + answer_text 带秘密」
  就能把敏感原文写进外部 LLM 的 prompt
- 新增进程内令牌桶限流（默认 600/min、burst 120、`/v1/health` 豁免，可关）：
  429 + `Retry-After`，键是 `X-API-Token` 的 sha256（不存原始密钥），桶数量有 LRU 上限防内存放大

### Added（0.10.2 第二批）

- **取代链**（[ADR 0013](docs/adr/0013-supersede-chain-and-relation-validity.md)）：
  `memories.version / superseded_by / superseded_at`。纠正后旧记忆被标记取代、
  **默认不再参与召回**（`ERAHERM_RECALL_EXCLUDE_SUPERSEDED`），但不删除 ——
  「纠正即进化」从"排序碰运气"变成结构保证，且可回滚
- **关系有效期**：`relations.valid_from / valid_to`。纠正时把被取代记忆带出来的边置为失效，
  `impact` 不再回答已经作废的依赖。`valid_to IS NULL` = 当前有效
- **整理的安全网**：`POST /v1/admin/consolidate {"dry_run": true}`（只统计不落库）、
  删除前自动 L3 归档（`ERAHERM_CONSOLIDATION_ARCHIVE_BEFORE_DELETE`，**归档失败即放弃删除**）、
  **跨进程整理锁**（`app/proclock.py`，多 worker 只有一个进程真正执行）
- **恢复接口**（此前完全没有回头路）：`POST /v1/admin/memories/restore`（恢复软删记忆并重建向量）、
  `POST /v1/admin/l3/restore`（从归档 JSON 补回缺失记忆）
- **向量检索前置过滤租户**：`EmbeddingRow.tenant_id` + `VectorStore.search(tenant_id=...)`。
  以前租户在 service 层「事后过滤」，别的租户会占满 top-k → 本租户明明有匹配却召回为空
- **所有权校验**：`pin_existing` / `adjust_weights` / `close_session` / L1 召回都带 `user_id` 校验
  （403），不再能用别人的 `memory_id` / `session_id` 操作别人的记忆
- 新测试：`tests/test_sensitive_policy.py`、`tests/test_migration_schema.py`（迁移×模型漂移守卫）、
  `tests/test_proclock.py`（17 例，含真实跨进程验证）、`tests/test_ratelimit.py`（26 例）
- 工程化脚手架：`Dockerfile` + `docker-compose.yml`（fail-fast 校验 `ERAHERM_API_TOKEN`）、
  `.dockerignore`、`docs/DEPLOYMENT_DOCKER.md`、Dependabot、发布 workflow、
  advisory lint workflow、`.pre-commit-config.yaml`、`pyproject.toml` 的 ruff/mypy/coverage 配置

### Changed（0.10.2 第二批）

- **迁移路径终于可信**：`0001_initial_schema` 从 `SQLModel.metadata.create_all()` 改为**显式 DDL**，
  新增幂等的 `0003`；CI 增加 `alembic upgrade head`（空库）与漂移测试。
  以前用"当前模型"建"历史表"，任何模型改动都不会让迁移失败
- 整理不再「摘要的摘要」：consolidation 产出的摘要不再参与下一轮聚类（语义逐轮漂移）
- 整理 embedding 改为分批（`batch_size=64`）并受 `ERAHERM_CONSOLIDATION_MAX_CANDIDATES` 限制
  （全对全相似度是 O(N²)，大库以前根本跑不完）；重排权重由逐行提交改为一个事务批量更新
- `apply_decay_deletions` 与召回路径**统一衰减语义**（此前直接用 `row.decay_lambda`，
  忽略命中增稳与半衰期护栏 —— 同一个库两套标准）
- `InMemorySessionCache` 加容量上限（`ERAHERM_SESSION_CACHE_MAX_SESSIONS`）；
  `InMemoryJobQueue` 加 `max_size`（溢出丢最旧并告警）且 lifespan 会 `stop()` 它（此前 daemon 线程泄漏）
- `RedisSessionCache.drop_lowest` 先 `llen` 再决定是否重写（此前每条 L1 写入都付一次 O(n) 往返）
- `/docs`、`/redoc`、`/openapi.json` 可用 `ERAHERM_ENABLE_DOCS=false` 关闭
- `L3ArchiveService` 支持 `restore`；`ArchiveStore` 端口新增 `read(uri)`（带归档根收敛校验）

### Fixed（0.10.2 第三批：真跑起来才发现的）

> 这一批全部来自**首次真正执行完整测试套件**（此前本机长期缺 sqlmodel、且沙箱封掉出站
> TLS，只能做静态审计）。跑出来 3 个失败，其中 2 个是**产品缺陷**。

- **一跑迁移就把进程里已存在的日志全部静默禁用**：`alembic/env.py` 调 `fileConfig()`
  时没传 `disable_existing_loggers=False`，而它默认会禁用 ini 里没列出的**所有已存在 logger**。
  本项目是"可嵌入内核"——宿主一旦以编程方式执行 `alembic upgrade`，宿主自己的日志
  以及我们的 `eraherm` logger 就会在那一刻被关掉，表现为"之后再也打不出任何日志"。
  测试侧的暴露方式：`test_migration_schema` 字母序在 `test_proclock` 之前，于是后者的
  `caplog` 收不到任何记录（单跑该文件却正常 —— 典型测试隔离问题）
- **`setup_logging()` 会清空宿主进程的 root handlers**（`root.handlers.clear()`）：
  对可嵌入内核同样是缺陷，会静默禁用宿主日志、也会清掉 pytest 的 caplog。
  改为只移除自己装过的那个 handler（用标记识别），幂等且不破坏宿主配置
- **迁移漂移测试自身写错**：只设 `Config` 的 `sqlalchemy.url` 不够 —— `alembic/env.py`
  里 `ERAHERM_DATABASE_URL` 优先，环境变量存在时迁移会打到别的库，
  测试自己的库始终为空。改用 `monkeypatch.setenv`（与既有 `test_phase5` 一致）
- **`mcp` 2.x 的报错会让人原地打转**：`mcp 2.x` 把 `FastMCP` 改名为 `MCPServer`，
  而 `create_mcp()` 只报 "MCP extra required: pip install ..."，已经装过的人会一直重复
  同一条命令。现在错误信息指出"需要 mcp 1.x / 2.x 不兼容"并附底层原因（两个 MCP server 都改了）

### Changed（0.10.2 第三批）

- `tests/test_phase8.py::test_mcp_tools_registered` 改为 `pytest.importorskip("mcp")`：
  `mcp` 是**可选** extra，没装时应该是 skip 而不是 fail —— 与本仓库 `test_phase6.py`
  对 `fakeredis` / `qdrant_client` 的既有写法一致（CI 装 `.[dev,mcp,scheduler]`，那里仍真跑）

### 验证（0.10.2 收口）

```
232 passed, 1 skipped in 12.61s
evals.harness: 16/16 passed, recall_at_k=1.0, mrr=1.0, p50≈7ms / p95≈29ms
alembic upgrade head: 0001 → 0002 → 0003 → 0004 全部执行成功
```
唯一 skip 的是 `requires_semantic_embedding`（需真语义嵌入，`ERAHERM_EVAL_SEMANTIC=1` 才跑）。

## [0.10.1] - 2026-08-25

### Fixed
- 图谱实体抽取质量：虚词/否定残留/碎片被抽成实体（「然后」「不」「不是 MySQL」「把两个完全不同的东西混在一起说了」）污染 impact。新增停用词表 + 实体质量门槛（长度/标点/否定前缀清理 `_clean_object`/`_is_valid_entity`），回归测试 `tests/test_graph_extractor_quality.py`
- MCP 转发 admin 端点 401：`app/mcp_server.py` 的 `_post` 不带 `X-Admin-Token` 头、`eraherm_mcp_server.py` 误用 `Authorization: Bearer`（后端只认 `X-Admin-Token`）——consolidate / reembed / l3 经 MCP 全部 401。统一改为 `X-Admin-Token`（值取 `ERAHERM_ADMIN_TOKEN`），新增回归测试 `test_mcp_admin_auth_header_is_x_admin_token`
- consolidate 摘要带 `【精华摘要·X】` 模板前缀：嵌入空间纯噪声，弱相关查询「服务器配置」0.501 命中摘要（验收探针 FAIL）。摘要改为干净事实句，回归 `test_summarizer_no_template_prefix`
- 文档同步：`docs/specs/API.md` 补 consolidate curl 示例（含 `X-Admin-Token`），`docs/MCP.md` 标注 consolidate 需服务端配置 `ERAHERM_ADMIN_TOKEN`

### Changed
- 生产启用夜间自动整理：`ERAHERM_CONSOLIDATION_ENABLED=true`（每天 03:00，防记忆再次堆积）

[0.10.1]: https://github.com/yangwenhua212/eraherm-memory/releases/tag/v0.10.1

## [0.10.0] - 2026-08-23

### Added
- `AgentMemory` 五能力封装：`learn()` / `remember()` / `reflect()` / `recall()` / `evolve()`（docs/HERMES_INTEGRATION.md §0）——面向 Host 的 Agent 能力化记忆 API，替代裸 HTTP 调用
- 演示：`examples/agent_memory.py`（remember → learn → recall → evolve → reflect 全链路）
- 回归测试：`tests/test_correct_evolve_regression.py`（纠正即进化：干净事实模板 + 无关不硬拉 pinned）

### Changed
- 许可从 AGPL-3.0 + 商业双许可改为 **MIT**（[ADR 0009](docs/adr/0009-mit-license.md)）：底层内核要扩散生态，上层完整产品（HxSync）仍保留 AGPL-3.0。
- 纠正反射 `_normalize_correction`：改为在关联记忆里做 wrong→correct 替换生成**干净事实句**（如「数据库使用 PostgreSQL」），不再用「正确事实：X（此前误为 Y）」模板——该模板拉低嵌入语义分，导致纠正后新事实被 recall 门禁挡掉（线上冒烟 FAIL）
- hermes-plugin：放弃上游 PR 路线，按用户级插件维护（README 更新）

### Fixed
- 纠正即进化回归：纠正后新事实无法排第一（嵌入分被模板拉低 0.244 + 零词法被 `min_score_no_lexical` 挡）。修复后新事实稳定第一（实测 0.619 [pinned] 压过旧事实）
- 上线检查表验收：补写生产用户身份记忆（含「用户名/名字」问法关键词，词法重叠生效）；清理 2 条无 user_id 孤儿测试残留

[0.10.0]: https://github.com/yangwenhua212/eraherm-memory/releases/tag/v0.10.0

## [0.9.1] - 2026-07-31

### Added
- 召回：`ERAHERM_RECALL_MIN_SCORE_NO_LEXICAL`（零词法重叠时抬高门槛，压制弱相关假阳性）
- 召回：CJK 词法改用字符 bigram；pinned 改为 `score + boost` 排序，取消无条件置顶（减轻多钉死串扰）
- 开源贡献入口：Issue 模板（docs / good first issue）、[GOOD_FIRST_ISSUES.md](docs/community/GOOD_FIRST_ISSUES.md)、CONTRIBUTING 补强

### Changed
- `correct_creates_pinned` 代码默认改为 `true`（与 `.env.example` 对齐）

[0.9.1]: https://github.com/yangwenhua212/eraherm-memory/releases/tag/v0.9.1

## [0.9.0] - 2026-07-29

### Added
- `fastembed` embedding 适配器（默认 `BAAI/bge-small-zh-v1.5` / 512 维），可选依赖 `eraherm-memory[fastembed]`
- 召回门禁 `ERAHERM_RECALL_MIN_SCORE`（默认 0.25）与请求字段 `min_score`
- 全量向量迁移：`eraherm-reembed` / `POST /v1/admin/reembed`（修复孤儿 `user_id`，不做双轨 hashing）
- Hermes 内置 Tools：`HermesMemoryTools` + `HermesMemoryBridge` 升入 SDK
- 自用回归脚本：`examples/correct_to_evolve.py`（纠正后新事实必须排第一）

### Changed
- README 首页：生态位（纠正即进化）、差异化、3 分钟 MCP 优先
- Hermes / ROADMAP：以「自用服务器上线检查表」为近期重心

[0.9.0]: https://github.com/yangwenhua212/eraherm-memory/releases/tag/v0.9.0

## [0.8.0] - 2026-07-29

### Added
- MCP Server（`remember` / `recall` / `impact` / `consolidate` / `health`）与 `mcp.json`
- 记忆整理 Consolidation：重要性重排、主题压缩、冲突淘汰、低权重遗忘
- 召回访问计数 `access_count` / `last_accessed_at`
- Hermes 集成指南与 `HermesMemoryBridge` 适配器示例
- SDK：`pin` / `consolidate` / `wait_feedback`
- 开源脚手架：CI、CONTRIBUTING、SECURITY、CHANGELOG、AGPL-3.0 + [COMMERCIAL.md](COMMERCIAL.md)

### Changed
- 文档写死：生产 / Hermes 须使用真实 embedding（禁止 hashing 上线）
- Demo：`/` 重定向到 `/demo/`；浏览器访问 `/v1/health` 返回可读 HTML 页
- 预警：近重复记忆不再误报 `conflict`；推荐为空时 Demo 提示去重原因

[0.8.0]: https://github.com/yangwenhua212/eraherm-memory/releases/tag/v0.8.0

## [0.7.0] - 2026-07-29

### Added
- 主动预警 `alerts[]`（技术栈切换等）
- Recall / Impact 旁路 `recommendations[]`

## [0.6.0] - 2026-07-29

### Added
- 可选 Redis / Qdrant / Neo4j Adapter
- 异步 Reflection、Python SDK `MemoryClient`
- 评测 harness、`examples/minimal_agent.py`、可选 LLM 抽取/反思

## [0.5.0] - 2026-07-29

### Added
- Alembic、L3 dump、JSON 日志、metrics、契约测试、Demo 反馈页签

## [0.4.0] - 2026-07-29

### Added
- `/feedback` + Heuristic Reflection + 权重更新

## [0.3.0] - 2026-07-29

### Added
- NetworkX 图谱、规则抽取、`/graph/*`、Demo

## [0.2.0] - 2026-07-29

### Added
- Embedding + VectorStore、语义召回、importance 启发式

## [0.1.0] - 2026-07-29

### Added
- FastAPI 骨架、SQLite、L1/L2、sessions / memories / recall / pin
