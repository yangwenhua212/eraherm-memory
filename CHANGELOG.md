# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)（`0.x` 允许破坏性变更，见 [API 规范](docs/specs/API.md)）。

## [Unreleased]

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
