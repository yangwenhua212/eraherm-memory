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
- 换 embedding 后全量重嵌：`eraherm-reembed` 或 `POST /v1/admin/reembed`（修复孤儿 `user_id`，不做双轨兜底）  
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

### ⚠ 生产 Embedding（挂真 Agent 必读）

| 场景 | `ERAHERM_EMBEDDING_BACKEND` | 说明 |
|------|------------------------------|------|
| 单测 / 离线 Demo / CI | `hashing`（默认） | 零依赖，**语义召回弱**，中文尤甚 |
| **Hermes / 生产（本地中文）** | **`fastembed`** | `BAAI/bge-small-zh-v1.5`，512 维，无外网 API |
| **Hermes / 生产（云端）** | **`openai`（或兼容端点）** | 需 API Key；**禁止继续用 hashing** |

挂真 Agent 请在 `.env` **写死**为真实向量模型。本地中文推荐：

```bash
pip install 'eraherm-memory[fastembed]'
```

```env
ERAHERM_EMBEDDING_BACKEND=fastembed
ERAHERM_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
ERAHERM_EMBEDDING_DIM=512
```

或使用 OpenAI 兼容 API：

```env
ERAHERM_EMBEDDING_BACKEND=openai
ERAHERM_EMBEDDING_API_KEY=sk-...
ERAHERM_EMBEDDING_BASE_URL=https://api.openai.com/v1
ERAHERM_EMBEDDING_MODEL=text-embedding-3-small
ERAHERM_EMBEDDING_DIM=1536
```

也可用任意 OpenAI 兼容网关（本地 vLLM / Ollama 代理等）：改 `BASE_URL` + `MODEL` 即可，**不要**用 `hashing` 上线。  
换 embedding 后端后向量空间不兼容，需清空或重建向量库后再写入记忆。详见 [DEPLOYMENT.md](docs/DEPLOYMENT.md)、[HERMES_INTEGRATION.md](docs/HERMES_INTEGRATION.md)。

| 配置 | 默认 | 升级 |
|------|------|------|
| `ERAHERM_SESSION_CACHE_BACKEND` | `memory` | `redis` |
| `ERAHERM_VECTOR_BACKEND` | `sqlite` | `qdrant` |
| `ERAHERM_GRAPH_BACKEND` | `networkx` | `neo4j` |
| `ERAHERM_FEEDBACK_ASYNC` | `false` | `true` |
| `ERAHERM_PROACTIVE_ALERTS_ENABLED` | `true` | `false` 关闭预警 |
| `ERAHERM_PROACTIVE_RECOMMEND_ENABLED` | `true` | `false` 关闭推荐 |
| `ERAHERM_CONSOLIDATION_ENABLED` | `false` | `true` 进程内定时整理 |
| `ERAHERM_EMBEDDING_BACKEND` | `hashing`（仅开发） | **`fastembed` 或 `openai`（生产必选）** |
| `ERAHERM_RECALL_MIN_SCORE` | `0.25` | `0` 关闭门禁；生产可按语料调到 `0.3~0.4` |

- Demo：`http://localhost:8000/demo/`
- 指标：`GET /v1/metrics`
- L3：`python -m app.ops.l3_dump`
- 重嵌：`eraherm-reembed --orphan-user-id <uid>`（换 embedding 后）

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
from eraherm_memory import MemoryClient, HermesMemoryTools

with MemoryClient("http://127.0.0.1:8000") as client:
    tools = HermesMemoryTools(client, user_id="hermes:boss")
    # 挂进 Hermes：tools.openai_tools() + tools.dispatch(name, args)
    print(tools.dispatch("memory_remember", {"content": "项目用 FastAPI", "pinned": False}))
    print(tools.dispatch("memory_recall", {"query": "技术栈"}))
```

```bash
uvicorn app.main:app --port 8000
python examples/hermes_builtin_tools.py   # 内置 tools（推荐）
python examples/hermes_memory_adapter.py  # 主循环 Bridge
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
