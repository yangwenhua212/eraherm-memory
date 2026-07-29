# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

"""Minimal Host Agent loop using EraHerm-Memory.

Demonstrates: remember context → recall → (simulate answer) → feedback correct → recall again.

Usage (in-process, no server):
  python examples/minimal_agent.py

Usage (HTTP SDK, requires running server):
  python examples/minimal_agent.py --http http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

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
from app.memory.service import MemoryService
from app.ports.clock import SystemClock


def build_local() -> tuple[MemoryService, FeedbackService, GraphService]:
    tmp = Path(tempfile.mkdtemp(prefix="eraherm-agent-"))
    settings = Settings(
        data_dir=tmp,
        database_url=f"sqlite:///{(tmp / 'agent.db').as_posix()}",
        extract_on_remember=True,
        embedding_dim=128,
        json_logs=False,
        log_level="WARNING",
    )
    settings.ensure_dirs()
    repo = SqliteMemoryRepository(settings.database_url)
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
        clock=SystemClock(),
        embedding=HashingEmbeddingClient(dimensions=128),
        vectors=SqliteVectorStore(settings.database_url, engine=repo.engine),
        graph_service=graph,
    )
    feedback = FeedbackService(
        store=SqliteFeedbackStore(repo.engine),
        memory=memory,
        reflection=HeuristicReflectionPipeline(),
        settings=settings,
        clock=SystemClock(),
    )
    return memory, feedback, graph


def run_local() -> None:
    memory, feedback, graph = build_local()
    user_id = "agent_demo"

    print("== 1) 写入项目事实与依赖 ==")
    memory.remember(
        content="EraHerm 项目使用 FastAPI",
        user_id=user_id,
        importance=0.9,
        extract_graph=True,
    )
    memory.remember(
        content="A服务依赖B服务和Redis。C服务依赖A服务。",
        user_id=user_id,
        importance=0.9,
        extract_graph=True,
    )
    wrong = memory.remember(
        content="数据库使用 MySQL",
        user_id=user_id,
        importance=0.9,
        extract_graph=False,
    )

    print("\n== 2) 提问前召回 ==")
    hits = memory.recall(user_id=user_id, query="数据库用什么")
    for h in hits[:5]:
        print(f"  [{h.layer}] {h.content}")

    print("\n== 3) 模拟错误回答 + 用户纠正 ==")
    answer = "你们用的是 MySQL"
    print(f"  Agent: {answer}")
    fb = feedback.submit(
        user_id=user_id,
        answer_id="ans_demo",
        feedback_type="correct",
        correction_text="应该是 PostgreSQL 不是 MySQL",
        related_memory_ids=[wrong.id],
        answer_text=answer,
        async_mode=False,
    )
    print(f"  feedback={fb.feedback_id} status={fb.reflection.status if fb.reflection else None}")
    print(f"  summary={fb.reflection.summary if fb.reflection else None}")

    print("\n== 4) 纠正后再次召回 ==")
    hits2 = memory.recall(user_id=user_id, query="数据库是 PostgreSQL 吗")
    for h in hits2[:5]:
        print(f"  [{h.layer}] {h.content}")

    print("\n== 5) 改 A 会影响谁 ==")
    impact = graph.impact(user_id=user_id, entity_name="A服务", direction="inbound", max_hops=2)
    for p in impact.paths:
        print("  " + " → ".join(n.name for n in p.nodes))


def run_http(base_url: str) -> None:
    from eraherm_memory import MemoryClient

    user_id = "agent_demo_http"
    with MemoryClient(base_url) as client:
        print("== health ==", client.health())
        client.remember(content="EraHerm 项目使用 FastAPI", user_id=user_id, importance=0.9)
        wrong = client.remember(content="数据库使用 MySQL", user_id=user_id, importance=0.9, extract_graph=False)
        print("recall before:", client.recall(user_id=user_id, query="数据库用什么")["items"][:3])
        fb = client.feedback(
            user_id=user_id,
            answer_id="ans_http",
            feedback_type="correct",
            correction_text="应该是 PostgreSQL 不是 MySQL",
            related_memory_ids=[wrong["id"]],
            answer_text="你们用的是 MySQL",
            async_mode=False,
        )
        print("feedback:", fb)
        print("recall after:", client.recall(user_id=user_id, query="数据库是 PostgreSQL 吗")["items"][:3])
        client.extract_graph(user_id=user_id, text="A服务依赖B服务。C服务依赖A服务。")
        print("impact:", client.impact(user_id=user_id, entity_name="A服务", direction="inbound"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", default=None, help="Base URL for HTTP SDK mode")
    args = parser.parse_args()
    if args.http:
        run_http(args.http)
    else:
        run_local()


if __name__ == "__main__":
    main()
