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
from app.config import Settings
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
    db = tmp_path / "graph.db"
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{db.as_posix()}",
        extract_on_remember=True,
        graph_max_hops_default=2,
        graph_min_extract_confidence=0.5,
        embedding_backend="hashing",
        embedding_dim=64,
    )


def _build(settings: Settings) -> tuple[MemoryService, GraphService]:
    repo = SqliteMemoryRepository(settings.database_url)
    vectors = SqliteVectorStore(settings.database_url, engine=repo.engine)
    graph_store = NetworkXSqliteGraphStore(repo.engine)
    graph = GraphService(
        store=graph_store,
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
    return memory, graph


def test_rule_extract_and_impact_who_depends_on_a(tmp_path: Path):
    settings = _settings(tmp_path)
    memory, graph = _build(settings)

    r = memory.remember(
        content="A服务依赖B服务和Redis。C服务依赖A服务。",
        user_id="u_g",
        memory_type="fact",
        importance=0.8,
        extract_graph=True,
    )
    assert r.relations_extracted >= 2
    assert r.entities_extracted >= 3

    impact = graph.impact(user_id="u_g", entity_name="A服务", direction="inbound", max_hops=2)
    names = {n.name for p in impact.paths for n in p.nodes}
    assert "C服务" in names

    outbound = graph.impact(user_id="u_g", entity_name="A服务", direction="outbound", max_hops=2)
    out_names = {n.name for p in outbound.paths for n in p.nodes}
    assert "B服务" in out_names
    assert "Redis" in out_names


def test_two_hop_impact(tmp_path: Path):
    settings = _settings(tmp_path)
    _, graph = _build(settings)
    graph.extract_and_ingest(
        user_id="u_g2",
        text="A服务依赖B服务。C服务依赖A服务。D服务依赖C服务。",
    )
    impact = graph.impact(user_id="u_g2", entity_name="A服务", direction="inbound", max_hops=2)
    # D is 2 hops via C
    end_names = {p.nodes[-1].name for p in impact.paths if p.hops == 2}
    assert "D服务" in end_names


def test_graph_api_impact_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = _settings(tmp_path)
    monkeypatch.setenv("ERAHERM_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("ERAHERM_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("ERAHERM_EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("ERAHERM_EXTRACT_ON_REMEMBER", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        ex = client.post(
            "/v1/graph/extract",
            json={
                "user_id": "u_api_g",
                "text": "A服务依赖B服务和Redis。C服务依赖A服务。",
            },
        )
        assert ex.status_code == 200
        assert ex.json()["relations"] >= 2

        impact = client.post(
            "/v1/graph/impact",
            json={
                "user_id": "u_api_g",
                "entity_name": "A服务",
                "direction": "inbound",
                "max_hops": 2,
            },
        )
        assert impact.status_code == 200
        body = impact.json()
        assert body["seed"]["name"] == "A服务"
        flat = [n["name"] for p in body["paths"] for n in p["nodes"]]
        assert "C服务" in flat

        ents = client.get("/v1/graph/entities", params={"user_id": "u_api_g", "q": "A"})
        assert ents.status_code == 200
        assert any(i["name"] == "A服务" for i in ents.json()["items"])

        demo = client.get("/demo/")
        assert demo.status_code == 200
        assert "EraHerm-Memory Demo" in demo.text
    get_settings.cache_clear()
