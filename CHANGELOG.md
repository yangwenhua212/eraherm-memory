# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)（`0.x` 允许破坏性变更，见 [API 规范](docs/specs/API.md)）。

## [Unreleased]

### Fixed

- **召回门禁量纲错配：记忆超过约 28 天后全库召回为空**（2026-10-08 生产实测）。`score = base × (0.15+0.85·rel)` 且 `base` 含 `exp(-decay_lambda·age)`，门禁却卡绝对分（0.25/0.38）——**分数上限等于 `base`**，`age > 27.7 天` 时即使 `relevance=1.0` 也过不了门禁。生产库 9 条活跃记忆 `base` 全在 0.025~0.099，recall 对任何查询（含同义换词问法）都返回空；线上用户唯一能过门禁的是一条 3 天前的 2920 字镜像长文，导致不同查询返回同一条。修复见 [ADR 0010](docs/adr/0010-recall-gate-relevance.md)：门禁改判**相关性**（`recall_rel_min=0.18` / `recall_rel_min_no_lexical=0.55`），`score` 退居排序。回归测试 `tests/test_recall_gate_age_decoupled.py`
- **pinned 记忆参与年龄衰减**：与「钉死记忆不因衰减删除」的承诺矛盾——没被删，但已召不回。改为 `recall_pinned_no_decay=true`（pinned 走 `decay=0`）
- **长文「大杂烩」绕过词法门禁**：一条几千字的记忆与几乎所有查询都有词法重叠。词法信号改为按内容长度**二次折扣**（`recall_lexical_len_norm=300`，折扣后低于 `_LEX_EVIDENCE_MIN=0.02` 视为零词法，走从严门禁）。实测把 2920 字镜像长文从「所有查询都命中」压回门禁之下

### Changed

- **二段重排：排序由相关性主导**。排序键从 `score`（=base×rel）改为 `relevance + 0.2×base + pinned_boost`，否则又长又 pinned 的记忆会压过更相关的短记忆（实测：更相关的短记忆被那条又长又 pinned 的定案记忆挤到第二）
- `recall_gate_mode` 新增（默认 `relevance`）。旧绝对分门禁保留为 `recall_gate_mode=score` 回滚开关；旧配置 `recall_min_score` / `recall_min_score_no_lexical` 在 `relevance` 模式下按 `rel = (score-0.15)/0.85` 换算，严格度语义不变；`min_score<=0` 仍表示关闭门禁

### Added

- `/v1/recall` 响应项新增诊断字段 `relevance` / `lexical` / `vector_sim` / `base`（排查「为什么这条召回不到」不必在客户端重算）
- 主动感知看门狗（phase 9）：`POST /v1/admin/watchdog` 巡检记忆库，产出「值得说的事」——倒计时事件（D-7/D-3/D-1/当天）、被遗忘的高价值记忆（importance≥0.8 且从未被 recall）、健康信号。**零 LLM / 零外部 API**（SQLite + 正则 + 标准库）。敏感记忆（秘密/红线类）绝不进入推送。回归测试 `tests/test_watchdog.py`（5 例）
- 生产启用 LLM 图谱抽取/反射（`ERAHERM_LLM_BACKEND=openai`，DeepSeek `deepseek-chat`）：规则抽取器抽不出的人物/事实关系（「用户 related_to 合作方」）现在由 LLM 抽取，图谱支柱真正兑现
- **敏感内容防护**（`app/sensitive.py`）：LLM 抽取/反射的输入命中敏感词（秘密/红线/不要告诉/不能提 等）→ 直接走本地规则/heuristic，**内容绝不出网**。watchdog 的敏感推送过滤改复用同一词表（一份定义，三处生效）。回归测试 `tests/test_llm_sensitive_guard.py`（10 例）

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
