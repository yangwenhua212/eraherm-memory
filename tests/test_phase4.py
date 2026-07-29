# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.adapters.heuristic_reflection import HeuristicReflectionPipeline
from app.adapters.memory_session_cache import InMemorySessionCache
from app.adapters.networkx_graph_store import NetworkXSqliteGraphStore
from app.adapters.sqlite_feedback_store import SqliteFeedbackStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.adapters.sqlite_vector_store import SqliteVectorStore
from app.config import Settings
from app.feedback.service import FeedbackService
from app.graph.extractor import RuleGraphExtractor
from app.graph.service import GraphService
from app.main import create_app
from app.memory.service import MemoryService
from app.ports.clock import Clock


class FixedClock(Clock):
    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self) -> datetime:
        return self._when


def _settings(tmp_path: Path) -> Settings:
    db = tmp_path / "fb.db"
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{db.as_posix()}",
        extract_on_remember=False,
        embedding_backend="hashing",
        embedding_dim=64,
        reflection_confidence_threshold=0.7,
        upvote_weight_delta=0.05,
        downvote_weight_delta=-0.1,
        downvote_writes_negative_memory=True,
        correct_creates_pinned=False,
        recall_min_score=0.0,
    )


def _build(settings: Settings) -> tuple[MemoryService, FeedbackService]:
    repo = SqliteMemoryRepository(settings.database_url)
    vectors = SqliteVectorStore(settings.database_url, engine=repo.engine)
    graph = GraphService(
        store=NetworkXSqliteGraphStore(repo.engine),
        extractor=RuleGraphExtractor(),
        settings=settings,
        memory_repo=repo,
    )
    memory = MemoryService(
        repo=repo,
        cache=InMemorySessionCache(),
        settings=settings,
        clock=FixedClock(datetime(2026, 7, 29, tzinfo=timezone.utc)),
        embedding=HashingEmbeddingClient(dimensions=settings.embedding_dim),
        vectors=vectors,
        graph_service=graph,
    )
    feedback = FeedbackService(
        store=SqliteFeedbackStore(repo.engine),
        memory=memory,
        reflection=HeuristicReflectionPipeline(),
        settings=settings,
        clock=FixedClock(datetime(2026, 7, 29, tzinfo=timezone.utc)),
    )
    return memory, feedback


def test_correct_writes_memory_and_recall_hits(tmp_path: Path):
    settings = _settings(tmp_path)
    memory, feedback = _build(settings)

    wrong = memory.remember(
        content="数据库使用 MySQL",
        user_id="u_fb",
        memory_type="fact",
        importance=0.9,
        extract_graph=False,
    )
    assert wrong.layer == "L2"

    result = feedback.submit(
        user_id="u_fb",
        answer_id="ans_1",
        feedback_type="correct",
        correction_text="应该是 PostgreSQL 不是 MySQL",
        related_memory_ids=[wrong.id],
        answer_text="你们用的是 MySQL",
    )
    assert result.reflection is not None
    assert result.reflection.status == "accepted"
    assert result.reflection.derived_memory_id
    assert "PostgreSQL" in result.reflection.summary

    # related wrong memory weight decreased
    old = memory.repo.get_memory(wrong.id)
    assert old is not None
    assert old.weight < 1.0

    hits = memory.recall(user_id="u_fb", query="数据库是 PostgreSQL 还是什么", top_k=5)
    contents = [h.content for h in hits]
    assert any("PostgreSQL" in c for c in contents)


def test_downvote_writes_negative_memory(tmp_path: Path):
    settings = _settings(tmp_path)
    memory, feedback = _build(settings)
    mem = memory.remember(
        content="推荐使用已废弃的旧 API",
        user_id="u_fb2",
        importance=0.8,
        extract_graph=False,
    )
    result = feedback.submit(
        user_id="u_fb2",
        answer_id="ans_2",
        feedback_type="downvote",
        related_memory_ids=[mem.id],
        answer_text="推荐使用已废弃的旧 API",
    )
    assert result.reflection is not None
    assert result.reflection.status == "accepted"
    derived = memory.repo.get_memory(result.reflection.derived_memory_id)
    assert derived is not None
    assert derived.memory_type == "negative"


def test_upvote_bumps_weight_no_reflection(tmp_path: Path):
    settings = _settings(tmp_path)
    memory, feedback = _build(settings)
    mem = memory.remember(
        content="项目名是 EraHerm-Memory",
        user_id="u_fb3",
        importance=0.9,
        extract_graph=False,
    )
    before = memory.repo.get_memory(mem.id)
    assert before is not None
    result = feedback.submit(
        user_id="u_fb3",
        answer_id="ans_3",
        feedback_type="upvote",
        related_memory_ids=[mem.id],
    )
    assert result.reflection is None
    after = memory.repo.get_memory(mem.id)
    assert after is not None
    assert after.weight == pytest.approx(before.weight + settings.upvote_weight_delta)


def test_low_confidence_rejected(tmp_path: Path):
    settings = _settings(tmp_path)
    _, feedback = _build(settings)
    # correct without enough text is validation error
    with pytest.raises(ValueError):
        feedback.submit(
            user_id="u_fb4",
            answer_id="ans_4",
            feedback_type="correct",
            correction_text="  ",
        )


def test_feedback_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = _settings(tmp_path)
    monkeypatch.setenv("ERAHERM_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("ERAHERM_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("ERAHERM_EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("ERAHERM_RECALL_MIN_SCORE", "0")
    from app.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        mem = client.post(
            "/v1/memories",
            json={
                "user_id": "u_api_fb",
                "content": "缓存用 Memcached",
                "importance": 0.9,
                "extract_graph": False,
            },
        )
        assert mem.status_code == 201
        mid = mem.json()["id"]

        fb = client.post(
            "/v1/feedback",
            json={
                "user_id": "u_api_fb",
                "answer_id": "ans_api",
                "feedback_type": "correct",
                "correction_text": "应该是 Redis 不是 Memcached",
                "related_memory_ids": [mid],
            },
        )
        assert fb.status_code == 200
        body = fb.json()
        assert body["reflection"]["status"] == "accepted"
        assert body["reflection"]["derived_memory_id"]

        recall = client.post(
            "/v1/recall",
            json={"user_id": "u_api_fb", "query": "缓存用 Redis 吗", "top_k": 5},
        )
        assert recall.status_code == 200
        assert any("Redis" in i["content"] for i in recall.json()["items"])
    get_settings.cache_clear()
