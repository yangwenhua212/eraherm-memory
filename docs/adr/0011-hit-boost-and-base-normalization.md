# ADR 0011：命中增稳（间隔重复的轻量版）与 base 归一化

- 状态：Accepted
- 日期：2026-10-08
- 依赖：[ADR 0010](0010-recall-gate-relevance.md)（门禁判相关性，衰减不再决定生死）

## 上下文

ADR 0010 之后，`decay_lambda` 只剩一个作用：**排序时区分名次**（不再决定召回生死）。此时回看打分链路，有两个问题：

### 1. 现成的「被使用」信号被浪费

`memories.access_count` / `last_accessed_at` 一直在写（每次召回返回就 +1），但**不参与任何打分**：

```text
base  = importance × exp(-decay_lambda × age_days) × weight
score = base × (0.15 + 0.85 × relevance)
```

也就是说，一条被反复召回、真正有用的记忆，和一条从没被用过、同年龄同重要度的记忆，衰减速度完全一样。这与「记忆应随使用而巩固」的直觉相反——也是间隔重复（SM-2 / FSRS）类系统最核心的那条机制。

### 2. `base` 项在排序里等于不存在

二段重排的排序键是：

```python
key = relevance + 0.2 × min(max(base, 0.0), 1.0) + pinned_boost
```

但 `base` 是**绝对量纲**且实测极小：生产库活跃记忆 `base ∈ [0.025, 0.099]`。于是 `0.2 × base ≈ 0.005 ~ 0.02`，而 `relevance ∈ [0, 1]`——**base 项比 relevance 低两个数量级，实际上没参与排序**。后果：两条相关性接近的记忆，谁更重要/更常用/更新，名次完全不看，等于「谁先命中谁先排」。

## 决策

### 1. 命中增稳：`lambda_eff = lambda / boost`

```text
boost = min(1 + alpha × ln(1 + access_count), cap)      # 单调、有界
```

- 默认 `alpha = 0.35`，`cap = 3.0`；用 `ln` 而非线性：增长慢，老条目不会变成「永生」。
- 命中 0 次 → `boost = 1.0`（与旧行为逐位一致）。
- `pinned` 在 boost 之前短路（`lambda = 0`），行为不变。
- L1 会话条目没有 `access_count` → `boost` 恒为 1.0（这是设计，不是漏洞）。
- **硬护栏** `recall_max_half_life_days = 365`：`lambda_eff` 不得小于 `ln2 / 365`，任何参数组合都造不出「永不衰减」的条目。

默认参数下的实际半衰期（基准 13.86 天）：

| 命中次数 | 0 | 1 | 3 | 10 | 36 | 68 | ≥cap |
|---|---|---|---|---|---|---|---|
| 有效半衰期 | 13.9 天 | 17.2 天 | 20.7 天 | 25.5 天 | 31.3 天 | 34.6 天 | 41.6 天 |

### 2. `base` 在候选集内相对归一化

```python
bmax = max(base_i)          # 候选集内
key  = relevance + base_w × (base / bmax) + pinned_boost     # base_w 默认 0.2
```

- 归一化后 base 项铺满 `[0, 0.2]`，**永远压不过 relevance**（量纲 1.0）。
- 所有候选 `base` 相等时全部归一化为 1.0 → 相当于加常数 → 名次不变（行为安全）。
- 开关 `recall_rank_base_normalize`（默认 `true`），关掉 = 回到 ADR 0010 的绝对量纲行为。

### 3. 两个开关都可逐位回滚

`ERAHERM_RECALL_HIT_BOOST_ENABLED=false` + `ERAHERM_RECALL_RANK_BASE_NORMALIZE=false`
→ 打分与 ADR 0010 版本**逐字节一致**（已用固定查询集的黄金样本 diff 验证）。

## 后果

- **正面**：被真正使用的记忆衰减更慢、名次更稳；「重要/常用/新鲜」这一维终于能参与破平，且不可能压过相关性；`access_count` 从「只写不读」的字段变成有效信号。
- **负面 / 已知风险**：`_touch_access` 在**每次召回返回**时就 +1，包含「被无关查询顺带捞出来」的情形 → 垃圾记忆也会攒 boost。v1 的对策是 `alpha` 小（0.35）+ `cap` 严（3.0）：最坏情况也只是半衰期从 13.9 天变成 41.6 天，且衰减只影响排序（门禁已与年龄解耦，见 ADR 0010），不会造成「召不回」或「压过相关性」。
- **中性**：`/v1/recall` 响应新增 `hit_boost` / `decay_lambda_eff` 两个诊断字段；`pinned` 条目的 `decay_lambda_eff` 恒为 0。
- 回归测试：`tests/test_recall_hit_boost.py`（10 例：单调/有界/开关等价/护栏/常用者排前/相关性仍压过 base）。

## 后续（未做，留作演进）

- 若实测发现 boost 通胀（被无关查询捞出的记忆攒分）：新增 `hit_count` 列，只在 `relevance ≥ recall_hit_boost_min_rel` 时 +1，boost 改用 `hit_count`。需要一次 schema 迁移，**本期不做**。
- 更远的方向见 `docs/ROADMAP.md`（归纳型偏好提炼 / bandit 化的权重在线更新），两者都挂了明确的启动条件。
