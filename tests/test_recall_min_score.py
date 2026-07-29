# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.adapters.memory_session_cache import InMemorySessionCache
from app.adapters.networkx_graph_store import NetworkXSqliteGraphStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.adapters.sqlite_vector_store import SqliteVectorStore
from app.config import Settings, get_settings
from app.graph.extractor import RuleGraphExtractor
from app.graph.service import GraphService
from app.main import create_app
from app.memory.service import MemoryService
from app.ports.clock import Clock


class FixedClock(Clock):
    def __init__(self, fixed: datetime) -> None:
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed


def _build(tmp_path: Path, *, min_score: float) -> MemoryService:
    db = tmp_path / "min_score.db"
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{db.as_posix()}",
        extract_on_remember=False,
        embedding_backend="hashing",
        embedding_dim=128,
        recall_min_score=min_score,
        recall_vector_weight=0.7,
        json_logs=False,
    )
    repo = SqliteMemoryRepository(settings.database_url)
    return MemoryService(
        repo=repo,
        cache=InMemorySessionCache(),
        settings=settings,
        clock=FixedClock(datetime(2026, 7, 29, tzinfo=timezone.utc)),
        embedding=HashingEmbeddingClient(dimensions=128),
        vectors=SqliteVectorStore(settings.database_url, engine=repo.engine),
        graph_service=GraphService(
            store=NetworkXSqliteGraphStore(repo.engine),
            extractor=RuleGraphExtractor(),
            settings=settings,
            memory_repo=repo,
        ),
    )


def test_recall_min_score_filters_weak_hits(tmp_path: Path) -> None:
    svc = _build(tmp_path, min_score=0.25)
    svc.remember(
        content="用户喜欢喝冰美式",
        user_id="u_ms",
        memory_type="fact",
        importance=1.0,
        pinned=True,
    )

    related = svc.recall(user_id="u_ms", query="冰美式 冰块 喜好", top_k=5)
    assert related, "related paraphrase should pass the gate"
    assert all(h.score >= 0.25 for h in related)

    # Unrelated query: hashing may still return a low-score hard-pull; gate should drop it.
    weak = svc.recall(user_id="u_ms", query="明天股市怎么走 量子纠缠证明", top_k=5)
    assert weak == [] or all(h.score >= 0.25 for h in weak)


def test_recall_min_score_override_disables_gate(tmp_path: Path) -> None:
    svc = _build(tmp_path, min_score=0.99)
    svc.remember(
        content="项目使用 FastAPI",
        user_id="u_ms2",
        memory_type="fact",
        importance=0.8,
    )
    assert svc.recall(user_id="u_ms2", query="FastAPI 框架", top_k=5) == []
    hits = svc.recall(user_id="u_ms2", query="FastAPI 框架", top_k=5, min_score=0.0)
    assert any("FastAPI" in h.content for h in hits)


def test_recall_api_min_score_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "api_ms.db"
    monkeypatch.setenv("ERAHERM_DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("ERAHERM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ERAHERM_EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("ERAHERM_RECALL_MIN_SCORE", "0.99")
    monkeypatch.setenv("ERAHERM_EXTRACT_ON_REMEMBER", "false")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/v1/memories",
            json={"user_id": "u_api", "content": "用户喜欢吃冰美式", "importance": 1.0},
        )
        res = client.post(
            "/v1/recall",
            json={"user_id": "u_api", "query": "量子计算", "top_k": 5},
        )
        assert res.status_code == 200
        assert res.json()["items"] == []
        res2 = client.post(
            "/v1/recall",
            json={"user_id": "u_api", "query": "冰美式", "top_k": 5, "min_score": 0.0},
        )
        assert res2.status_code == 200
        assert any("冰美式" in i["content"] for i in res2.json()["items"])
    get_settings.cache_clear()
