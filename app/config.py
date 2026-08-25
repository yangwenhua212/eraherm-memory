# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ERAHERM_",
        extra="ignore",
    )

    data_dir: Path = Path("./storage")
    database_url: str = "sqlite:///./storage/eraherm.db"
    host: str = "0.0.0.0"
    port: int = 8000

    # memory_policy
    decay_lambda_default: float = 0.05
    promotion_importance_threshold: float = 0.6
    recall_top_k_default: int = 8
    recall_pinned_cap: int = 20
    recall_min_score: float = 0.25  # drop weak hits; 0 = disable gate
    # When query shares no tokens with content, require a higher final score
    # (cuts pure-vector near-misses like「服务器配置」→ 数据库偏好).
    recall_min_score_no_lexical: float = 0.38
    # Mild boost so equally relevant pinned facts win ties (not a hard prepend).
    recall_pinned_score_boost: float = 0.05
    l1_max_items_per_session: int = 200
    extract_on_remember: bool = True
    auto_importance: bool = True
    recall_vector_weight: float = 0.7

    # graph_policy
    graph_max_hops_default: int = 2
    graph_min_extract_confidence: float = 0.5

    # feedback_policy
    reflection_confidence_threshold: float = 0.7
    upvote_weight_delta: float = 0.05
    downvote_weight_delta: float = -0.1
    correct_creates_pinned: bool = True
    downvote_writes_negative_memory: bool = True

    # embedding
    embedding_backend: str = "hashing"  # hashing | openai | fastembed
    embedding_dim: int = 256
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: str | None = None
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_cache_dir: Path | None = None  # fastembed model cache (optional)

    # ops / observability
    admin_token: str = "dev-admin-token"
    log_level: str = "INFO"
    json_logs: bool = True

    # phase 6 backends
    session_cache_backend: str = "memory"  # memory | redis
    redis_url: str = "redis://localhost:6379/0"
    vector_backend: str = "sqlite"  # sqlite | qdrant
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_path: str | None = None  # local path or leave empty + no url => :memory:
    qdrant_collection: str = "eraherm_memories"
    graph_backend: str = "networkx"  # networkx | neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    feedback_async: bool = False

    # LLM for extract / reflection (optional)
    llm_backend: str = "heuristic"  # heuristic | openai
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None  # falls back to embedding_api_key
    llm_base_url: str | None = None  # falls back to embedding_base_url

    # phase 7 proactive (alerts + sidecar recommendations)
    proactive_alerts_enabled: bool = True
    proactive_recommend_enabled: bool = True
    alert_similarity_threshold: float = 0.35
    alert_neighbor_k: int = 8
    alert_scan_limit: int = 40
    alert_max_items: int = 3
    recommend_top_k: int = 3
    recommend_min_score: float = 0.2

    # phase 8 consolidation (forget + compress)
    consolidation_enabled: bool = False  # opt-in scheduler in API process
    consolidation_cron_hour: int = 3  # local hour
    consolidation_cron_minute: int = 0
    consolidation_forget_weight_threshold: float = 0.12
    consolidation_cluster_min_size: int = 3
    consolidation_cluster_similarity: float = 0.45
    consolidation_max_clusters: int = 20
    consolidation_use_llm: bool = False  # heuristic summary by default

    # phase 9 watchdog (主动感知看门狗 — 零 LLM / 零外部 API)
    watchdog_scan_limit: int = 200  # 巡检的记忆条数上限
    watchdog_gem_importance: float = 0.8  # 「从未被用过高价值记忆」的 importance 门槛
    watchdog_max_gems: int = 3
    watchdog_low_weight: float = 0.12  # 低于此 weight 视为待遗忘

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "l3").mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url.removeprefix("sqlite:///"))
            db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
