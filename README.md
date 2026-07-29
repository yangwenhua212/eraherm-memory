# EraHerm-Memory

[![CI](https://github.com/yangwenhua212/eraherm-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/yangwenhua212/eraherm-memory/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

可嵌入任意 Agent 的**记忆内核**：分层记忆、知识图谱、反馈进化。  
不追求大而全，只做一件事——让 Agent **记得住、推得出、越用越懂你**。

> 仓库：https://github.com/yangwenhua212/eraherm-memory  
> **许可**：默认 [AGPL-3.0](LICENSE)；闭源商用见 [COMMERCIAL.md](COMMERCIAL.md)。

## 一句话

**EraHerm-Memory = 分层记忆（记准）+ 轻量图谱（推通）+ 反馈反思（进化）**

## 三大支柱

| 支柱 | 解决什么 |
|------|----------|
| 分层记忆 L1/L2/L3 | 防上下文爆炸，关键信息永不丢 |
| 知识图谱 | 「改 A 会影响谁」类结构推理 |
| 反馈闭环 | 纠正 → Reflection → 写回，越用越懂 |

## 文档导航

| 文档 | 说明 |
|------|------|
| [技术设计](docs/TECHNICAL_DESIGN.md) | 架构、模块边界、生命周期（主文档） |
| [数据模型](docs/specs/DATA_MODEL.md) | 表结构、字段、不变量 |
| [API 规范](docs/specs/API.md) | HTTP 接口契约 |
| [MCP 接入](docs/MCP.md) | Cursor / Claude Desktop 挂载 |
| [Hermes 集成](docs/HERMES_INTEGRATION.md) | Host Agent 主循环怎么接记忆 |
| [扩展指南](docs/specs/EXTENSION.md) | 插件点、替换存储/模型的方式 |
| [政策说明](docs/specs/POLICIES.md) | 衰减、晋升、Reflection 阈值等语义 |
| [路线图](docs/ROADMAP.md) | MVP → 长期迭代阶段 |
| [部署对照](docs/DEPLOYMENT.md) | 默认单机 vs 生产按需升级 |
| [贡献指南](CONTRIBUTING.md) | 开发环境、PR 约定 |
| [变更日志](CHANGELOG.md) | 版本记录 |
| [安全说明](SECURITY.md) | 漏洞上报与信任边界 |
| [商业许可](COMMERCIAL.md) | AGPL 之外的闭源授权 |
| [ADR 索引](docs/adr/README.md) | 架构决策记录，保证演进可追溯 |

## 当前状态

✅ **阶段 8（0.8.0）— MCP 标准化 + 遗忘/压缩**  
- MCP Server：`python -m app.mcp_server`（见 [docs/MCP.md](docs/MCP.md)、`mcp.json`）  
- 记忆整理：重要性重排 / 摘要压缩 / 冲突淘汰（`eraherm-consolidate` 或 `POST /v1/admin/consolidate`）  
- 可选夜间调度：`ERAHERM_CONSOLIDATION_ENABLED=true` + `pip install '.[scheduler]'`  

## 快速开始

```bash
python -m pip install -e ".[dev,mcp,scheduler]"
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

MCP（Cursor / Claude Desktop）：

```bash
python -m app.mcp_server
```

配置见仓库根目录 [`mcp.json`](mcp.json)。

| 配置 | 默认 | 升级 |
|------|------|------|
| `ERAHERM_SESSION_CACHE_BACKEND` | `memory` | `redis` |
| `ERAHERM_VECTOR_BACKEND` | `sqlite` | `qdrant` |
| `ERAHERM_GRAPH_BACKEND` | `networkx` | `neo4j` |
| `ERAHERM_FEEDBACK_ASYNC` | `false` | `true` |
| `ERAHERM_PROACTIVE_ALERTS_ENABLED` | `true` | `false` 关闭预警 |
| `ERAHERM_PROACTIVE_RECOMMEND_ENABLED` | `true` | `false` 关闭推荐 |
| `ERAHERM_CONSOLIDATION_ENABLED` | `false` | `true` 进程内定时整理 |

- Demo：`http://localhost:8000/demo/`
- 指标：`GET /v1/metrics`
- L3：`python -m app.ops.l3_dump`

### 评测与样例

```bash
python -m evals.harness
python examples/minimal_agent.py
```

可选 LLM（抽取 + Reflection，失败回落规则/启发式）：

```env
ERAHERM_LLM_BACKEND=openai
ERAHERM_LLM_API_KEY=sk-...
```

### Python SDK

```python
from eraherm_memory import MemoryClient

with MemoryClient("http://127.0.0.1:8000") as client:
    client.remember(content="项目用 FastAPI", user_id="u1", importance=0.9)
    print(client.recall(user_id="u1", query="技术栈"))
```

Hermes 主循环适配器（策略在 Host）：

```bash
uvicorn app.main:app --port 8000
python examples/hermes_memory_adapter.py
```

详见 [Hermes 集成指南](docs/HERMES_INTEGRATION.md)。

```bash
python -m pytest -q
```

## 许可

默认 **[AGPL-3.0](LICENSE)** © EraHerm-Memory Authors。

- 开源使用（含网络服务须提供对应源码）：遵守 AGPL-3.0 即可免费使用  
- 闭源 / 专有商用：见 **[COMMERCIAL.md](COMMERCIAL.md)**  

参与贡献见 [CONTRIBUTING.md](CONTRIBUTING.md)；安全问题见 [SECURITY.md](SECURITY.md)。
