# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

"""Weak near-miss filtering + multi-pinned ranking without hard prepend."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.adapters.memory_session_cache import InMemorySessionCache
from app.adapters.networkx_graph_store import NetworkXSqliteGraphStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.adapters.sqlite_vector_store import SqliteVectorStore
from app.config import Settings
from app.graph.extractor import RuleGraphExtractor
from app.graph.service import GraphService
from app.memory.service import MemoryService, _lexical_similarity, _passes_recall_gates, _tokenize
from app.ports.clock import Clock


class FixedClock(Clock):
    def __init__(self, fixed: datetime) -> None:
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed


def _build(tmp_path: Path, **overrides) -> MemoryService:
    db = tmp_path / "rank.db"
    kwargs = dict(
        data_dir=tmp_path,
        database_url=f"sqlite:///{db.as_posix()}",
        extract_on_remember=False,
        embedding_backend="hashing",
        embedding_dim=128,
        recall_min_score=0.25,
        recall_min_score_no_lexical=0.38,
        recall_pinned_score_boost=0.05,
        recall_vector_weight=0.7,
        json_logs=False,
    )
    kwargs.update(overrides)
    settings = Settings(**kwargs)
    repo = SqliteMemoryRepository(settings.database_url)
    return MemoryService(
        repo=repo,
        cache=InMemorySessionCache(),
        settings=settings,
        clock=FixedClock(datetime(2026, 7, 30, tzinfo=timezone.utc)),
        embedding=HashingEmbeddingClient(dimensions=128),
        vectors=SqliteVectorStore(settings.database_url, engine=repo.engine),
        graph_service=GraphService(
            store=NetworkXSqliteGraphStore(repo.engine),
            extractor=RuleGraphExtractor(),
            settings=settings,
            memory_repo=repo,
        ),
    )


def test_cjk_lexical_bigrams_detect_overlap() -> None:
    tokens = _tokenize("数据库用什么")
    assert _lexical_similarity("数据库使用 PostgreSQL", tokens) > 0
    assert _lexical_similarity("用户喜欢喝冰美式", tokens) == 0


def test_gates_raise_bar_without_lexical() -> None:
    assert (
        _passes_recall_gates(
            score=0.35, lexical=0.0, min_score=0.25, min_score_no_lexical=0.38
        )
        is False
    )
    assert (
        _passes_recall_gates(
            score=0.40, lexical=0.0, min_score=0.25, min_score_no_lexical=0.38
        )
        is True
    )
    assert (
        _passes_recall_gates(
            score=0.30, lexical=0.5, min_score=0.25, min_score_no_lexical=0.38
        )
        is True
    )


def test_multi_pinned_query_prefers_matching_fact(tmp_path: Path) -> None:
    svc = _build(
        tmp_path,
        recall_min_score=0.0,
        recall_min_score_no_lexical=0.0,
    )
    svc.remember(
        content="用户名为杨文华",
        user_id="u_pin",
        memory_type="identity",
        importance=1.0,
        pinned=True,
    )
    svc.remember(
        content="数据库使用 PostgreSQL",
        user_id="u_pin",
        memory_type="fact",
        importance=1.0,
        pinned=True,
    )
    svc.remember(
        content="用户喜欢喝冰美式",
        user_id="u_pin",
        memory_type="preference",
        importance=1.0,
        pinned=True,
    )

    name_hits = svc.recall(user_id="u_pin", query="我的用户名是什么", top_k=5)
    assert name_hits, "identity query should recall"
    assert "杨文华" in name_hits[0].content

    db_hits = svc.recall(user_id="u_pin", query="数据库用什么", top_k=5)
    assert db_hits
    assert "PostgreSQL" in db_hits[0].content


def test_unrelated_query_does_not_hard_pull_pinned(tmp_path: Path) -> None:
    svc = _build(tmp_path)
    svc.remember(
        content="数据库使用 PostgreSQL",
        user_id="u_fp",
        importance=1.0,
        pinned=True,
    )
    weak = svc.recall(user_id="u_fp", query="今晚月球几点月圆", top_k=5)
    assert weak == []
