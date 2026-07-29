# ADR 0004：用 Port/Adapter 保证可替换后端

- 状态：Accepted
- 日期：2026-07-29

## 上下文

项目明确要「可扩展、可长期迭代」。若业务代码直接绑定 OpenAI/Chroma/Neo4j，替换成本会指数上升。

## 决策

- 领域模块只依赖 `app/ports`。
- 具体 SDK 放在 `app/adapters`，于组合根注入。
- 关键 Port 必须有 Fake，便于测试与 CI。

## 后果

- 正面：换 Redis/Qdrant/Neo4j/本地模型时改配置与 Adapter。
- 负面：前期样板代码略多；禁止「图省事」在路由里直连 SDK。
