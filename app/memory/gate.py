# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""召回门禁与词法信号的**纯函数**实现（无 IO、无第三方依赖）。

从 ``app/memory/service.py`` 抽出来的原因：
这些判断是召回正确性的核心，却以前埋在 800 行的 service 里，只能通过「起一个
真 SQLite + 真向量库」才能测。抽成纯模块后可以直接单测，门禁这类容易出错、
又最容易悄悄退化的逻辑终于有了便宜可验证的落点。

**本次修复的真实 bug（``legacy_relevance_floor``）**：

ADR 0010 把门禁从「绝对分」改成「相关性」，同时把旧的 ``ERAHERM_RECALL_MIN_SCORE``
折算过来，老实现是::

    rel = (score - 0.15) / 0.85          # 且 score == 默认值时特判返回 None

这个映射有三个问题：

1. **不连续**：默认 ``0.25`` 走特判 → ``rel_min`` 保持 0.18；改成 ``0.26`` →
   ``(0.26-0.15)/0.85 = 0.129``，**门禁反而放宽**。用户以为自己收紧了。
2. **非单调**：``0.25 → 0.18`` 但 ``0.26 → 0.129``，阈值升高而门禁下降。
3. 换算后的量纲与它声称的"严格度不变"不符：``0.25``（旧绝对分）对应
   ``base=0.10`` 的记忆本来几乎必然被挡，而 ``rel=0.18`` 却能放行。

正确做法是**按默认点做比例缩放**，保证映射连续、单调、且在默认点精确落在
新的相关性默认值上::

    rel = relevance_default × (score / score_default)

- ``0.25 → 0.18``（锚点，与 ADR 0010 声称的默认行为一致）
- ``0.26 → 0.1872``、``0.30 → 0.216``（调高 = 更严，符合直觉）
- ``0.20 → 0.144``（调低 = 更松）
- ``<= 0 → 0.0``（显式关闭该档门禁，语义不变）
"""

from __future__ import annotations

import re

#: 「有词法证据」的最小值：低于此视为零词法，走从严门禁。
#: 长文二次折扣后零星命中的 lex 会掉到这以下，从而被归入从严档。
LEX_EVIDENCE_MIN = 0.02

_TOKEN_SPLIT = re.compile(r"[\s,.;:!?，。；：！？、]+")


def tokenize(text: str) -> list[str]:
    """按空白与中英文标点切词（不做分词，CJK 由 bigram 兜底）。"""
    return [t for t in _TOKEN_SPLIT.split((text or "").lower()) if t]


def clamp01(x: float) -> float:
    """把余弦相似度压进 [0, 1]（hashing 碰撞可能产生负值）。"""
    return max(0.0, min(1.0, float(x)))


def lexical_similarity(content: str, tokens: list[str]) -> float:
    """查询词在内容里的命中比例；一个词都没命中时退回 CJK 字符 bigram。"""
    if not tokens:
        return 0.0
    hay = (content or "").lower()
    hits = sum(1 for t in tokens if t in hay)
    if hits:
        return hits / len(tokens)
    # 中文常常整句作为一个 token，用字符 bigram 兜底
    joined = "".join(tokens)
    cjk = [ch for ch in joined if "\u4e00" <= ch <= "\u9fff"]
    if len(cjk) >= 2:
        bigrams = {"".join(cjk[i : i + 2]) for i in range(len(cjk) - 1)}
        shared = sum(1 for bg in bigrams if bg in hay)
        return shared / len(bigrams) if bigrams else 0.0
    return 0.0


def length_adjusted_lexical(lex: float, content_len: int, full_credit_len: int) -> float:
    """长文里「命中一个词」是弱证据：超过 ``full_credit_len`` 后按长度**二次**折扣。

    不折扣的话，一条几千字的「大杂烩」记忆会与几乎所有查询产生词法重叠，
    从而绕过词法门禁。
    """
    if full_credit_len <= 0 or content_len <= full_credit_len:
        return lex
    ratio = full_credit_len / content_len
    return lex * ratio * ratio


def legacy_relevance_floor(
    score_floor: float,
    *,
    score_default: float,
    relevance_default: float,
) -> float:
    """把旧的「绝对分门禁」配置折算到相关性空间（连续、单调、默认点对齐）。

    ``score_floor <= 0`` 表示调用方显式关闭这一档门禁，返回 ``0.0``。
    """
    if score_floor is None:
        return relevance_default
    score_floor = float(score_floor)
    if score_floor <= 0:
        return 0.0
    if score_default <= 0:
        return relevance_default
    return max(0.0, relevance_default * (score_floor / score_default))


def passes_recall_gates(
    *,
    score: float,
    relevance: float = 0.0,
    lexical: float,
    min_score: float,
    min_score_no_lexical: float,
    mode: str = "relevance",
) -> bool:
    """召回门禁。

    ``mode="relevance"``（默认）：只判相关性，与记忆年龄解耦。``score`` 含
    ``exp(-λ·age)``，卡绝对分会让 age > ~28 天的记忆永远召不回。

    ``mode="score"``：旧行为（绝对分门禁），保留作回滚开关。
    """
    if mode == "score":
        if min_score > 0 and score < min_score:
            return False
        if lexical <= 0 and min_score_no_lexical > 0 and score < min_score_no_lexical:
            return False
        return True
    # 零词法重叠 → 用更严的相关性门槛（挡纯向量蹭分，如「服务器配置」）
    floor = min_score if lexical >= LEX_EVIDENCE_MIN else min_score_no_lexical
    return relevance >= floor
