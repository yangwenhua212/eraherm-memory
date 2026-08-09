# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.adapters.memory_session_cache import InMemorySessionCache
from app.adapters.networkx_graph_store import NetworkXSqliteGraphStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.adapters.sqlite_vector_store import SqliteVectorStore
from app.config import Settings
from app.graph.extractor import RuleGraphExtractor
from app.graph.service import GraphService
from app.main import create_app
from app.memory.importance import score_importance
from app.memory.service import MemoryService, effective_score
from app.models import MemoryRow
from app.ports.clock import Clock


class FixedClock(Clock):
    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self) -> datetime:
        return self._when


def _build_service(settings: Settings) -> MemoryService:
    repo = SqliteMemoryRepository(settings.database_url)
    vectors = SqliteVectorStore(settings.database_url, engine=repo.engine)
    graph_store = NetworkXSqliteGraphStore(repo.engine)
    graph = GraphService(
        store=graph_store,
        extractor=RuleGraphExtractor(),
        settings=settings,
        memory_repo=repo,
    )
    cache = InMemorySessionCache()
    clock = FixedClock(datetime(2026, 7, 29, tzinfo=timezone.utc))
    embedding = HashingEmbeddingClient(dimensions=settings.embedding_dim)
    return MemoryService(
        repo=repo,
        cache=cache,
        settings=settings,
        clock=clock,
        embedding=embedding,
        vectors=vectors,
        graph_service=graph,
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    db = tmp_path / "test.db"
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{db.as_posix()}",
        decay_lambda_default=0.05,
        promotion_importance_threshold=0.6,
        recall_top_k_default=8,
        recall_pinned_cap=20,
        recall_min_score=0.0,
        l1_max_items_per_session=200,
        auto_importance=True,
        recall_vector_weight=0.7,
        embedding_backend="hashing",
        embedding_dim=256,
    )


@pytest.fixture
def service(settings: Settings) -> MemoryService:
    return _build_service(settings)


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ERAHERM_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("ERAHERM_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("ERAHERM_EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("ERAHERM_RECALL_MIN_SCORE", "0")
    from app.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_effective_score_decays_with_age():
    now = datetime(2026, 7, 29, tzinfo=timezone.utc)
    fresh = effective_score(
        importance=1.0,
        weight=1.0,
        created_at="2026-07-29T00:00:00Z",
        decay_lambda=0.05,
        now=now,
    )
    old = effective_score(
        importance=1.0,
        weight=1.0,
        created_at="2026-01-01T00:00:00Z",
        decay_lambda=0.05,
        now=now,
    )
    assert fresh > old
    assert fresh == pytest.approx(1.0)


def test_pinned_never_decay_deleted(service: MemoryService):
    pinned = service.remember(
        content="用户名为 cc",
        user_id="u_1",
        memory_type="identity",
        importance=1.0,
        pinned=True,
    )
    old_id = "mem_old_low"
    old_created = (service.clock.now() - timedelta(days=365)).replace(microsecond=0)
    old_iso = old_created.isoformat().replace("+00:00", "Z")
    service.repo.create_memory(
        MemoryRow(
            id=old_id,
            user_id="u_1",
            content="临时闲聊内容",
            memory_type="episode",
            importance=0.2,
            weight=1.0,
            pinned=False,
            created_at=old_iso,
            updated_at=old_iso,
        )
    )

    deleted = service.apply_decay_deletions(user_id="u_1", score_threshold=0.5)
    assert deleted >= 1

    still = service.repo.get_memory(pinned.id)
    assert still is not None
    assert still.deleted_at is None
    assert still.pinned is True

    gone = service.repo.get_memory(old_id)
    assert gone is not None
    assert gone.deleted_at is not None


def test_pinned_survives_session_clear(service: MemoryService):
    session = service.create_session(user_id="u_demo")
    pinned = service.remember(
        content="项目名是 EraHerm-Memory",
        user_id="u_demo",
        session_id=session.id,
        memory_type="identity",
        importance=1.0,
        pinned=True,
    )
    service.remember(
        content="今天天气不错",
        user_id="u_demo",
        session_id=session.id,
        memory_type="episode",
        importance=0.1,
        pinned=False,
    )

    closed = service.close_session(session.id)
    assert closed.promoted_count >= 1
    assert service.cache.list(session.id) == []

    hits = service.recall(user_id="u_demo", query="项目名 EraHerm", session_id=None)
    assert any(h.id == pinned.id and h.pinned for h in hits)
    assert any("EraHerm-Memory" in h.content for h in hits)


def test_api_health_and_demo_flow(client: TestClient):
    health = client.get("/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    sess = client.post("/v1/sessions", json={"user_id": "u_api"})
    assert sess.status_code == 201
    session_id = sess.json()["id"]

    pin = client.post(
        "/v1/memories/pin",
        json={
            "user_id": "u_api",
            "session_id": session_id,
            "content": "用户名为 cc",
            "memory_type": "identity",
            "pinned": True,
        },
    )
    assert pin.status_code == 200
    assert pin.json()["pinned"] is True
    assert pin.json()["layer"] == "L2"

    closed = client.post(f"/v1/sessions/{session_id}/close")
    assert closed.status_code == 200

    recall = client.post(
        "/v1/recall",
        json={"user_id": "u_api", "query": "用户名是什么", "include_pinned": True},
    )
    assert recall.status_code == 200
    contents = [i["content"] for i in recall.json()["items"]]
    assert any("cc" in c for c in contents)


def test_importance_heuristic_promotes_facts():
    fact = score_importance(
        content="EraHerm 项目使用 FastAPI 和 SQLite 作为存储",
        memory_type="fact",
    )
    chat = score_importance(content="哈哈你好天气不错", memory_type="episode")
    assert fact >= 0.6
    assert chat < 0.6


def test_session_close_promotes_and_semantic_recall(service: MemoryService):
    """Phase 2 demo: multi-turn -> close -> semantic recall of promoted fact."""
    session = service.create_session(user_id="u_p2")

    # Low importance chitchat stays L1 then drops
    r1 = service.remember(
        content="早上好呀",
        user_id="u_p2",
        session_id=session.id,
        memory_type="episode",
        importance=0.2,
    )
    assert r1.layer == "L1"

    # Fact should auto-score high enough to write L2 immediately or promote on close
    r2 = service.remember(
        content="EraHerm-Memory 的 API 层采用 FastAPI 实现",
        user_id="u_p2",
        session_id=session.id,
        memory_type="fact",
        importance=0.5,
    )
    assert r2.importance >= 0.6
    assert r2.layer == "L2"

    r3 = service.remember(
        content="长期记忆默认落在 SQLite 里",
        user_id="u_p2",
        session_id=session.id,
        memory_type="fact",
        importance=0.5,
    )
    assert r3.layer == "L2"

    closed = service.close_session(session.id)
    assert closed.dropped_count >= 1
    assert service.cache.list(session.id) == []

    # Semantic-ish paraphrase (shares key tokens with hashing embed; not exact sentence)
    hits = service.recall(
        user_id="u_p2",
        query="EraHerm 项目的 API 框架技术是什么",
        session_id=None,
        top_k=5,
    )
    contents = [h.content for h in hits]
    assert any("FastAPI" in c for c in contents)

    hits2 = service.recall(
        user_id="u_p2",
        query="长期记忆存在 SQLite 吗",
        session_id=None,
        top_k=5,
    )
    assert any("SQLite" in h.content for h in hits2)
