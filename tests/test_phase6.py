# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.adapters.heuristic_reflection import HeuristicReflectionPipeline
from app.adapters.memory_job_queue import InMemoryJobQueue
from app.adapters.memory_session_cache import InMemorySessionCache
from app.adapters.networkx_graph_store import NetworkXSqliteGraphStore
from app.adapters.redis_session_cache import RedisSessionCache
from app.adapters.sqlite_feedback_store import SqliteFeedbackStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.adapters.sqlite_vector_store import SqliteVectorStore
from app.config import Settings, get_settings
from app.feedback.service import FeedbackService
from app.graph.extractor import RuleGraphExtractor
from app.graph.service import GraphService
from app.main import create_app
from app.memory.service import MemoryService
from app.models import L1Item
from app.ports.clock import Clock, SystemClock


class FixedClock(Clock):
    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self) -> datetime:
        return self._when


def test_redis_session_cache_roundtrip():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    cache = RedisSessionCache(client=client)
    item = L1Item(content="hello redis", user_id="u", session_id="s1", importance=0.8)
    cache.append("s1", item)
    listed = cache.list("s1")
    assert len(listed) == 1
    assert listed[0].content == "hello redis"
    assert cache.clear("s1") == 1
    assert cache.list("s1") == []


def test_qdrant_vector_store_search(tmp_path: Path):
    pytest.importorskip("qdrant_client")
    from app.adapters.qdrant_vector_store import QdrantVectorStore

    embed = HashingEmbeddingClient(dimensions=64)
    store = QdrantVectorStore(path=str(tmp_path / "qdrant"), vector_size=64, collection="t")
    v1 = embed.embed(["FastAPI memory kernel"])[0]
    v2 = embed.embed(["banana smoothie recipe"])[0]
    store.upsert(memory_id="m1", user_id="u", vector=v1, model=embed.model_name)
    store.upsert(memory_id="m2", user_id="u", vector=v2, model=embed.model_name)
    hits = store.search(query=embed.embed(["FastAPI kernel"])[0], user_id="u", top_k=2)
    assert hits[0].memory_id == "m1"


def test_async_feedback_pending_then_accepted(tmp_path: Path):
    db = tmp_path / "async.db"
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{db.as_posix()}",
        feedback_async=True,
        extract_on_remember=False,
        embedding_dim=64,
    )
    repo = SqliteMemoryRepository(settings.database_url)
    memory = MemoryService(
        repo=repo,
        cache=InMemorySessionCache(),
        settings=settings,
        clock=FixedClock(datetime(2026, 7, 29, tzinfo=timezone.utc)),
        embedding=HashingEmbeddingClient(dimensions=64),
        vectors=SqliteVectorStore(settings.database_url, engine=repo.engine),
        graph_service=GraphService(
            store=NetworkXSqliteGraphStore(repo.engine),
            extractor=RuleGraphExtractor(),
            settings=settings,
            memory_repo=repo,
        ),
    )
    service = FeedbackService(
        store=SqliteFeedbackStore(repo.engine),
        memory=memory,
        reflection=HeuristicReflectionPipeline(),
        settings=settings,
        clock=SystemClock(),
        job_queue=None,
    )
    queue = InMemoryJobQueue(handler=service.process_job)
    service.job_queue = queue

    mem = memory.remember(
        content="数据库使用 MySQL",
        user_id="u_async",
        importance=0.9,
        extract_graph=False,
    )
    result = service.submit(
        user_id="u_async",
        answer_id="ans_a",
        feedback_type="correct",
        correction_text="应该是 PostgreSQL 不是 MySQL",
        related_memory_ids=[mem.id],
        async_mode=True,
    )
    assert result.async_pending is True
    assert result.reflection is not None
    assert result.reflection.status == "pending"

    deadline = time.time() + 3
    final = None
    while time.time() < deadline:
        final = service.get(result.feedback_id)
        if final.reflection and final.reflection.status != "pending":
            break
        time.sleep(0.05)
    assert final is not None and final.reflection is not None
    assert final.reflection.status == "accepted"
    assert final.reflection.derived_memory_id
    queue.stop()


def test_sdk_and_get_feedback_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from eraherm_memory import MemoryClient

    db = tmp_path / "sdk.db"
    monkeypatch.setenv("ERAHERM_DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("ERAHERM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ERAHERM_EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("ERAHERM_JSON_LOGS", "false")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        # Exercise SDK methods via TestClient-compatible wrapper
        class _TC:
            def __init__(self, c: TestClient):
                self._c = c

            def get(self, url, **kwargs):
                return self._c.get(url, **kwargs)

            def post(self, url, **kwargs):
                return self._c.post(url, **kwargs)

            def close(self):
                return None

        sdk = MemoryClient(base_url="http://test")
        sdk._client = _TC(client)  # type: ignore[assignment]
        assert sdk.health()["status"] == "ok"
        mem = sdk.remember(
            content="EraHerm uses FastAPI",
            user_id="u_sdk",
            importance=0.9,
            extract_graph=False,
        )
        hits = sdk.recall(user_id="u_sdk", query="FastAPI")
        assert any("FastAPI" in i["content"] for i in hits["items"])
        fb = sdk.feedback(
            user_id="u_sdk",
            answer_id="ans_sdk",
            feedback_type="correct",
            correction_text="应该是 Starlette 底层不是 Django",
            related_memory_ids=[mem["id"]],
            async_mode=False,
        )
        got = sdk.get_feedback(fb["feedback_id"])
        assert got["feedback_id"] == fb["feedback_id"]
        assert got["reflection"]["status"] == "accepted"
    get_settings.cache_clear()


def test_neo4j_adapter_import_message():
    # Without neo4j installed, constructing should raise ImportError with hint.
    # If installed but no server, skip connection test here.
    try:
        import neo4j  # noqa: F401
    except ImportError:
        from app.adapters.neo4j_graph_store import Neo4jGraphStore

        with pytest.raises(ImportError, match="neo4j"):
            # Force import error path by temporarily breaking - actually if not installed
            # the class body import happens in __init__
            Neo4jGraphStore(uri="bolt://localhost:7687")
    else:
        pytest.skip("neo4j installed; live server test not run in CI")
