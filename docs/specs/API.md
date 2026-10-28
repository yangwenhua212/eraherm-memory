# API 规范

> 状态：Draft v0.1  
> 风格：REST + JSON；前缀 `/v1`；时间 UTC。  
> 认证（0.10.2 起）：见 [ADR 0012](../adr/0012-api-auth-and-exposure-guard.md)。

---

## 1. 约定

| 项 | 约定 |
|----|------|
| Base URL | `/v1` |
| Content-Type | `application/json` |
| 错误 | `{ "error": { "code": "...", "message": "...", "details": {} } }` |
| 认证 | 配置了 `ERAHERM_API_TOKEN` 时，除 `GET /v1/health` 外所有路由都要带 `X-API-Token`（或 `Authorization: Bearer`），否则 **401**。见 [ADR 0012](../adr/0012-api-auth-and-exposure-guard.md) |
| 管理 | `/v1/admin/*` 另需 `X-Admin-Token`（值 = `ERAHERM_ADMIN_TOKEN`）。**未配置该环境变量时一律 503**（fail-closed） |
| 限流 | 进程内令牌桶（默认 600/min，burst 120，`/v1/health` 豁免）。超限返回 **429** + `Retry-After`。多 worker 各自计数，是「防误用」而非分布式限流 |
| 幂等 | 写操作可带 `Idempotency-Key`（**尚未实现**） |
| 隔离 | Header 或 body 传 `X-User-Id` / `user_id`；`tenant_id` 可选。⚠️ **仅 `X-User-Id` 自报，不是鉴权**：拿到 API token 的客户端仍可指定任意 `user_id`（单租户语义） |

公共 Header：

- `X-Request-Id`
- `X-API-Token`（配置了 API token 时必需）
- `X-User-Id`（仅 `POST /v1/sessions`、`POST /v1/memories`、`POST /v1/memories/pin` 读取；其余端点忽略它）
- `X-Tenant-Id`（可选）

> 响应会回带 `X-Request-Id`。

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
  "persisted": true,
  "drop_reason": null,
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

> **`persisted` / `drop_reason`（0.10.2 新增）**：`importance < ERAHERM_PROMOTION_IMPORTANCE_THRESHOLD`
> 且没传 `session_id` 时，这条记忆**不会落库**——以前 API 依然返回 201 + 一个查不到的 id。
> 现在显式返回 `persisted: false` 并给出 `drop_reason`。想要必定落库：传 `session_id`、
> 提高 `importance`、或 `pinned: true`。
>
> `memory_type` 必须是 `fact` / `preference` / `identity` / `episode` / `negative` / `reflection`
> 之一（其它值返回 422）。未知类型会落到 importance 兜底基线 0.5（< 0.6），
> 正是上面那条静默丢弃最常见的触发方式。

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
  "include_pinned": true
}
```

> 门禁判**相关性**而不是绝对分（见 [ADR 0010](../adr/0010-recall-gate-relevance.md)）：`ERAHERM_RECALL_REL_MIN`（有词法重叠，默认 `0.18`）/ `ERAHERM_RECALL_REL_MIN_NO_LEXICAL`（零词法，默认 `0.55`）。请求参数 `min_score` 会抬高有词法档的门槛，传 `0` 关闭门禁。
>
> 排序（见 [ADR 0011](../adr/0011-hit-boost-and-base-normalization.md)）：`relevance + 0.2×(base/max(base)) + pinned_boost`——相关性主导，`base`（重要度 × 衰减 × 反馈权重）只做破平。响应的 `hit_boost` 是被召回次数带来的稳定性倍数（命中 0 次 = 1.0，上限 `ERAHERM_RECALL_HIT_BOOST_CAP`，默认 3.0），`decay_lambda_eff` 是应用增稳与半衰期护栏后的实际衰减系数（`pinned` 恒为 `0`）。

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
      "layer": "L2",
      "relevance": 0.77,
      "lexical": 0.5,
      "vector_sim": 0.88,
      "base": 1.0,
      "hit_boost": 1.84,
      "decay_lambda_eff": 0.027
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

**唯一免认证的端点**（探针用）。`Accept: text/html` 时返回一个极简 HTML 页，否则 JSON：

```json
{ "status": "ok", "version": "0.10.2" }
```

### `POST /v1/admin/consolidate`

触发记忆整理（重排 / 压缩 / 冲突淘汰 / 低权重遗忘）。需 `X-Admin-Token` 头（值 = `ERAHERM_ADMIN_TOKEN`）。

```bash
# 先看会动什么（不落库）
curl -X POST http://127.0.0.1:8000/v1/admin/consolidate \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: $ERAHERM_ADMIN_TOKEN" \
  -d '{"user_id": "u_123", "dry_run": true}'
```

```json
{ "user_id": "u_123", "dry_run": false }
```

`user_id` 省略则对所有用户执行（走跨进程文件锁：多 worker 时只有一个进程真正跑）。
响应每项含 `dry_run` / `skipped_reason` / `archive_id`（删除前自动归档的 id）。

> ⚠️ 整理是**破坏性**的。三道安全网：`dry_run`、删除前自动 L3 归档
> （`ERAHERM_CONSOLIDATION_ARCHIVE_BEFORE_DELETE`，归档失败即放弃删除）、
> 以及下面两个恢复端点。

### `POST /v1/admin/memories/restore`

恢复被软删的记忆（整理误判的兜底出口）。二选一：显式 `memory_ids`，或
`user_id` + `limit`（恢复该用户最近删除的若干条）。恢复后会自动重建向量。

### `POST /v1/admin/l3/restore`

从 L3 归档 JSON 恢复记忆：`{"archive_id": "l3_..."}`。只补缺失的 id，不覆盖已存在的行；
返回 `restored_memories` / `skipped_existing` / `reembedded` / `errors`。

### `POST /v1/admin/watchdog`

主动感知看门狗巡检：扫描记忆库，产出「值得说的事」（倒计时事件 / 被遗忘的高价值记忆 / 记忆健康信号）。**零 LLM / 零外部 API**（SQLite + 正则 + 标准库）。需 `X-Admin-Token` 头。

```bash
curl -X POST http://127.0.0.1:8000/v1/admin/watchdog \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: $ERAHERM_ADMIN_TOKEN" \
  -d '{"user_id": "u_123"}'
```

```json
{ "user_id": "u_123" }
```

`user_id` 省略则巡检所有活跃用户。响应：

```json
{
  "items": [
    {
      "kind": "countdown",
      "title": "⏰ 一周后：2026-12-19",
      "detail": "期末考试 2026-12-19 开考",
      "severity": "normal",
      "related": ["mem_xxx"]
    }
  ],
  "users": ["u_123"]
}
```

- `items` 为空 = 无事发生，Host（cron 脚本）应静默不打扰
- 记忆内容命中敏感词表时**绝不进入 items**——主动推送 = 泄露。注意这只是中文**词表匹配**（`app/sensitive.py`），不是可靠的防泄漏边界
- 信号类型：`countdown`（D-7/D-3/D-1/当天）、`forgotten_gems`（importance≥0.8 且从未被 recall）、`health`（低权重堆积）

### `POST /v1/admin/l3/dump`

触发 L3 归档（把记忆/实体/关系导出成 JSON 落到 `storage/l3/`）。需 `X-Admin-Token`。

```bash
curl -X POST http://127.0.0.1:8000/v1/admin/l3/dump \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: $ERAHERM_ADMIN_TOKEN" \
  -d '{"user_id": "u_123"}'
```

`user_id` 省略则导出全库。响应含归档 id、文件绝对路径、sha256 校验和与各类计数。

> ⚠️ **目前只有导出，没有恢复接口**——它不是备份方案，删掉的记忆（consolidate 的软删）
> 无法通过它还原。

### `GET /v1/admin/l3/archives`

列出已有归档（`limit` 1~100，默认 20），按创建时间倒序。需 `X-Admin-Token`。

### `POST /v1/admin/reembed`

全量重建向量（换 embedding 后端 / 维度后必做）。需 `X-Admin-Token`。
body：`user_id`、`orphan_policy`(`assign`|`skip`|`fail`)、`orphan_user_id`、`batch_size`(1~512)、
`force`、`dry_run`、`cleanup_dangling`、`recreate_collection`。等价 CLI：`eraherm-reembed`。

### `GET /v1/metrics`

进程内计数器快照（`{"counters": {...}}`）。**不聚合多 worker、重启即清零**；无 Prometheus/OTel 导出。需要 API token（配置了的话）。

### `GET /v1/feedback/{feedback_id}`

查询某次反馈的异步 reflection 状态（`status` 为 `pending` 时表示还在跑）。需要 API token（配置了的话）。

---

## 7. 错误码

| code | HTTP | 含义 |
|------|------|------|
| `validation_error` | 400 | 参数不合法（含：远端 embedding + 敏感内容被拒，见 [ADR 0014](../adr/0014-sensitive-content-remote-embedding.md)） |
| `unauthorized` | 401 | API token 缺失/错误，或 admin token 错误 |
| `forbidden` | 403 | 资源不属于该 `user_id`（pin 别人的记忆 / 关闭别人的会话） |
| `not_found` | 404 | 资源不存在 |
| `conflict` | 409 | 状态冲突（如重复关闭会话） |
| `reembed_failed` | 400 | 重嵌请求本身失败（`details` 带报告） |
| `llm_failed` | 502 | 抽取/反思上游失败 |
| `rate_limited` | 429 | 触发限流，看 `Retry-After` |
| `unavailable` | 503 | 能力未启用（如 consolidate/watchdog 服务缺失） |
| `admin_disabled` | 503 | `ERAHERM_ADMIN_TOKEN` 未配置 → admin 端点整体关闭 |
| `internal_error` | 500 | 未分类错误 |

---

## 8. 版本策略

- 路径含 `/v1`；破坏性变更走 `/v2`。
- 新增可选字段不视为破坏。
- 废弃字段在响应 `Warning` 或文档中标注至少一个次版本周期。
