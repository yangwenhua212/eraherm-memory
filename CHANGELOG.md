# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)（`0.x` 允许破坏性变更，见 [API 规范](docs/specs/API.md)）。

## [Unreleased]

### Fixed
- MCP 转发 admin 端点 401：`app/mcp_server.py` 的 `_post` 不带 `X-Admin-Token` 头、`eraherm_mcp_server.py` 误用 `Authorization: Bearer`（后端只认 `X-Admin-Token`）——consolidate / reembed / l3 经 MCP 全部 401。统一改为 `X-Admin-Token`（值取 `ERAHERM_ADMIN_TOKEN`），新增回归测试 `test_mcp_admin_auth_header_is_x_admin_token`
- 文档同步：`docs/specs/API.md` 补 consolidate curl 示例（含 `X-Admin-Token`），`docs/MCP.md` 标注 consolidate 需服务端配置 `ERAHERM_ADMIN_TOKEN`

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
- 上线检查表验收：补写 xiaoxian 身份记忆（含「用户名/名字」问法关键词，词法重叠生效）；清理 2 条无 user_id 孤儿测试残留

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
