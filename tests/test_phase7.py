# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Phase 7: proactive alerts + sidecar recommendations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
from app.memory.service import MemoryService
from app.ports.clock import Clock
from app.proactive.service import ProactiveService


class FixedClock(Clock):
    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self) -> datetime:
        return self._when


def _settings(tmp_path: Path) -> Settings:
    db = tmp_path / "proactive.db"
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{db.as_posix()}",
        extract_on_remember=False,
        auto_importance=True,
        embedding_backend="hashing",
        embedding_dim=128,
        proactive_alerts_enabled=True,
        proactive_recommend_enabled=True,
        alert_similarity_threshold=0.2,
        recommend_min_score=0.05,
        recommend_top_k=3,
        recall_min_score=0.0,
        json_logs=False,
        log_level="WARNING",
    )


def _build(settings: Settings) -> MemoryService:
    repo = SqliteMemoryRepository(settings.database_url)
    vectors = SqliteVectorStore(settings.database_url, engine=repo.engine)
    embedding = HashingEmbeddingClient(dimensions=settings.embedding_dim)
    graph = GraphService(
        store=NetworkXSqliteGraphStore(repo.engine),
        extractor=RuleGraphExtractor(),
        settings=settings,
        memory_repo=repo,
    )
    proactive = ProactiveService(
        repo=repo, embedding=embedding, vectors=vectors, settings=settings
    )
    return MemoryService(
        repo=repo,
        cache=InMemorySessionCache(),
        settings=settings,
        clock=FixedClock(datetime(2026, 7, 29, tzinfo=timezone.utc)),
        embedding=embedding,
        vectors=vectors,
        graph_service=graph,
        proactive=proactive,
    )


def test_tech_stack_shift_alert(tmp_path: Path):
    memory = _build(_settings(tmp_path))
    memory.remember(
        content="后端技术栈使用 Java 和 Spring Boot",
        user_id="u_p7",
        importance=0.9,
        extract_graph=False,
    )
    result = memory.remember(
        content="新项目改用 Go 语言重写服务",
        user_id="u_p7",
        importance=0.9,
        extract_graph=False,
    )
    types = {a.type for a in result.alerts}
    assert "tech_stack_shift" in types
    assert any("java" in a.message.lower() and "go" in a.message.lower() for a in result.alerts)


def test_rewrite_same_go_fact_no_spam_conflict(tmp_path: Path):
    memory = _build(_settings(tmp_path))
    text = "新项目改用 Go 重写网关服务"
    memory.remember(content=text, user_id="u_p7d", importance=0.95, extract_graph=False)
    memory.remember(content=text, user_id="u_p7d", importance=0.95, extract_graph=False)
    again = memory.remember(content=text, user_id="u_p7d", importance=0.95, extract_graph=False)
    conflicts = [a for a in again.alerts if a.type == "conflict"]
    assert len(conflicts) == 0


def test_recommend_sidecar(tmp_path: Path):
    memory = _build(_settings(tmp_path))
    memory.remember(
        content="上次把支付超时从3秒调到10秒，并加了重试",
        user_id="u_p7b",
        importance=0.9,
        extract_graph=False,
    )
    memory.remember(
        content="用户偏好深色主题",
        user_id="u_p7b",
        importance=0.9,
        memory_type="preference",
        pinned=True,
        extract_graph=False,
    )
    recs = memory.recommend_sidecar(
        user_id="u_p7b",
        query="改超时配置要注意什么",
        reason="similar_topic",
    )
    assert len(recs) >= 1
    assert any("超时" in r.content or "重试" in r.content for r in recs)


def test_api_remember_alerts_and_recall_recommendations(tmp_path: Path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setenv("ERAHERM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ERAHERM_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("ERAHERM_EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("ERAHERM_EMBEDDING_DIM", "128")
    monkeypatch.setenv("ERAHERM_RECALL_MIN_SCORE", "0")
    monkeypatch.setenv("ERAHERM_PROACTIVE_ALERTS_ENABLED", "true")
    monkeypatch.setenv("ERAHERM_PROACTIVE_RECOMMEND_ENABLED", "true")
    monkeypatch.setenv("ERAHERM_EXTRACT_ON_REMEMBER", "false")
    monkeypatch.setenv("ERAHERM_JSON_LOGS", "false")
    from app.config import get_settings

    get_settings.cache_clear()

    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/v1/memories",
            json={
                "user_id": "u_api",
                "content": "团队主栈是 Java Spring",
                "importance": 0.95,
                "extract_graph": False,
            },
        )
        r2 = client.post(
            "/v1/memories",
            json={
                "user_id": "u_api",
                "content": "新项目改用 golang 微服务",
                "importance": 0.95,
                "extract_graph": False,
            },
        )
        assert r2.status_code == 201
        body = r2.json()
        assert isinstance(body.get("alerts"), list)
        assert any(a["type"] == "tech_stack_shift" for a in body["alerts"])

        client.post(
            "/v1/memories",
            json={
                "user_id": "u_api",
                "content": "改 Redis 连接池大小时曾导致抖动，建议先压测",
                "importance": 0.95,
                "extract_graph": False,
            },
        )
        recall = client.post(
            "/v1/recall",
            json={"user_id": "u_api", "query": "改 Redis 要注意什么", "top_k": 1},
        )
        assert recall.status_code == 200
        data = recall.json()
        assert "recommendations" in data
        assert isinstance(data["recommendations"], list)

    get_settings.cache_clear()
