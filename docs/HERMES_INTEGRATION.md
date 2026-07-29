# Hermes 集成指南

> 目标：把 EraHerm-Memory 嵌进 **Hermes Agent** 主循环，而不是把 Hermes 重写成记忆框架。  
> 配套代码：[`examples/hermes_memory_adapter.py`](../examples/hermes_memory_adapter.py)

---

## 1. 边界

| 归属 | 职责 |
|------|------|
| **EraHerm-Memory** | 存 / 召回 / 图影响 / 反馈反思 / 整理 |
| **Hermes** | 规划、工具、对话 UI；决定**何时**调用记忆、**记什么** |

内核不会自动从整段 chat 抽记忆。策略在 Host（本仓库用 `HermesMemoryBridge` 示范）。

---

## 2. 身份与会话映射（必须先定）

| Hermes 概念 | EraHerm 字段 | 建议 |
|-------------|--------------|------|
| 登录用户 / 工作区主人 | `user_id` | 稳定字符串，例如 `hermes:{account_id}` |
| 组织 / 多租户 | `tenant_id` | 可选；有多工作区再启用 |
| 一次对话线程 | `session_id` | 线程开始 `create_session`，结束 `close_session`（触发 L1→L2 晋升） |

错误示范：每条消息换一个 `user_id` → 永远召不回。

---

## 3. 推荐主循环

```text
on_thread_start:
  session = memory.create_session(user_id)
  bridge = HermesMemoryBridge(client, user_id=..., session_id=session["id"])

on_user_message(text):
  ctx = bridge.before_turn(text)
  system += bridge.build_system_suffix(ctx)   # 或 tool/context 块
  answer = hermes_llm_and_tools(...)

  # UI 赞/踩/纠正优先；否则启发式写记忆
  result = bridge.after_turn(
      text, answer,
      answer_id=turn_id,
      user_feedback=ui_feedback,       # upvote|downvote|correct|None
      correction_text=ui_correction,
  )
  if result.alerts:
      hermes_ui.show_memory_alerts(result.alerts)

on_thread_end:
  bridge.end_session()
```

演示脚本（需先起 API）：

```bash
uvicorn app.main:app --port 8000
python examples/hermes_memory_adapter.py --base-url http://127.0.0.1:8000
```

---

## 4. 记什么 / 不记什么（默认策略）

`HermesMemoryBridge` 默认启发式（可在 Hermes 里替换）：

| 写入 | 条件 |
|------|------|
| `remember` fact | 用户话含「我们用 / 项目 / 数据库 / 请记住…」等 |
| `remember` + `pinned` identity | 「我叫 / 用户名 / 称呼我」 |
| `feedback(correct)` | UI 纠正，或用户话像「不对 / 应该是…」 |
| 不写 | 纯闲聊、一次性工具日志、超长粘贴 |

生产建议：用 Hermes 自己的「记忆候选」分类器替换 `_maybe_extract_memory`，规则只作 fallback。

---

## 5. 能力接线表

| Hermes 场景 | API / SDK |
|-------------|-----------|
| 答眼前注入长期记忆 | `MemoryClient.recall` → `items` + `recommendations` |
| 「改 X 会影响谁」 | `MemoryClient.impact` |
| 用户钉死偏好 | `MemoryClient.pin` |
| 用户纠正错答 | `MemoryClient.feedback`（可 `wait_feedback`） |
| 技术栈切换弹窗 | `remember` 返回的 `alerts[]` |
| 夜间去膨胀 | 运维跑 `eraherm-consolidate` 或 admin API（不必进对话热路径） |
| IDE 侧挂载 | MCP：见 [MCP.md](MCP.md)（与 Hermes 进程可并存） |

---

## 6. 部署建议（挂 Hermes）— Embedding 写死

**硬性约定：Hermes 生产路径禁止 `hashing`。**  
`hashing` 只适合本仓库单测与离线脚手架；用它做「记忆准不准」的体验，召回会明显漂，口碑会坏在语义层而不是业务逻辑。

生产 `.env` 最小必改：

```env
# ✅ 生产 / Hermes：真实 embedding（OpenAI 或兼容网关）
ERAHERM_EMBEDDING_BACKEND=openai
ERAHERM_EMBEDDING_API_KEY=sk-...          # 或网关 key
ERAHERM_EMBEDDING_BASE_URL=https://api.openai.com/v1
ERAHERM_EMBEDDING_MODEL=text-embedding-3-small
ERAHERM_EMBEDDING_DIM=1536                # 须与模型维度一致

# ❌ 禁止（生产）
# ERAHERM_EMBEDDING_BACKEND=hashing

# 可选：更好抽取 / Reflection
ERAHERM_LLM_BACKEND=openai
ERAHERM_LLM_API_KEY=...

# 整理：对话外 cron，不要每轮触发
ERAHERM_CONSOLIDATION_ENABLED=false
```

本地模型：只要提供 **OpenAI 兼容** `/v1/embeddings`，把 `BASE_URL` 指到本地即可，后端名仍用 `openai`。

换 embedding 后必须重建向量（旧 hashing 向量不可混用）。

- 本机联调：同一台机 `uvicorn` + Hermes HTTP 客户端（联调阶段可用 hashing，**上线前改掉**）。  
- 同机多进程：L1 换 Redis（`ERAHERM_SESSION_CACHE_BACKEND=redis`）。  
- 向量量大：再上 Qdrant。

---

## 7. 接入检查清单

- [ ] `user_id` 跨会话稳定  
- [ ] 线程有 `session_id`，结束会 `close`  
- [ ] 每轮 `before_turn` 注入 recall（钉死项可见）  
- [ ] UI 有纠正/点踩 → `feedback`  
- [ ] `alerts` 有展示或明确忽略策略  
- [ ] **生产 `ERAHERM_EMBEDDING_BACKEND=openai`（或兼容端点），确认不是 `hashing`**  
- [ ] 评测：纠正后同类问题召回新事实（`python -m evals.harness`）

---

## 8. 把适配器搬进 Hermes 仓库

1. Hermes 依赖：`pip install eraherm-memory`（或 editable path）。  
2. 复制或引用 `HermesMemoryBridge`（策略可 fork）。  
3. 只依赖 `eraherm_memory.MemoryClient`，不要 import `app.*`（避免把内核实现泄漏进 Agent）。  
4. 契约测试：对 Fake HTTP / 本地 `uvicorn` 跑一轮「写入 → 召回 → 纠正 → 再召回」。
