# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

"""Phase 8: consolidation + MCP tools smoke."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.adapters.memory_session_cache import InMemorySessionCache
from app.adapters.networkx_graph_store import NetworkXSqliteGraphStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.adapters.sqlite_vector_store import SqliteVectorStore
from app.config import Settings
from app.consolidate.service import ConsolidationService, HeuristicSummarizer
from app.graph.extractor import RuleGraphExtractor
from app.graph.service import GraphService
from app.memory.service import MemoryService
from app.ports.clock import Clock


class FixedClock(Clock):
    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self) -> datetime:
        return self._when


def _build(tmp_path: Path) -> tuple[MemoryService, ConsolidationService]:
    db = tmp_path / "c8.db"
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{db.as_posix()}",
        extract_on_remember=False,
        embedding_dim=128,
        consolidation_cluster_min_size=3,
        consolidation_cluster_similarity=0.2,
        consolidation_forget_weight_threshold=0.08,
        json_logs=False,
    )
    repo = SqliteMemoryRepository(settings.database_url)
    vectors = SqliteVectorStore(settings.database_url, engine=repo.engine)
    emb = HashingEmbeddingClient(dimensions=128)
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
        embedding=emb,
        vectors=vectors,
        graph_service=graph,
    )
    cons = ConsolidationService(
        repo=repo,
        memory=memory,
        embedding=emb,
        vectors=vectors,
        settings=settings,
        clock=FixedClock(datetime(2026, 7, 29, tzinfo=timezone.utc)),
        summarizer=HeuristicSummarizer(),
    )
    return memory, cons


def test_conflict_retires_mysql_keeps_postgres(tmp_path: Path):
    memory, cons = _build(tmp_path)
    memory.remember(
        content="数据库使用 MySQL",
        user_id="u8",
        importance=0.9,
        extract_graph=False,
    )
    memory.remember(
        content="应该是 PostgreSQL 不是 MySQL",
        user_id="u8",
        importance=0.95,
        extract_graph=False,
    )
    report = cons.run_for_user("u8")
    assert report.conflicts_resolved >= 1
    rows = memory.repo.list_active_by_user("u8")
    contents = " ".join(r.content for r in rows)
    assert "PostgreSQL" in contents or "postgres" in contents.lower()
    # MySQL-only fact should be gone (or only appear inside correction text)
    active_mysql_only = [
        r for r in rows if "MySQL" in r.content and "PostgreSQL" not in r.content and "不是" not in r.content
    ]
    assert active_mysql_only == []


def test_compress_three_db_memories(tmp_path: Path):
    memory, cons = _build(tmp_path)
    for text in (
        "数据库连接池大小设为 20",
        "数据库超时时间 3 秒，数据库配置要注意",
        "数据库配置使用连接池，避免每次新建连接",
    ):
        memory.remember(content=text, user_id="u8b", importance=0.85, extract_graph=False)
    report = cons.run_for_user("u8b")
    assert report.compressed_clusters >= 1
    assert report.compressed_deleted >= 3
    rows = memory.repo.list_active_by_user("u8b")
    assert any("精华摘要" in r.content for r in rows)


def test_recall_increments_access_count(tmp_path: Path):
    memory, _ = _build(tmp_path)
    r = memory.remember(
        content="核心依赖是 FastAPI",
        user_id="u8c",
        importance=0.9,
        extract_graph=False,
    )
    memory.recall(user_id="u8c", query="核心依赖", top_k=3)
    row = memory.repo.get_memory(r.id)
    assert row is not None
    assert row.access_count >= 1
    assert row.last_accessed_at is not None


def test_mcp_tools_registered():
    from app.mcp_server import create_mcp

    mcp = create_mcp()
    tools = mcp._tool_manager.list_tools()
    names = {t.name for t in tools}
    assert {"remember", "recall", "impact", "consolidate", "health"} <= names
