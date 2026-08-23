# EraHerm-Memory

[![CI](https://github.com/yangwenhua212/eraherm-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/yangwenhua212/eraherm-memory/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**可嵌入的记忆内核**——专治 Agent「说过就忘、纠正了还不改」。  
不是又一个 RAG 全家桶，也不是完整 Agent 框架。

> 仓库：https://github.com/yangwenhua212/eraherm-memory  
> **许可**：**[MIT](LICENSE)**——可自由使用、修改、商用（保留版权声明即可）。

---

## 生态位（30 秒）

> EraHerm-Memory = **Hermes 的长期记忆层** —— 记准 · 推通 · 进化  
> 主打打磨的是 **「纠正即进化」**：用户说「不对，应该是 X」→ 钉死新事实 → 下次同类问题优先新版本。  
> 开发顺序：**记忆内核稳定 → Hermes 会用 Memory → 再接入 Cursor / 手机 / Web 等工具端**。Cursor 只是一个工具接入端，记忆先服务核心 Agent（Hermes）。

| 我们坚持 | 我们不做 |
|----------|----------|
| 小而美的 **Memory Kernel**，嵌入任意 Host | 规划器 / 工具总线 / 聊天 UI 全家桶 |
| 标准接口：**MCP**、HTTP、Python SDK | 绑死某一家 Agent 产品 |
| 决策写进 [ADR](docs/adr/README.md)，可追溯可推翻 | 「口口相传」的架构 |

故事素材：为何内核而非框架 → [ADR-0001](docs/adr/0001-kernel-not-full-agent.md)；为何 SQLite 优先 → [ADR-0002](docs/adr/0002-sqlite-first-storage.md)；为何先轻量图 → [ADR-0003](docs/adr/0003-lightweight-graph-before-neo4j.md)。

---

## 和「大而全记忆项目」差在哪

| | 常见记忆 / RAG 组件 | **EraHerm-Memory** |
|--|---------------------|---------------------|
| 定位 | 向量库 + 检索，或平台功能的一环 | **可替换的记忆内核**（Port/Adapter） |
| 纠正 | 常常只追加一条新向量，旧错仍在抢排名 | **feedback → Reflection → pinned**，旧版让路 |
| 结构问题 | 「改 A 会影响谁」常靠提示词硬猜 | **轻量图谱** `impact`（可升 Neo4j） |
| 集成 | 各家私有 SDK | **MCP 即插即用** + HTTP + Hermes Tools |
| 演进 | 功能清单越堆越长 | 三支柱做深：L1/L2/L3、图、反馈闭环 |

一句话验收：**纠正后，同义再问，必须优先新事实。**  
（`python -m evals.harness` / Demo 里可走通。）

---

## 🔬 实测：纠正信息不做模板包装

「纠正即进化」最容易被做坏的一步：把用户的纠正包成「正确事实：X（此前误为 Y）」再写入。这个模板在语义空间里是纯噪声——**0.9.1 线上冒烟就死在这**（真实复现数据）：

| 步骤 | 内容 | 嵌入分（对「我们数据库用什么」） |
|---|---|---|
| 用户纠正 | 应该是 PostgreSQL 不是 MySQL | — |
| ❌ 模板包装写入 | 正确事实：PostgreSQL（此前误为 MySQL） | **0.244**，零词法重叠 → 被 `min_score_no_lexical=0.38` 挡掉，新事实召不回 |
| ✅ wrong→correct 替换写入 | 数据库使用 PostgreSQL | **0.619**，top1 压过旧事实「数据库使用 MySQL」 |

修复不是在调参，是**在关联记忆里做 wrong→correct 替换**，直接生成干净事实句。从此「纠正即进化」是数据结构层面的版本管理，不是 Prompt 魔法。

### 为什么「调高门禁」是伪方案

经验上容易想到把 `ERAHERM_RECALL_MIN_SCORE` 从 0.25 调到 0.3~0.4 来压噪音——实测数据否决：

- 「我的名字叫啥」对身份记忆 **0.386**，正好卡在 0.38 线上：调高门禁 = 误杀真实问法
- 「你好呀」对身份记忆 **0.359**，比「用户名是什么」的 **0.349** 还高：纯语义分区分不了「问名字」和「打招呼」，豁免 pinned 一样串扰

正解是**内容工程**：身份记忆补上常见问法关键词（「用户名」「名字」），让词法重叠自然生效，门禁一行不用动：

| 问法 | 修复前 | 修复后 |
|---|---|---|
| 用户名是什么 | ❌ 未召回 | ✅ 0.525 |
| 我的名字叫啥 | ❌ 未召回 | ✅ 0.386 |
| 今晚月球几点月圆 | — | ✅ 不硬拉（空） |

**结论：用数据的丰富度适配工具，而不是削足适履调参数。** 回归测试：`tests/test_correct_evolve_regression.py`。

---

## 3 分钟：MCP 挂上 Cursor / Claude

最推荐的第一印象路径——**不写业务代码，先当内置记忆工具用**。

```bash
git clone https://github.com/yangwenhua212/eraherm-memory.git
cd eraherm-memory
python -m pip install -e ".[mcp]"
copy .env.example .env          # Windows；Unix: cp .env.example .env
```

把仓库根目录 [`mcp.json`](mcp.json) 合并进 Cursor / Claude Desktop 的 MCP 配置（改 `cwd` 为你的本地路径）。然后：

```bash
# 可选：先起 HTTP Demo 看闭环
uvicorn app.main:app --reload --port 8000
# 浏览器打开 http://localhost:8000/demo/
```

在对话里直接让模型调用：

| Tool | 干什么 |
|------|--------|
| `remember` | 存长期事实 |
| `recall` | 语义召回 |
| `impact` | 「改 X 会影响谁」 |
| `consolidate` | 整理压缩（运维向） |

完整说明：[docs/MCP.md](docs/MCP.md)。

**挂真 Agent / 对外演示语义召回时**，把 MCP `env` 改成真实 embedding（禁止长期 `hashing`）：

```bash
pip install 'eraherm-memory[fastembed]'
```

```env
ERAHERM_EMBEDDING_BACKEND=fastembed
ERAHERM_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
ERAHERM_EMBEDDING_DIM=512
ERAHERM_RECALL_MIN_SCORE=0.25
```

---

## Cursor 适配器（独立 stdio，不经 Hermes）

想让 Cursor 直接读写 EraHerm 记忆、不经过 Hermes？用独立的 [`eraherm_mcp_server.py`](eraherm_mcp_server.py)：

- **零依赖**：不加载 embedding 模型、不起本地容器，纯 HTTP 转发到 `ERAHERM_API_URL`（模型在服务端）
- **工具带 `eraherm_` 前缀**，避免与 Cursor 里其它 MCP 冲突
- 工具：`eraherm_remember` / `eraherm_recall` / `eraherm_evolve`（纠正即进化）/ `eraherm_impact` / `eraherm_consolidate` / `eraherm_health`

在 Cursor 的 `mcp.json` 里加（参考 [`mcp.cursor.json`](mcp.cursor.json)）：

```json
{
  "mcpServers": {
    "eraherm": {
      "command": "python",
      "args": ["eraherm_mcp_server.py"],
      "cwd": "D:/path/to/eraherm-memory",
      "env": {
        "ERAHERM_API_URL": "http://127.0.0.1:8000",
        "ERAHERM_USER_ID": "cursor:laoda"
      }
    }
  }
}
```

然后直接自然语言触发：

| 你说 | 背后调用 |
|------|----------|
| 「记住：项目部署在 OVH」 | `eraherm_remember` |
| 「我之前记过这个项目的什么？」 | `eraherm_recall` |
| 「不对，应该是 X 不是 Y」 | `eraherm_evolve`（纠正即进化） |
| 「改 MCP 配置会影响谁？」 | `eraherm_impact` |

自验脚本（需服务在跑）：`python examples/cursor_mcp_check.py`。

> `eraherm_consolidate` 需要管理员权限：配 `ERAHERM_ADMIN_TOKEN` 环境变量。

---

## 三大支柱（只做这三件事）

| 支柱 | 解决什么 |
|------|----------|
| **分层记忆 L1/L2/L3** | 会话热数据 / 长期事实 / 冷归档，关键钉死不丢 |
| **轻量知识图谱** | 结构推理：「改 A 会影响谁」 |
| **反馈闭环** | 点赞 / 点踩 / **纠正** → Reflection → 写回并优先 |

当前版本 **0.10.0**：MCP、整理压缩、`eraherm-reembed`、Hermes 内置 Tools、召回假阳性/多 pinned 修复。详见 [CHANGELOG](CHANGELOG.md)、[ROADMAP](docs/ROADMAP.md)。

想贡献？请读 [CONTRIBUTING.md](CONTRIBUTING.md)，Issues 筛选标签 **`good first issue`**。

---

## HTTP / SDK 快速开始

```bash
python -m pip install -e ".[dev,mcp,scheduler]"
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

```python
from eraherm_memory import MemoryClient, HermesMemoryTools

with MemoryClient("http://127.0.0.1:8000") as client:
    tools = HermesMemoryTools(client, user_id="hermes:boss")
    tools.dispatch("memory_remember", {"content": "数据库用 PostgreSQL", "pinned": True})
    print(tools.dispatch("memory_recall", {"query": "我们用什么库"}))
```

- Hermes 深集成（替代 curl）：[HERMES_INTEGRATION.md](docs/HERMES_INTEGRATION.md)  
- 示例：`python examples/hermes_builtin_tools.py`  
- 纠正闭环自测：`python examples/correct_to_evolve.py`  
- 换 embedding 后重建向量：`eraherm-reembed --orphan-user-id <uid>`（[DEPLOYMENT.md §3.1](docs/DEPLOYMENT.md)）  
- 评测：`python -m evals.harness` · 测试：`python -m pytest -q`

### 生产配置要点

| 配置 | 开发默认 | 生产 / Hermes |
|------|----------|----------------|
| `ERAHERM_EMBEDDING_BACKEND` | `hashing` | **`fastembed` 或 `openai`** |
| `ERAHERM_RECALL_MIN_SCORE` | `0.25` | 可调 `0.3~0.4`；`0` 关闭 |
| `ERAHERM_RECALL_MIN_SCORE_NO_LEXICAL` | `0.38` | 零词法命中时的更高门槛 |
| `ERAHERM_CORRECT_CREATES_PINNED` | `true` | `false` 纠正不钉死 |
| 会话 / 向量 / 图 | memory / sqlite / networkx | 按需 Redis / Qdrant / Neo4j |

完整对照：[DEPLOYMENT.md](docs/DEPLOYMENT.md)。

---

## 文档导航

| 想了解… | 去读 |
|---------|------|
| 设计哲学与生命周期 | [技术设计](docs/TECHNICAL_DESIGN.md) |
| **为什么这样选** | [ADR 索引](docs/adr/README.md) |
| MCP / Hermes / 部署 | [MCP](docs/MCP.md) · [Hermes](docs/HERMES_INTEGRATION.md) · [部署](docs/DEPLOYMENT.md) |
| 契约与扩展 | [API](docs/specs/API.md) · [数据模型](docs/specs/DATA_MODEL.md) · [扩展](docs/specs/EXTENSION.md) · [政策](docs/specs/POLICIES.md) |
| 参与与许可 | [CONTRIBUTING](CONTRIBUTING.md) · [Good First Issues 草稿](docs/community/GOOD_FIRST_ISSUES.md) · [SECURITY](SECURITY.md) |

---

## 许可

**[MIT](LICENSE)** © 2026 杨文华 (Wenhua Yang)。

- 可自由使用、修改、分发、商用，只需保留版权声明与许可声明（MIT 全文见 [LICENSE](LICENSE)）。
- MIT 不是「放弃著作权」：你仍然保留署名权与版权声明要求。
- 注意：**eraherm-memory 是 MIT**，但上层完整产品（如 **HxSync**）仍保留 **[AGPL-3.0](https://github.com/yangwenhua212/hxsync/blob/main/LICENSE)** 保护。两者不冲突——底层模块要扩散，完整产品要守住。

欢迎开 Issue / PR：先跑通「纠正后再召回」，再谈功能清单。
