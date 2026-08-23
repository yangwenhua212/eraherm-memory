# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""纠正即进化回归：新事实必须压过旧事实（干净事实模板 + pinned 豁免 no_lexical 门禁）。

背景（2026-08-23 线上 FAIL）：
- 纠正反射把新事实包成「正确事实：X（此前误为 Y）」，嵌入分被拉低；
- recall 门禁用 min_score_no_lexical 挡掉零词法重叠的 pinned 新事实；
- pinned boost 在门禁过滤后才生效，救不了被挡的候选。
"""

from __future__ import annotations

from pathlib import Path

from app.adapters.heuristic_reflection import (
    HeuristicReflectionPipeline,
    _normalize_correction,
)
from app.memory.service import _passes_recall_gates

from test_recall_ranking import _build


# ---------- 纠正反射：生成干净事实 ----------

def test_correction_replaces_wrong_in_related_memory() -> None:
    out = _normalize_correction("应该是 PostgreSQL 不是 MySQL", ["数据库使用 MySQL"])
    assert out == "数据库使用 PostgreSQL"


def test_correction_case_insensitive_replace() -> None:
    # 用户纠正写小写 fastmcp，记忆里存大写 MCP → 大小写不敏感替换
    out = _normalize_correction("应该是 fastmcp 不是 mcp", ["项目 Cursor 适配器用 MCP stdio 连接"])
    assert out == "项目 Cursor 适配器用 fastmcp stdio 连接"


def test_correction_fallback_without_related_keeps_correct_first() -> None:
    out = _normalize_correction("应该是 PostgreSQL 不是 MySQL")
    assert "PostgreSQL" in out
    assert "此前误为" in out


def test_reflect_correct_uses_clean_fact_summary() -> None:
    pipe = HeuristicReflectionPipeline()
    draft = pipe.reflect(
        feedback_type="correct",
        correction_text="应该是 PostgreSQL 不是 MySQL",
        answer_text="你们用 MySQL",
        related_contents=["数据库使用 MySQL"],
    )
    assert draft.summary == "数据库使用 PostgreSQL"


def test_reflect_correct_identity_still_pinned() -> None:
    pipe = HeuristicReflectionPipeline()
    draft = pipe.reflect(
        feedback_type="correct",
        correction_text="我是小忺",
        answer_text="你叫大忺",
        related_contents=["用户叫大忺"],
    )
    assert draft.pinned is True
    assert draft.memory_type == "identity"


# ---------- recall 门禁：pinned 不豁免、无关不硬拉 ----------

def test_gates_still_block_zero_lexical_low_score() -> None:
    assert (
        _passes_recall_gates(
            score=0.35, lexical=0.0, min_score=0.25, min_score_no_lexical=0.38
        )
        is False
    )


def test_pinned_not_hard_pulled_on_unrelated_query(tmp_path: Path) -> None:
    # pinned 只 boost 不豁免：无关查询零词法重叠时，pinned 也不硬拉
    svc = _build(
        tmp_path,
        recall_min_score_no_lexical=0.99,
        recall_min_score=0.0,
    )
    svc.remember(
        content="数据库使用 PostgreSQL",
        user_id="u_pl",
        memory_type="fact",
        importance=1.0,
        pinned=True,
    )

    hits = svc.recall(user_id="u_pl", query="月球几点月圆", top_k=5)
    assert hits == []
