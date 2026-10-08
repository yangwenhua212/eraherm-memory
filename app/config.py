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
    # 门禁量纲。score = base × (0.15+0.85·rel)，而 base 含 exp(-λ·age) 会随年龄塌陷：
    # 卡绝对分时 age > ~28d 的记忆（即使 relevance=1.0）永远过不了门禁。
    # "relevance" = 门禁只判相关性（与年龄解耦），score 仅用于排序；"score" = 旧行为（回滚开关）。
    recall_gate_mode: str = "relevance"
    recall_rel_min: float = 0.18            # 有词法重叠时的相关性门禁（词法重叠本身已是强证据）
    recall_rel_min_no_lexical: float = 0.55  # 零词法重叠（更严，挡纯向量蹭分）
    # 二段重排：rel 主导、base 小幅加权，否则又长又 pinned 的记忆会压过更相关的短记忆。
    recall_rank_base_weight: float = 0.2
    # base 在候选集内相对归一化（base / max(base)）。不归一化的话 base 是 0.02~0.1 量纲，
    # 乘以 0.2 后比 relevance（0~1）低两个数量级 —— base 项等于不存在。关掉=回到旧行为。
    recall_rank_base_normalize: bool = True
    # 命中增稳（间隔重复的轻量版）：被召回过的记忆衰减变慢，越用越抗忘。
    #   boost = min(1 + alpha·ln(1+access_count), cap)，lambda_eff = lambda / boost
    # 只影响排序（门禁已与年龄解耦，见 ADR 0010/0011），关掉=回到固定半衰期。
    recall_hit_boost_enabled: bool = True
    recall_hit_boost_alpha: float = 0.35
    recall_hit_boost_cap: float = 3.0
    # 硬护栏：任何记忆的有效半衰期不得超过该天数（防「永生条目」）
    recall_max_half_life_days: float = 365.0
    # 词法信号的长度折扣：内容超过该字数后，命中一个词的证据强度按长度线性衰减。
    # 不折扣的话，几千字的「大杂烩」记忆会与几乎所有查询产生词法重叠，绕过词法门禁。
    recall_lexical_len_norm: int = 300
    # pinned（核心记忆：身份/红线/偏好）不参与年龄衰减。
    recall_pinned_no_decay: bool = True
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
