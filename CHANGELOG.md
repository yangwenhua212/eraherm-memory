# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)（`0.x` 允许破坏性变更，见 [API 规范](docs/specs/API.md)）。

## [Unreleased]

### Changed
- 默认许可证由 MIT 调整为 **AGPL-3.0-only**，并增加双许可说明 [COMMERCIAL.md](COMMERCIAL.md)
- 源文件增加 SPDX / 版权头

### Added
- 开源脚手架：CI、CONTRIBUTING、SECURITY、CHANGELOG

## [0.8.0] - 2026-07-29

### Added
- MCP Server（`remember` / `recall` / `impact` / `consolidate` / `health`）与 `mcp.json`
- 记忆整理 Consolidation：重要性重排、主题压缩、冲突淘汰、低权重遗忘
- 召回访问计数 `access_count` / `last_accessed_at`
- Hermes 集成指南与 `HermesMemoryBridge` 适配器示例
- SDK：`pin` / `consolidate` / `wait_feedback`

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

<!-- 远程仓库就绪后，可按 Keep a Changelog 补全 compare/tag 链接 -->
