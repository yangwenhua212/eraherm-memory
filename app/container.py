# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from dataclasses import dataclass

from app.adapters.filesystem_archive import FilesystemArchiveStore
from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.adapters.memory_job_queue import InMemoryJobQueue
from app.adapters.memory_session_cache import InMemorySessionCache
from app.adapters.networkx_graph_store import NetworkXSqliteGraphStore
from app.adapters.openai_embedding import OpenAICompatibleEmbeddingClient
from app.adapters.sqlite_feedback_store import SqliteFeedbackStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.adapters.sqlite_vector_store import SqliteVectorStore
from app.archive.service import L3ArchiveService
from app.config import Settings, get_settings
from app.feedback.service import FeedbackService
from app.graph.service import GraphService
from app.memory.service import MemoryService
from app.observability.logging import setup_logging
from app.ports.clock import SystemClock
from app.ports.embedding import EmbeddingClient
from app.ports.graph_store import GraphStore
from app.ports.session_cache import SessionCache
from app.ports.vector_store import VectorStore
from app.proactive.service import ProactiveService
from app.consolidate.service import ConsolidationService, HeuristicSummarizer, LLMSummarizer


@dataclass
class Container:
    settings: Settings
    memory_service: MemoryService
    graph_service: GraphService
    feedback_service: FeedbackService
    l3_service: L3ArchiveService
    proactive_service: ProactiveService | None = None
    consolidation_service: ConsolidationService | None = None
    job_queue: InMemoryJobQueue | None = None
    scheduler: object | None = None


def build_embedding_client(settings: Settings) -> EmbeddingClient:
    backend = settings.embedding_backend.lower().strip()
    if backend == "openai":
        if not settings.embedding_api_key:
            raise ValueError("ERAHERM_EMBEDDING_API_KEY required when embedding_backend=openai")
        return OpenAICompatibleEmbeddingClient(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            dimensions=settings.embedding_dim,
        )
    if backend == "fastembed":
        from app.adapters.fastembed_embedding import (
            DEFAULT_FASTEMBED_MODEL,
            FastEmbedEmbeddingClient,
        )

        model = settings.embedding_model.strip()
        # Keep openai default model name from leaking into local ONNX path.
        if model in ("", "text-embedding-3-small", "hashing-v1"):
            model = DEFAULT_FASTEMBED_MODEL
        cache = str(settings.embedding_cache_dir) if settings.embedding_cache_dir else None
        return FastEmbedEmbeddingClient(
            model_name=model,
            dimensions=settings.embedding_dim,
            cache_dir=cache,
        )
    return HashingEmbeddingClient(dimensions=settings.embedding_dim)


def build_session_cache(settings: Settings) -> SessionCache:
    backend = settings.session_cache_backend.lower().strip()
    if backend == "redis":
        from app.adapters.redis_session_cache import RedisSessionCache

        return RedisSessionCache(url=settings.redis_url)
    return InMemorySessionCache()


def build_vector_store(settings: Settings, *, engine) -> VectorStore:
    backend = settings.vector_backend.lower().strip()
    if backend == "qdrant":
        from app.adapters.qdrant_vector_store import QdrantVectorStore

        return QdrantVectorStore(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            path=settings.qdrant_path,
            collection=settings.qdrant_collection,
            vector_size=settings.embedding_dim,
        )
    return SqliteVectorStore(settings.database_url, engine=engine)


def build_graph_store(settings: Settings, *, engine) -> GraphStore:
    backend = settings.graph_backend.lower().strip()
    if backend == "neo4j":
        from app.adapters.neo4j_graph_store import Neo4jGraphStore

        return Neo4jGraphStore(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
        )
    return NetworkXSqliteGraphStore(engine)


def build_graph_extractor(settings: Settings):
    from app.graph.extractor import RuleGraphExtractor

    rules = RuleGraphExtractor(min_confidence=settings.graph_min_extract_confidence)
    if settings.llm_backend.lower().strip() != "openai":
        return rules
    api_key = settings.llm_api_key or settings.embedding_api_key
    if not api_key:
        return rules
    from app.adapters.llm_graph_extractor import FallbackGraphExtractor, LLMGraphExtractor
    from app.adapters.openai_llm import OpenAICompatibleLLM

    llm = OpenAICompatibleLLM(
        api_key=api_key,
        base_url=settings.llm_base_url or settings.embedding_base_url,
        model=settings.llm_model,
    )
    return FallbackGraphExtractor(
        LLMGraphExtractor(llm, min_confidence=settings.graph_min_extract_confidence),
        fallback=rules,
    )


def build_reflection_pipeline(settings: Settings):
    from app.adapters.heuristic_reflection import HeuristicReflectionPipeline

    if settings.llm_backend.lower().strip() != "openai":
        return HeuristicReflectionPipeline()
    api_key = settings.llm_api_key or settings.embedding_api_key
    if not api_key:
        return HeuristicReflectionPipeline()
    from app.adapters.llm_reflection import LLMReflectionPipeline
    from app.adapters.openai_llm import OpenAICompatibleLLM

    llm = OpenAICompatibleLLM(
        api_key=api_key,
        base_url=settings.llm_base_url or settings.embedding_base_url,
        model=settings.llm_model,
    )
    return LLMReflectionPipeline(llm)


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()
    settings.ensure_dirs()
    setup_logging(level=settings.log_level, json_logs=settings.json_logs)

    repo = SqliteMemoryRepository(settings.database_url)
    vectors = build_vector_store(settings, engine=repo.engine)
    graph_store = build_graph_store(settings, engine=repo.engine)
    feedback_store = SqliteFeedbackStore(repo.engine)
    from sqlmodel import SQLModel
    from app.models import L3ArchiveRow  # noqa: F401

    SQLModel.metadata.create_all(repo.engine)

    extractor = build_graph_extractor(settings)
    graph_service = GraphService(
        store=graph_store,
        extractor=extractor,
        settings=settings,
        memory_repo=repo,
    )
    cache = build_session_cache(settings)
    clock = SystemClock()
    embedding = build_embedding_client(settings)
    proactive = ProactiveService(
        repo=repo,
        embedding=embedding,
        vectors=vectors,
        settings=settings,
    )
    memory_service = MemoryService(
        repo=repo,
        cache=cache,
        settings=settings,
        clock=clock,
        embedding=embedding,
        vectors=vectors,
        graph_service=graph_service,
        proactive=proactive,
    )

    feedback_service = FeedbackService(
        store=feedback_store,
        memory=memory_service,
        reflection=build_reflection_pipeline(settings),
        settings=settings,
        clock=clock,
        job_queue=None,
    )
    job_queue = None
    if settings.feedback_async:
        job_queue = InMemoryJobQueue(handler=feedback_service.process_job)
        feedback_service.job_queue = job_queue

    l3_service = L3ArchiveService(
        engine=repo.engine,
        archive_store=FilesystemArchiveStore(settings.data_dir / "l3"),
    )

    summarizer: HeuristicSummarizer | LLMSummarizer = HeuristicSummarizer()
    if settings.consolidation_use_llm and settings.llm_backend.lower().strip() == "openai":
        api_key = settings.llm_api_key or settings.embedding_api_key
        if api_key:
            from app.adapters.openai_llm import OpenAICompatibleLLM

            summarizer = LLMSummarizer(
                OpenAICompatibleLLM(
                    api_key=api_key,
                    base_url=settings.llm_base_url or settings.embedding_base_url,
                    model=settings.llm_model,
                )
            )

    consolidation_service = ConsolidationService(
        repo=repo,
        memory=memory_service,
        embedding=embedding,
        vectors=vectors,
        settings=settings,
        clock=clock,
        summarizer=summarizer,
    )

    scheduler = None
    if settings.consolidation_enabled:
        from app.consolidate.scheduler import start_consolidation_scheduler

        scheduler = start_consolidation_scheduler(consolidation_service, settings)

    return Container(
        settings=settings,
        memory_service=memory_service,
        graph_service=graph_service,
        feedback_service=feedback_service,
        l3_service=l3_service,
        proactive_service=proactive,
        consolidation_service=consolidation_service,
        job_queue=job_queue,
        scheduler=scheduler,
    )
