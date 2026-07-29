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

## 8. 接入检查清单

- [ ] `user_id` 跨会话稳定  
- [ ] 已注册 `HermesMemoryTools.openai_tools()` + `dispatch`（不再手写 curl）  
- [ ] 线程结束会 `end_session`  
- [ ] UI 纠正走 `memory_correct`  
- [ ] 生产 embedding 不是 `hashing`  
- [ ] 旧向量已 `eraherm-reembed`  

---

## 9. 把 SDK 搬进 Hermes 仓库

1. `pip install eraherm-memory`（或 editable path）。  
2. 只依赖 `eraherm_memory.*`，不要 import `app.*`。  
3. 契约测试：`memory_remember` → `memory_recall` → `memory_correct` → 再 `memory_recall`。  
4. 多用户：每个账号一个 `HermesMemoryTools(..., user_id=...)`。
