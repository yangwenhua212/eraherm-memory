# Hermes 集成指南

> 目标：把 EraHerm-Memory 嵌进 **Hermes Agent** 主循环，而不是把 Hermes 重写成记忆框架。  
> SDK：`from eraherm_memory import MemoryClient, HermesMemoryTools, HermesMemoryBridge`  
> 示例：[`examples/hermes_builtin_tools.py`](../examples/hermes_builtin_tools.py)、[`examples/hermes_memory_adapter.py`](../examples/hermes_memory_adapter.py)

---

## 1. 边界

| 归属 | 职责 |
|------|------|
| **EraHerm-Memory** | 存 / 召回 / 图影响 / 反馈反思 / 整理 |
| **Hermes** | 规划、工具、对话 UI；决定**何时**调用记忆、**记什么** |

内核不会自动从整段 chat 抽记忆。策略在 Host。

---

## 2. 推荐接入方式：内置 Tools（替代 curl）

把记忆注册成 Hermes **与其它 tool 同级的内置函数**；`user_id` / `session_id` 在构造时绑定，LLM 只传 `query` / `content`。

```python
from eraherm_memory import MemoryClient, HermesMemoryTools

client = MemoryClient("http://127.0.0.1:8000")  # 或同机 sidecar URL
tools = HermesMemoryTools(client, user_id="hermes:boss")  # 稳定 user_id

# ① 把 OpenAI 风格 schema 挂进 Hermes tool registry
hermes.register_tools(tools.openai_tools())

# ② 模型发出 tool_call 时：
#    name="memory_recall", arguments={"query": "老大喜欢吃什么"}
result_text = tools.dispatch(name, arguments)  # JSON 字符串，塞回 tool message
```

| Tool | 作用 |
|------|------|
| `memory_recall` | 语义召回（换词也能中） |
| `memory_remember` | 写入长期事实 |
| `memory_pin` | 钉死身份/硬偏好 |
| `memory_correct` | 用户纠正 → feedback |
| `memory_impact` | 「改 X 会影响谁」 |

演示：

```bash
uvicorn app.main:app --port 8000
python examples/hermes_builtin_tools.py --base-url http://127.0.0.1:8000
```

**不要再**让 Hermes 每轮手写 `curl POST /v1/recall`——费 tokens、易漏 `user_id`、难测试。

---

## 3. 身份与会话映射（必须先定）

| Hermes 概念 | EraHerm 字段 | 建议 |
|-------------|--------------|------|
| 登录用户 / 工作区主人 | `user_id` | 稳定字符串，例如 `hermes:{account_id}` |
| 组织 / 多租户 | `tenant_id` | 可选；有多工作区再启用 |
| 一次对话线程 | `session_id` | `HermesMemoryTools` 默认自动 `create_session`；结束调 `tools.end_session()` |

错误示范：每条消息换一个 `user_id` → 永远召不回。唐美女上线时用另一个 `user_id` 实例化一套 `HermesMemoryTools` 即可隔离。

---

## 4. 可选：主循环 Bridge（自动注入 + 启发式写入）

若不想完全交给 LLM 决定何时 recall，用 `HermesMemoryBridge`：

```text
on_thread_start:
  bridge = HermesMemoryBridge(client, user_id=...)

on_user_message(text):
  ctx = bridge.before_turn(text)
  system += bridge.build_system_suffix(ctx)
  answer = hermes_llm_and_tools(...)   # 仍可同时挂 HermesMemoryTools
  bridge.after_turn(text, answer, answer_id=..., user_feedback=...)

on_thread_end:
  bridge.end_session()
```

`Bridge` = 策略注入；`Tools` = 模型可调用。可并存：Bridge 保证每轮有上下文，Tools 负责显式「记住 / 纠正」。

---

## 5. 记什么 / 不记什么

| 写入 | 条件 |
|------|------|
| `memory_remember` | 喜好、技术栈、身份、明确「请记住」 |
| `memory_pin` | 身份 / 硬性偏好 |
| `memory_correct` | 用户说「不对 / 应该是…」 |
| 不写 | 纯闲聊、一次性工具日志、超长粘贴 |

---

## 6. 能力接线表

| Hermes 场景 | 用法 |
|-------------|------|
| 答眼前查记忆 | tool `memory_recall` 或 Bridge `before_turn` |
| 「改 X 会影响谁」 | tool `memory_impact` |
| 钉死偏好 | tool `memory_pin` |
| 用户纠正 | tool `memory_correct` |
| 技术栈切换弹窗 | `memory_remember` 返回的 `alerts[]` |
| 夜间去膨胀 | `eraherm-consolidate` / admin API |
| IDE 侧挂载 | MCP：见 [MCP.md](MCP.md)（与 Hermes 进程可并存） |
| 换 embedding 后 | `eraherm-reembed --orphan-user-id ...` |

---

## 7. 部署建议（挂 Hermes）— Embedding 写死

**硬性约定：Hermes 生产路径禁止 `hashing`。**

```env
ERAHERM_EMBEDDING_BACKEND=fastembed
ERAHERM_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
ERAHERM_EMBEDDING_DIM=512
ERAHERM_RECALL_MIN_SCORE=0.25
```

换 embedding 后：

```bash
eraherm-reembed --orphan-user-id hermes:boss
```

详见 [DEPLOYMENT.md §3.1](DEPLOYMENT.md)。

---

## 8. 服务器上线检查表（自用 Hermes，按序勾）

> 目前只有你在用时，**先跑完这张表**，比开源宣传重要。稳定 `user_id` 示例：`hermes:boss`。

### A. 代码与依赖

- [ ] `git pull origin main`（至少含 Tools / reembed / min_score 的提交）
- [ ] `pip install -e '.[fastembed]'`（生产语义召回）
- [ ] 重启 uvicorn / 记忆服务进程

### B. `.env`（禁止 hashing 上线）

```env
ERAHERM_EMBEDDING_BACKEND=fastembed
ERAHERM_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
ERAHERM_EMBEDDING_DIM=512
ERAHERM_RECALL_MIN_SCORE=0.25
```

- [ ] 已按上面写死并重启生效  
- [ ] `GET /v1/health` 正常

### C. 旧向量迁移

```bash
eraherm-reembed --dry-run --orphan-user-id hermes:boss
eraherm-reembed --orphan-user-id hermes:boss
```

- [ ] dry-run 报告无 ERROR  
- [ ] 正式 reembed 完成；再问「老大叫什么」等旧事实能召回

### D. 内置 Tools（停 curl）

```python
from eraherm_memory import MemoryClient, HermesMemoryTools

tools = HermesMemoryTools(MemoryClient("http://127.0.0.1:8000"), user_id="hermes:boss")
# hermes.register_tools(tools.openai_tools())
# tool_call → tools.dispatch(name, arguments)
```

- [ ] `user_id` 跨会话稳定（不要每轮换）  
- [ ] 已注册 `openai_tools()` + `dispatch`  
- [ ] 线程结束调用 `tools.end_session()`  
- [ ] 纠正走 `memory_correct`（或 Bridge `after_turn` feedback）

### E. 纠正闭环冒烟（你自己验）

- [ ] 换词能召回已有喜好/身份  
- [ ] 故意答错 → 纠正 → 同义再问 → **新事实排第一**  
- [ ] 完全不相关的问题：`items` 为空或低于门禁（不硬拉）  
- [ ] 弱相关（如「服务器配置」）不该硬蹭到数据库偏好  
- [ ] 多条 pinned（身份/库/口味）问「用户名」应命中身份，而非别的钉死项  

本地一键脚本（仓库内）：

```bash
uvicorn app.main:app --port 8000
python examples/correct_to_evolve.py --base-url http://127.0.0.1:8000
```

相关配置（0.9+）：

```env
ERAHERM_RECALL_MIN_SCORE=0.25
ERAHERM_RECALL_MIN_SCORE_NO_LEXICAL=0.38
ERAHERM_RECALL_PINNED_SCORE_BOOST=0.05
ERAHERM_CORRECT_CREATES_PINNED=true
```

---

## 9. 把 SDK 搬进 Hermes 仓库

1. `pip install eraherm-memory`（或 editable path）。  
2. 只依赖 `eraherm_memory.*`，不要 import `app.*`。  
3. 契约测试：`memory_remember` → `memory_recall` → `memory_correct` → 再 `memory_recall`。  
4. 第二个使用者（如唐美女）上线时：再开一个 `HermesMemoryTools(..., user_id=...)` 隔离即可。
