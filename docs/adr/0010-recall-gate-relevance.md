# ADR 0010：召回门禁判「相关性」，不判绝对分

- 状态：Accepted
- 日期：2026-10-08

## 上下文

召回打分是两段相乘：

```text
base  = importance × exp(-decay_lambda × age_days) × weight
score = base × (0.15 + 0.85 × relevance)
```

而门禁 `_passes_recall_gates` 卡的是 **`score`**（绝对分：有词法重叠 0.25，零词法 0.38）。

因为 `score = base × (0.15 + 0.85·relevance) ≤ base`，**分数上限就是 `base`**，而 `base` 随年龄指数衰减（默认 `decay_lambda = 0.05/天`，`exp(-0.05×27.7) = 0.2466`）：

> **记忆年龄超过约 28 天后，无论 `relevance` 多高（哪怕 1.0）都过不了门禁。**

2026-10-08 生产实测：生产库 9 条活跃记忆的 `base` 全在 `0.025 ~ 0.099` 之间，**recall 对任何查询（含同义换词这种送分题）都返回空**。线上用户 `hermes-user` 更极端：唯一还能过门禁的是 3 天前的一条 2920 字镜像长文，于是不同查询都返回同一条。

同时暴露三个次生问题：

1. `pinned` 记忆同样参与年龄衰减，与「钉死记忆不因衰减删除」的承诺自相矛盾——它们没被删，但已经召不回。
2. 排序键是 `score`（= base × relevance），于是**又长又 pinned 的记忆会压过更相关的短记忆**。
3. 超长「大杂烩」记忆（如镜像整段人设/记忆库）几乎与任何查询都有词法重叠，天然绕过词法门禁。

## 决策

1. **门禁改判 `relevance`**（与记忆年龄解耦）。`score` 退居排序用。
   - 有词法重叠：`recall_rel_min`（默认 0.18）
   - 零词法重叠：`recall_rel_min_no_lexical`（默认 0.55，保持「无关不答」）
   - 旧行为保留为 `recall_gate_mode = "score"` 回滚开关；旧配置（`recall_min_score*`）在 `relevance` 模式下按 `rel = (score - 0.15) / 0.85` 换算，语义严格度不变。
2. **`pinned` 不参与年龄衰减**（`recall_pinned_no_decay = true`），兑现「pinned 永不为衰减」。
3. **二段重排**：排序键改为 `relevance + 0.2 × base + pinned_boost`，相关性主导。
4. **词法信号按内容长度二次折扣**（`recall_lexical_len_norm = 300`）：超过 300 字后，零星命中的证据强度按 `(300/len)²` 折减；折减后低于 `_LEX_EVIDENCE_MIN = 0.02` 的视为「零词法」，走从严门禁。防长文「大杂烩」绕过门禁。

## 后果

- **正面**：老记忆重新可召回（这是长期记忆系统的底线）；身份/红线类 pinned 记忆年龄免疫；排序由相关性主导，长 pinned 记忆不再挤掉更相关的短记忆；长文噪声被结构性挡住。
- **负面**：门禁从绝对分改为相关性后，**准入面变宽**——对零词法候选必须靠 `recall_rel_min_no_lexical` 兜底，该阈值是对当前 embedding（`BAAI/bge-small-zh-v1.5`）的分数分布标定的，换模型必须重新标定。
- **中性**：`score` 字段仍在 API 返回中保留（同时新增 `relevance` / `lexical` / `vector_sim` / `base` 四个诊断字段），旧调用方不受影响。
- 回归测试：`tests/test_recall_gate_age_decoupled.py`（构造 400 天前的记忆，断言仍可召回）、`tests/test_recall_ranking.py`（两种门禁模式各自的行为）。
