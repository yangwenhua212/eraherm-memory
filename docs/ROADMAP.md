# 路线图

> 原则：每个阶段结束都有可演示增量；不一次做完「大而全」。

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

## 阶段 8+ 后续（按需）

| 触发条件 | 动作 |
|----------|------|
| 换 embedding / 维度 | `eraherm-reembed` 全量覆盖（已实现，禁止双轨） |
| Hermes 深集成 | `HermesMemoryTools` 内置 tool（已实现，替代 curl） |
| 多实例 + 可靠异步 | JobQueue → ARQ/Redis；Consolidation → Celery Beat |
| L3 多机 | ArchiveStore → S3 |
| 主库并发 | MemoryRepo → Postgres |
| 冲突判定要更准 | 可选 LLM 冲突判定 Adapter |
| MCP 远程共享 | Streamable HTTP transport |

---

## 版本号建议

| 版本 | 含义 |
|------|------|
| 0.x | 内核打磨，允许破坏性变更（文档同步） |
| 1.0 | API `/v1` 稳定，有迁移承诺 |
| 1.x | 新增 Adapter / 策略，向后兼容 |

---

## 近期下一步

对 **Hermes 挂载**：见 [HERMES_INTEGRATION.md](HERMES_INTEGRATION.md) 与 `examples/hermes_memory_adapter.py`。  
开源脚手架已就绪（**AGPL-3.0** + [COMMERCIAL.md](../COMMERCIAL.md) / CI / CONTRIBUTING）。  
远程仓库：https://github.com/yangwenhua212/eraherm-memory
