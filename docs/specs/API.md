# API 规范

> 状态：Draft v0.1  
> 风格：REST + JSON；前缀 `/v1`；时间 UTC。

---

## 1. 约定

| 项 | 约定 |
|----|------|
| Base URL | `/v1` |
| Content-Type | `application/json` |
| 错误 | `{ "error": { "code": "...", "message": "...", "details": {} } }` |
| 幂等 | 写操作可带 `Idempotency-Key`（后续实现） |
| 隔离 | Header 或 body 传 `X-User-Id` / `user_id`；`tenant_id` 可选 |

公共 Header（建议）：

- `X-Request-Id`
- `X-User-Id`
- `X-Tenant-Id`（可选）

---

## 2. 会话

### `POST /v1/sessions`

创建会话。

```json
{
  "user_id": "u_123",
  "meta": { "channel": "ide" }
}
```

响应：`201`

```json
{
  "id": "sess_...",
  "status": "open",
  "created_at": "2026-07-29T01:00:00Z"
}
```

### `POST /v1/sessions/{session_id}/close`

关闭会话，触发 L1 晋升/丢弃策略。

响应：`200`

```json
{
  "id": "sess_...",
  "status": "closed",
  "promoted_count": 3,
  "dropped_count": 10
}
```

---

## 3. 记忆写入与召回

### `POST /v1/memories`

Remember：写入一条内容（先进 L1；符合策略则写 L2）。

```json
{
  "session_id": "sess_...",
  "user_id": "u_123",
  "content": "项目 EraHerm 使用 FastAPI 作为 API 层",
  "memory_type": "fact",
  "importance": 0.8,
  "pinned": false,
  "extract_graph": true
}
```

响应：`201`

```json
{
  "id": "mem_...",
  "layer": "L2",
  "pinned": false,
  "entities_extracted": 2,
  "relations_extracted": 1,
  "alerts": [
    {
      "type": "tech_stack_shift",
      "severity": 0.82,
      "message": "检测到技术栈切换（java→go）。…是否要将迁移经验也写入？",
      "related_memory_ids": ["mem_..."]
    }
  ]
}
```

`alerts` 默认可为空数组；Host 决定是否弹窗。可用 `ERAHERM_PROACTIVE_ALERTS_ENABLED=false` 关闭。
### `POST /v1/memories/pin`

将已有记忆钉死（或直接写入钉死记忆）。

```json
{
  "memory_id": "mem_...",
  "pinned": true
}
```

或：

```json
{
  "user_id": "u_123",
  "content": "用户名为 cc",
  "memory_type": "identity",
  "pinned": true
}
```

### `POST /v1/recall`

召回。

```json
{
  "user_id": "u_123",
  "session_id": "sess_...",
  "query": "EraHerm 用什么技术栈",
  "top_k": 8,
  "include_pinned": true,
  "expand_graph": false
}
```

响应：`200`

```json
{
  "items": [
    {
      "id": "mem_...",
      "content": "...",
      "memory_type": "fact",
      "score": 0.91,
      "pinned": true,
      "layer": "L2"
    }
  ],
  "recommendations": [
    {
      "memory_id": "mem_...",
      "content": "上次改超时配置曾加过重试…",
      "score": 0.61,
      "reason": "similar_topic"
    }
  ]
}
```

`recommendations` 为旁路关联推荐（不替代 `items`）；可用 `ERAHERM_PROACTIVE_RECOMMEND_ENABLED=false` 关闭。

---

## 4. 图谱

### `POST /v1/graph/extract`

对文本或 `memory_id` 强制抽取（调试/补跑）。

```json
{
  "user_id": "u_123",
  "text": "A 服务依赖 B 服务和 Redis",
  "memory_id": null
}
```

### `GET /v1/graph/entities`

查询实体：`?user_id=&q=&type=`

### `POST /v1/graph/impact`

「改 A 会影响谁」——路径/影响面。

```json
{
  "user_id": "u_123",
  "entity_name": "A服务",
  "direction": "outbound",
  "max_hops": 2
}
```

响应：`200`

```json
{
  "seed": { "id": "ent_...", "name": "A服务", "entity_type": "service" },
  "paths": [
    {
      "hops": 1,
      "nodes": [
        { "name": "A服务", "entity_type": "service" },
        { "name": "B服务", "entity_type": "service" }
      ],
      "edges": [
        { "relation_type": "depends_on", "weight": 1.0 }
      ]
    }
  ],
  "recommendations": [
    {
      "memory_id": "mem_...",
      "content": "上次改 A 服务超时配置的经验…",
      "score": 0.55,
      "reason": "similar_change_experience"
    }
  ]
}
```

---

## 5. 反馈

### `POST /v1/feedback`

```json
{
  "user_id": "u_123",
  "session_id": "sess_...",
  "answer_id": "ans_...",
  "feedback_type": "correct",
  "correction_text": "应该是 PostgreSQL 不是 MySQL",
  "related_memory_ids": ["mem_..."]
}
```

响应：`200`

```json
{
  "feedback_id": "fb_...",
  "reflection": {
    "id": "ref_...",
    "status": "accepted",
    "confidence": 0.86,
    "summary": "用户数据库为 PostgreSQL，纠正此前 MySQL 表述",
    "derived_memory_id": "mem_..."
  }
}
```

`upvote` / `downvote` 时 `correction_text` 可空；`downvote` 仍可能产生 Reflection。

---

## 6. 健康与管理

### `GET /v1/health`

```json
{ "status": "ok", "version": "0.1.0" }
```

### `POST /v1/admin/consolidate`

触发记忆整理（重排 / 压缩 / 冲突淘汰 / 低权重遗忘）。需 `X-Admin-Token` 头（值 = `ERAHERM_ADMIN_TOKEN`）。

```bash
curl -X POST http://127.0.0.1:8000/v1/admin/consolidate \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: $ERAHERM_ADMIN_TOKEN" \
  -d '{"user_id": "u_123"}'
```

```json
{ "user_id": "u_123" }
```

`user_id` 省略则对所有用户执行。

### `POST /v1/admin/l3/dump`

触发 L3 归档；需管理令牌。

MCP 工具封装见 [MCP.md](../MCP.md)。

---

## 7. 错误码（初稿）

| code | HTTP | 含义 |
|------|------|------|
| `validation_error` | 400 | 参数不合法 |
| `not_found` | 404 | 资源不存在 |
| `conflict` | 409 | 状态冲突（如重复关闭会话） |
| `llm_failed` | 502 | 抽取/反思上游失败 |
| `internal_error` | 500 | 未分类错误 |

---

## 8. 版本策略

- 路径含 `/v1`；破坏性变更走 `/v2`。
- 新增可选字段不视为破坏。
- 废弃字段在响应 `Warning` 或文档中标注至少一个次版本周期。
