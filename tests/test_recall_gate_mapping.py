# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""召回门禁纯函数的回归测试（不需要数据库）。

**核心回归**：ADR 0010 声称「旧绝对分配置按 rel=(score-0.15)/0.85 折算，严格度
语义不变」，但这个映射在默认值处不连续：

    0.25 → 特判 None → rel_min 保持 0.18
    0.26 → (0.26-0.15)/0.85 = 0.129   ← 调高阈值反而放宽门禁

也就是说「把 ERAHERM_RECALL_MIN_SCORE 从 0.25 调到 0.26」会让更多噪音过门禁，
而 README 的调参表还在教用户往 0.3~0.4 调。下面的单调性测试就是为这个 bug 加的。
"""

from __future__ import annotations

import pytest

from app.memory.gate import (
    LEX_EVIDENCE_MIN,
    legacy_relevance_floor,
    length_adjusted_lexical,
    lexical_similarity,
    passes_recall_gates,
    tokenize,
)

SCORE_DEFAULT = 0.25
REL_DEFAULT = 0.18
NOLEX_SCORE_DEFAULT = 0.38
NOLEX_REL_DEFAULT = 0.55


def _floor(score: float) -> float:
    return legacy_relevance_floor(
        score, score_default=SCORE_DEFAULT, relevance_default=REL_DEFAULT
    )


def _nolex_floor(score: float) -> float:
    return legacy_relevance_floor(
        score, score_default=NOLEX_SCORE_DEFAULT, relevance_default=NOLEX_REL_DEFAULT
    )


# --- 旧配置折算 ------------------------------------------------------------


def test_default_score_maps_exactly_to_new_relevance_default() -> None:
    assert _floor(SCORE_DEFAULT) == pytest.approx(REL_DEFAULT)
    assert _nolex_floor(NOLEX_SCORE_DEFAULT) == pytest.approx(NOLEX_REL_DEFAULT)


def test_raising_threshold_never_loosens_the_gate() -> None:
    """单调性：阈值升高 → 门禁不得变松（这是修复前的真实 bug）。"""
    scores = [0.05, 0.1, 0.2, 0.249, 0.25, 0.251, 0.26, 0.3, 0.4, 0.6, 0.9, 1.0]
    floors = [_floor(s) for s in scores]
    for prev_s, prev_f, cur_s, cur_f in zip(scores, floors, scores[1:], floors[1:]):
        assert cur_f >= prev_f - 1e-12, (
            f"门禁随阈值升高反而放宽：score {prev_s}→{cur_s} 使 rel_min {prev_f}→{cur_f}"
        )


def test_legacy_mapping_is_continuous_at_the_default() -> None:
    """默认点两侧不得出现跳变（旧实现在 0.25 处从 0.18 跳到 0.1176）。"""
    left = _floor(SCORE_DEFAULT - 1e-6)
    right = _floor(SCORE_DEFAULT + 1e-6)
    assert abs(right - left) < 1e-4
    assert abs(left - REL_DEFAULT) < 1e-4


def test_tightening_is_actually_tighter() -> None:
    # 旧实现在这两个点上都会「越调越松」
    assert _floor(0.26) > _floor(SCORE_DEFAULT)
    assert _floor(0.30) > _floor(SCORE_DEFAULT)
    assert _nolex_floor(0.39) > _nolex_floor(NOLEX_SCORE_DEFAULT)


def test_loosening_is_actually_looser() -> None:
    assert _floor(0.20) < _floor(SCORE_DEFAULT)
    assert _nolex_floor(0.30) < _nolex_floor(NOLEX_SCORE_DEFAULT)


def test_zero_or_negative_disables_that_gate() -> None:
    assert _floor(0.0) == 0.0
    assert _floor(-1.0) == 0.0
    assert _nolex_floor(0.0) == 0.0


def test_none_keeps_relevance_default() -> None:
    assert legacy_relevance_floor(
        None, score_default=SCORE_DEFAULT, relevance_default=REL_DEFAULT
    ) == pytest.approx(REL_DEFAULT)


# --- 门禁本身（保持 ADR 0010 行为） ----------------------------------------


def test_relevance_mode_ignores_age_collapsed_score() -> None:
    assert passes_recall_gates(
        score=0.001, relevance=0.60, lexical=0.5,
        min_score=0.30, min_score_no_lexical=0.55, mode="relevance",
    )
    assert not passes_recall_gates(
        score=0.001, relevance=0.60, lexical=0.5,
        min_score=0.25, min_score_no_lexical=0.38, mode="score",
    )


def test_zero_lexical_uses_stricter_floor() -> None:
    kwargs = dict(score=1.0, lexical=0.0, min_score=0.30, min_score_no_lexical=0.55,
                  mode="relevance")
    assert not passes_recall_gates(relevance=0.40, **kwargs)
    assert passes_recall_gates(relevance=0.60, **kwargs)


def test_score_mode_keeps_old_thresholds() -> None:
    assert not passes_recall_gates(
        score=0.20, lexical=0.5, min_score=0.25, min_score_no_lexical=0.38, mode="score"
    )
    assert passes_recall_gates(
        score=0.30, lexical=0.5, min_score=0.25, min_score_no_lexical=0.38, mode="score"
    )
    # 零词法时走更高门槛
    assert not passes_recall_gates(
        score=0.30, lexical=0.0, min_score=0.25, min_score_no_lexical=0.38, mode="score"
    )


# --- 词法信号 --------------------------------------------------------------


def test_tokenize_splits_ascii_and_cjk_punctuation() -> None:
    assert tokenize("FastAPI, 项目。技术栈！") == ["fastapi", "项目", "技术栈"]


def test_lexical_similarity_token_hits() -> None:
    tokens = tokenize("FastAPI 框架")
    assert lexical_similarity("项目使用 FastAPI 实现", tokens) == pytest.approx(0.5)


def test_lexical_similarity_cjk_bigram_fallback() -> None:
    """整句中文是一个 token，命中为 0 → 必须靠 bigram 兜底。"""
    tokens = tokenize("数据库用什么")
    score = lexical_similarity("我们数据库使用 PostgreSQL", tokens)
    assert score > 0.0


def test_long_content_discounts_lexical_evidence() -> None:
    full_credit = 300
    short = length_adjusted_lexical(0.5, 100, full_credit)
    assert short == pytest.approx(0.5)  # 未超长，不折扣
    long = length_adjusted_lexical(0.5, 1200, full_credit)
    assert long == pytest.approx(0.5 * (300 / 1200) ** 2)
    assert long < 0.5  # 折扣生效
    # 线上那条约 2920 字的「大杂烩」镜像长文：折扣后必须掉到零词法档
    mirror = length_adjusted_lexical(0.5, 2920, full_credit)
    assert mirror == pytest.approx(0.5 * (300 / 2920) ** 2)
    assert mirror < LEX_EVIDENCE_MIN
