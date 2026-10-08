# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""回归：召回门禁不得随记忆年龄失效。

2026-10-08 事故：`score = base × (0.15+0.85·rel)`，而 `base` 含 `exp(-λ·age)`；
门禁卡的是绝对分（0.25/0.38），于是 `age > ~28 天` 的记忆**即使 relevance=1.0**
也永远过不了门禁 —— 线上表现为「任何查询都返回空」。

本文件把两件事锁死：
1. `relevance` 门禁与年龄解耦（老记忆照样能召回）；
2. `pinned`（核心记忆）不参与年龄衰减。
同时保留 `recall_gate_mode="score"` 的旧行为回归，防止回滚开关失效。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.adapters.memory_session_cache import InMemorySessionCache
from app.adapters.networkx_graph_store import NetworkXSqliteGraphStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.adapters.sqlite_vector_store import SqliteVectorStore
from app.config import Settings
from app.graph.extractor import RuleGraphExtractor
from app.graph.service import GraphService
from app.memory.service import MemoryService, _passes_recall_gates, decay_lambda_for
from app.ports.clock import Clock

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
ANCIENT = NOW - timedelta(days=400)


class ShiftableClock(Clock):
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


def _build(tmp_path: Path, name: str, **overrides) -> tuple[MemoryService, ShiftableClock]:
    db = tmp_path / f"{name}.db"
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{db.as_posix()}",
        extract_on_remember=False,
        embedding_backend="hashing",
        embedding_dim=128,
        recall_vector_weight=0.7,
        json_logs=False,
        **overrides,
    )
    repo = SqliteMemoryRepository(settings.database_url)
    clock = ShiftableClock(NOW)
    svc = MemoryService(
        repo=repo,
        cache=InMemorySessionCache(),
        settings=settings,
        clock=clock,
        embedding=HashingEmbeddingClient(dimensions=128),
        vectors=SqliteVectorStore(settings.database_url, engine=repo.engine),
        graph_service=GraphService(
            store=NetworkXSqliteGraphStore(repo.engine),
            extractor=RuleGraphExtractor(),
            settings=settings,
            memory_repo=repo,
        ),
    )
    return svc, clock


# --- 单元：门禁与衰减 ------------------------------------------------------


def test_relevance_gate_ignores_age_collapsed_score() -> None:
    """分数被年龄压到 0.001，只要相关性达标就应放行（旧行为会挡掉）。"""
    assert _passes_recall_gates(
        score=0.001, relevance=0.60, lexical=0.5,
        min_score=0.30, min_score_no_lexical=0.55, mode="relevance",
    )
    # 旧行为（score 模式）下同一条被挡 —— 证明这就是事故根因
    assert not _passes_recall_gates(
        score=0.001, relevance=0.60, lexical=0.5,
        min_score=0.25, min_score_no_lexical=0.38, mode="score",
    )


def test_zero_lexical_uses_stricter_relevance_floor() -> None:
    args = dict(score=1.0, lexical=0.0, min_score=0.30, min_score_no_lexical=0.55,
                mode="relevance")
    assert not _passes_recall_gates(relevance=0.40, **args)
    assert _passes_recall_gates(relevance=0.60, **args)


def test_pinned_no_decay() -> None:
    assert decay_lambda_for(pinned=True, row_lambda=None, default_lambda=0.05,
                            pinned_no_decay=True) == 0.0
    assert decay_lambda_for(pinned=False, row_lambda=None, default_lambda=0.05,
                            pinned_no_decay=True) == 0.05
    assert decay_lambda_for(pinned=True, row_lambda=0.2, default_lambda=0.05,
                            pinned_no_decay=False) == 0.2


# --- 集成：400 天的记忆仍可召回 -------------------------------------------


def test_ancient_pinned_memory_is_still_recallable(tmp_path: Path) -> None:
    svc, clock = _build(tmp_path, "ancient_pinned")
    clock.current = ANCIENT
    svc.remember(content="用户名：example_user", user_id="u_age", memory_type="identity",
                 importance=1.0, pinned=True)
    clock.current = NOW

    hits = svc.recall(user_id="u_age", query="用户名：example_user", top_k=5)
    assert hits, "400 天前的 pinned 记忆必须仍能召回（门禁不得随年龄失效）"
    assert "example_user" in hits[0].content
    assert hits[0].base > 0.9, "pinned 不应参与年龄衰减"


def test_ancient_non_pinned_memory_passes_relevance_gate(tmp_path: Path) -> None:
    """非 pinned 的记忆同样不该因为「老」而被门禁判死。"""
    svc, clock = _build(tmp_path, "ancient_plain")
    clock.current = ANCIENT
    svc.remember(content="项目使用 FastAPI", user_id="u_age2", memory_type="fact",
                 importance=0.9)
    clock.current = NOW

    hits = svc.recall(user_id="u_age2", query="项目使用 FastAPI", top_k=5)
    assert hits, "老记忆的相关性达标就该召回"
    assert hits[0].base < 0.2, "非 pinned 仍走衰减（只是不再决定生死）"


def test_score_mode_keeps_old_behaviour(tmp_path: Path) -> None:
    """回滚开关：gate_mode=score + pinned_no_decay=False 时，老记忆仍被绝对分门禁挡掉。"""
    svc, clock = _build(tmp_path, "score_mode", recall_gate_mode="score",
                        recall_pinned_no_decay=False)
    clock.current = ANCIENT
    svc.remember(content="用户名：example_user", user_id="u_age3", memory_type="identity",
                 importance=1.0, pinned=True)
    clock.current = NOW

    assert svc.recall(user_id="u_age3", query="用户名：example_user", top_k=5) == []
