# 记忆与反馈政策（初稿）

> 机器可读配置将在实现阶段引入；本文档为权威语义说明。

---

## 1. 记忆政策 `memory_policy`

| 键 | 默认 | 说明 |
|----|------|------|
| `decay_lambda_default` | `0.05` | 按天指数衰减系数 |
| `promotion_importance_threshold` | `0.6` | 会话结束晋升 L2 的重要性下限 |
| `recall_top_k_default` | `8` | 默认召回条数 |
| `recall_pinned_cap` | `20` | 召回时强制附带的钉死条数上限 |
| `extract_on_remember` | `true` | 写入时是否抽图 |
| `l1_max_items_per_session` | `200` | 超出则淘汰最低分 |
| `auto_importance` | `true` | 用启发式抬升 importance（取 max(provided, heuristic)） |
| `recall_vector_weight` | `0.7` | 召回时向量相似度权重（其余为词法） |

### 钉死规则

- `memory_type in {identity, preference}` 且 Host 声明 `pinned=true` → 必须钉死。
- 钉死项：不因衰减删除；可更新 `content`（纠正确认后）；软删需显式管理接口。

### 晋升规则（会话关闭）

1. 计算 L1 条目 `effective_score`。
2. `score >= promotion_importance_threshold` → 写 L2 + embed。
3. 其余丢弃（可配置进入短时垃圾桶，MVP 直接丢）。

---

## 2. 图谱政策 `graph_policy`

| 键 | 默认 | 说明 |
|----|------|------|
| `max_hops_default` | `2` | impact 默认跳数 |
| `min_extract_confidence` | `0.5` | 低于此不落边 |
| `merge_entities_by_alias` | `true` | 别名合并到规范实体 |

---

## 3. 反馈政策 `feedback_policy`

| 键 | 默认 | 说明 |
|----|------|------|
| `reflection_confidence_threshold` | `0.7` | 低于此不写 L2 |
| `upvote_weight_delta` | `+0.05` | |
| `downvote_weight_delta` | `-0.1` | |
| `correct_creates_pinned` | `false` | 纠正默认不钉死；identity 类可例外 |
| `downvote_writes_negative_memory` | `true` | 点踩写 negative 类型 |

### Reflection 最低产出字段

- `analysis`：错误原因
- `summary`：可写入的陈述句
- `confidence`：0–1

---

## 4. 变更流程

1. 改本文档语义。
2. 同步默认配置。
3. 若改变线上用户可见行为，记 CHANGELOG，并考虑 ADR。
