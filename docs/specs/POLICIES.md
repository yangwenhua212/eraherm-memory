# 记忆与反馈政策（初稿）

> 机器可读配置将在实现阶段引入；本文档为权威语义说明。

---

## 1. 记忆政策 `memory_policy`

| 键 | 默认 | 说明 |
|----|------|------|
| `decay_lambda_default` | `0.05` | 按天指数衰减系数 |
| `promotion_importance_threshold` | `0.6` | 会话结束晋升 L2 的重要性下限 |
| `recall_top_k_default` | `8` | 默认召回条数 |
| `recall_pinned_cap` | `20` | 参与召回的钉死条数扫描上限 |
| `recall_min_score` | `0.25` | **旧：绝对分门禁**（仅 `recall_gate_mode=score` 时生效） |
| `recall_min_score_no_lexical` | `0.38` | **旧：零词法重叠时的更高门槛**（仅 `recall_gate_mode=score` 时生效） |
| `recall_gate_mode` | `relevance` | 门禁量纲。`relevance`=只判相关性（与记忆年龄解耦）；`score`=旧绝对分行为（回滚开关） |
| `recall_rel_min` | `0.18` | 有词法重叠时的**相关性**门禁 |
| `recall_rel_min_no_lexical` | `0.55` | 零词法重叠时的更高相关性门禁（压制纯向量蹭分） |
| `recall_pinned_no_decay` | `true` | pinned（核心记忆）不参与年龄衰减——兑现「pinned 永不为衰减」 |
| `recall_rank_base_weight` | `0.2` | 二段重排里 base 的权重（相关性主导排序） |
| `recall_lexical_len_norm` | `300` | 词法信号长度折扣阈值：超长内容的零星命中按长度二次折减（防「大杂烩」绕过门禁） |
| `recall_pinned_score_boost` | `0.05` | 钉死仅作排序加权，**不再无条件置顶** |
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
| `correct_creates_pinned` | `true` | 纠正默认钉死新事实（与 `.env.example` 一致） |
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
