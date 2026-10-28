# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Sequence

from app.adapters.sqlite_vector_store import cosine
from app.config import Settings
from app.graph.service import GraphService
from app.memory.gate import (
    LEX_EVIDENCE_MIN,
    clamp01,
    length_adjusted_lexical,
    legacy_relevance_floor,
    lexical_similarity,
    passes_recall_gates,
    tokenize,
)
from app.memory.importance import resolve_importance
from app.models import (
    L1Item,
    MemoryRow,
    MemorySource,
    MemoryType,
    SessionRow,
    SessionStatus,
)
from app.observability.logging import logger
from app.ports.clock import Clock
from app.ports.embedding import EmbeddingClient
from app.ports.memory_repo import MemoryRepository
from app.ports.session_cache import SessionCache
from app.ports.vector_store import VectorStore
from app.sensitive import assert_remote_embedding_allowed

if TYPE_CHECKING:
    from app.proactive.service import MemoryAlert, ProactiveService, Recommendation


def parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def age_days(created_at: str, now: datetime) -> float:
    created = parse_iso(created_at)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = now - created
    return max(delta.total_seconds() / 86400.0, 0.0)


def effective_score(
    *,
    importance: float,
    weight: float,
    created_at: str,
    decay_lambda: float,
    now: datetime,
) -> float:
    """effective_score = importance * exp(-λ * age_days) * feedback_boost(weight)."""
    return importance * math.exp(-decay_lambda * age_days(created_at, now)) * weight


def stability_boost(access_count: int, *, alpha: float, cap: float) -> float:
    """命中增稳：被召回过的记忆衰减变慢（间隔重复的轻量版）。

    boost = min(1 + alpha·ln(1+access_count), cap)

    用 ln 而非线性/log2：增长慢且有界，老条目不会变成「永生」。
    命中 0 次 = 1.0（行为与旧版一致）。
    """
    n = max(int(access_count or 0), 0)
    if n == 0 or alpha <= 0:
        return 1.0
    return min(1.0 + alpha * math.log1p(n), cap)


def decay_lambda_for(
    *,
    pinned: bool,
    row_lambda: float | None,
    default_lambda: float,
    pinned_no_decay: bool,
    access_count: int = 0,
    boost_enabled: bool = False,
    boost_alpha: float = 0.35,
    boost_cap: float = 3.0,
    max_half_life_days: float = 365.0,
) -> float:
    """pinned（核心记忆）不参与年龄衰减——兑现 ROADMAP「pinned 永不为衰减」。

    绝对分门禁 + 年龄衰减会让 age > ~28 天的记忆永远召不回（2026-10-08 实测全库召回为空）。
    非 pinned 的记忆按命中次数增稳：λ_eff = λ / boost（见 stability_boost），
    并受 max_half_life_days 硬护栏约束（防「永生条目」）。
    """
    if pinned_no_decay and pinned:
        return 0.0
    lam = default_lambda if row_lambda is None else row_lambda
    if not boost_enabled or lam <= 0:
        return lam
    lam = lam / stability_boost(
        access_count, alpha=boost_alpha, cap=boost_cap
    )
    if max_half_life_days and max_half_life_days > 0:
        # ln2/λ ≤ max → λ ≥ ln2/max（护栏只对「衰减过慢」生效）
        lam = max(lam, math.log(2) / max_half_life_days)
    return lam


@dataclass
class RememberResult:
    id: str
    layer: str
    pinned: bool
    entities_extracted: int = 0
    relations_extracted: int = 0
    importance: float = 0.0
    alerts: list[MemoryAlert] = field(default_factory=list)
    #: 是否真的落库了。以前这个信息不存在：重要度不足且没有 session_id 时，
    #: ``remember`` 会返回 201 + 一个 id，但其实**什么都没写**，调用方无从得知。
    persisted: bool = True
    #: 未落库的原因（persisted=False 时给出可操作的说明）
    drop_reason: str | None = None


@dataclass
class RecallItem:
    id: str
    content: str
    memory_type: str
    score: float
    pinned: bool
    layer: str
    relevance: float = 0.0
    lexical: float = 0.0
    vector_sim: float = 0.0
    base: float = 1.0
    hit_boost: float = 1.0
    decay_lambda_eff: float = 0.0


@dataclass
class CloseSessionResult:
    id: str
    status: str
    promoted_count: int
    dropped_count: int


class MemoryService:
    def __init__(
        self,
        *,
        repo: MemoryRepository,
        cache: SessionCache,
        settings: Settings,
        clock: Clock,
        embedding: EmbeddingClient,
        vectors: VectorStore,
        graph_service: GraphService | None = None,
        proactive: ProactiveService | None = None,
    ) -> None:
        self.repo = repo
        self.cache = cache
        self.settings = settings
        self.clock = clock
        self.embedding = embedding
        self.vectors = vectors
        self.graph_service = graph_service
        self.proactive = proactive

    def create_session(
        self,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> SessionRow:
        row = SessionRow(
            user_id=user_id,
            tenant_id=tenant_id,
            meta_json=json.dumps(meta or {}, ensure_ascii=False),
            created_at=self._now_iso(),
        )
        return self.repo.create_session(row)

    def close_session(self, session_id: str, *, user_id: str | None = None) -> CloseSessionResult:
        session = self.repo.get_session(session_id)
        if session is None:
            raise KeyError(f"session not found: {session_id}")
        if user_id and session.user_id and session.user_id != user_id:
            raise PermissionError(f"session {session_id} belongs to another user")
        if session.status == SessionStatus.CLOSED.value:
            raise ValueError(f"session already closed: {session_id}")

        now = self.clock.now()
        items = self.cache.list(session_id)
        promoted = 0
        dropped = 0
        threshold = self.settings.promotion_importance_threshold
        lam = self.settings.decay_lambda_default

        for item in items:
            score = effective_score(
                importance=item.importance,
                weight=item.weight,
                created_at=item.created_at,
                decay_lambda=lam,
                now=now,
            )
            if item.pinned or score >= threshold:
                self._write_l2_from_l1(item, source=MemorySource.PROMOTION.value)
                promoted += 1
            else:
                dropped += 1

        self.cache.clear(session_id)
        session.status = SessionStatus.CLOSED.value
        session.closed_at = self._now_iso()
        self.repo.save_session(session)
        return CloseSessionResult(
            id=session.id,
            status=session.status,
            promoted_count=promoted,
            dropped_count=dropped,
        )

    def remember(
        self,
        *,
        content: str,
        user_id: str | None = None,
        tenant_id: str | None = None,
        session_id: str | None = None,
        memory_type: str = MemoryType.FACT.value,
        importance: float = 0.5,
        pinned: bool = False,
        extract_graph: bool | None = None,
        meta: dict[str, Any] | None = None,
    ) -> RememberResult:
        if pinned and memory_type in {MemoryType.IDENTITY.value, MemoryType.PREFERENCE.value}:
            pinned = True

        importance = resolve_importance(
            content=content,
            memory_type=memory_type,
            pinned=pinned,
            provided=importance,
            auto=self.settings.auto_importance,
        )

        item = L1Item(
            content=content,
            memory_type=memory_type,
            importance=importance,
            pinned=pinned,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            meta=meta,
            created_at=self._now_iso(),
        )

        write_l2 = pinned or importance >= self.settings.promotion_importance_threshold
        persisted = True
        drop_reason: str | None = None
        if session_id:
            self.cache.append(session_id, item)
            self.cache.drop_lowest(session_id, self.settings.l1_max_items_per_session)

        if write_l2:
            self._assert_embeddable(content)
            row = self._write_l2_from_l1(item, source=MemorySource.INGEST.value)
            layer = "L2"
            mem_id = row.id
        else:
            layer = "L1"
            mem_id = item.id
            # 关键：没有 session_id 时 L1 只是「会话热数据」，不会落盘。
            # 以前这里静默返回成功，调用方以为存下了。
            if not session_id:
                persisted = False
                drop_reason = (
                    "importance "
                    f"{importance:.2f} < promotion_importance_threshold "
                    f"{self.settings.promotion_importance_threshold:.2f} and no session_id: "
                    "nothing was persisted. Pass session_id, raise importance, or set pinned=True."
                )
                logger.warning(
                    "memory_not_persisted",
                    extra={
                        "reason": drop_reason,
                        "user_id": user_id,
                        "memory_type": memory_type,
                        "layer": layer,
                    },
                )

        do_extract = (
            extract_graph if extract_graph is not None else self.settings.extract_on_remember
        )
        entities_n = 0
        relations_n = 0
        if do_extract and self.graph_service is not None and user_id:
            ingested = self.graph_service.extract_and_ingest(
                user_id=user_id,
                text=content,
                tenant_id=tenant_id,
                source_memory_id=mem_id if layer == "L2" else None,
            )
            entities_n = ingested.entities
            relations_n = ingested.relations

        alerts: list[MemoryAlert] = []
        if self.proactive is not None and user_id:
            alerts = self.proactive.detect_alerts(
                user_id=user_id,
                content=content,
                exclude_memory_id=mem_id if layer == "L2" else None,
                tenant_id=tenant_id,
            )

        return RememberResult(
            id=mem_id,
            layer=layer,
            pinned=pinned,
            importance=importance,
            entities_extracted=entities_n,
            relations_extracted=relations_n,
            alerts=alerts,
            persisted=persisted,
            drop_reason=drop_reason,
        )

    def pin_existing(
        self, memory_id: str, pinned: bool = True, *, user_id: str | None = None
    ) -> MemoryRow:
        row = self.repo.get_memory(memory_id)
        if row is None or row.deleted_at is not None:
            raise KeyError(f"memory not found: {memory_id}")
        # 归属校验：以前任何调用方拿到 memory_id 就能改别人的 pin 状态。
        if user_id and row.user_id and row.user_id != user_id:
            raise PermissionError(f"memory {memory_id} belongs to another user")
        row.pinned = pinned
        row.updated_at = self._now_iso()
        saved = self.repo.save_memory(row)
        # Ensure pinned L2 has an embedding for semantic recall.
        self._embed_memory(saved)
        return saved

    def pin_new(
        self,
        *,
        content: str,
        user_id: str,
        memory_type: str = MemoryType.IDENTITY.value,
        tenant_id: str | None = None,
        session_id: str | None = None,
        importance: float = 1.0,
        meta: dict[str, Any] | None = None,
    ) -> RememberResult:
        return self.remember(
            content=content,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            memory_type=memory_type,
            importance=importance,
            pinned=True,
            meta=meta,
        )

    def recall(
        self,
        *,
        user_id: str,
        query: str,
        session_id: str | None = None,
        tenant_id: str | None = None,
        top_k: int | None = None,
        include_pinned: bool = True,
        min_score: float | None = None,
    ) -> list[RecallItem]:
        top_k = top_k or self.settings.recall_top_k_default
        threshold = self.settings.recall_min_score if min_score is None else min_score
        now = self.clock.now()
        lam = self.settings.decay_lambda_default
        pinned_no_decay = self.settings.recall_pinned_no_decay
        hit_boost_enabled = bool(self.settings.recall_hit_boost_enabled)
        hit_boost_alpha = self.settings.recall_hit_boost_alpha
        hit_boost_cap = self.settings.recall_hit_boost_cap
        max_half_life_days = self.settings.recall_max_half_life_days
        base_normalize = bool(self.settings.recall_rank_base_normalize)
        exclude_superseded = bool(self.settings.recall_exclude_superseded)
        gate_mode = (self.settings.recall_gate_mode or "relevance").strip().lower()
        tokens = tokenize(query)
        self._assert_embeddable(query)
        query_vec = self.embedding.embed([query])[0]
        vector_weight = self.settings.recall_vector_weight
        lexical_weight = 1.0 - vector_weight

        by_id: dict[str, RecallItem] = {}

        # L2 via vector search (semantic)
        hits = self.vectors.search(
            query=query_vec,
            user_id=user_id,
            top_k=max(top_k * 3, 20),
            # 租户必须**在检索层**过滤；事后过滤会让别的租户占满 top-k → 召回空
            tenant_id=tenant_id,
        )
        hit_ids = [h.memory_id for h in hits]
        hit_scores = {h.memory_id: h.score for h in hits}
        rows = self.repo.get_memories_by_ids(hit_ids)
        row_map = {r.id: r for r in rows if r.deleted_at is None}
        if tenant_id is not None:
            row_map = {k: v for k, v in row_map.items() if v.tenant_id == tenant_id}
        if exclude_superseded:
            # 已被取代的记忆不再参与竞争（但没被删除：历史可审计、可回滚）
            row_map = {k: v for k, v in row_map.items() if not v.superseded_by}

        # 词法信号按内容长度折扣（防长文「大杂烩」绕过门禁）
        lex_norm = self.settings.recall_lexical_len_norm

        def _lex_of(content: str) -> float:
            return length_adjusted_lexical(
                lexical_similarity(content, tokens), len(content), lex_norm
            )

        for mid, row in row_map.items():
            boost_f = stability_boost(
                row.access_count, alpha=hit_boost_alpha, cap=hit_boost_cap
            ) if hit_boost_enabled else 1.0
            decay = decay_lambda_for(
                pinned=row.pinned,
                row_lambda=row.decay_lambda,
                default_lambda=lam,
                pinned_no_decay=pinned_no_decay,
                access_count=row.access_count,
                boost_enabled=hit_boost_enabled,
                boost_alpha=hit_boost_alpha,
                boost_cap=hit_boost_cap,
                max_half_life_days=max_half_life_days,
            )
            base = effective_score(
                importance=row.importance,
                weight=row.weight,
                created_at=row.created_at,
                decay_lambda=decay,
                now=now,
            )
            sim = clamp01(hit_scores.get(mid, 0.0))
            lex = _lex_of(row.content)
            relevance = vector_weight * sim + lexical_weight * lex
            score = base * (0.15 + 0.85 * relevance)
            by_id[mid] = RecallItem(
                id=row.id,
                content=row.content,
                memory_type=row.memory_type,
                score=score,
                pinned=row.pinned,
                layer="L2",
                relevance=relevance,
                lexical=lex,
                vector_sim=sim,
                base=base,
                hit_boost=boost_f,
                decay_lambda_eff=decay,
            )

        # Also include pinned L2 not returned by vector top list
        if include_pinned:
            pinned_rows = [
                row
                for row in self.repo.list_active_by_user(
                    user_id,
                    tenant_id=tenant_id,
                    pinned_only=True,
                    limit=self.settings.recall_pinned_cap,
                )
                if row.id not in by_id
            ]
            # 一次批量嵌入，而不是每行一次（openai 后端下每行一次 = 一次 TLS 握手 + 一次计费调用）
            pinned_vecs = (
                self.embedding.embed([row.content for row in pinned_rows])
                if pinned_rows
                else []
            )
            for row, row_vec in zip(pinned_rows, pinned_vecs):
                boost_f = stability_boost(
                    row.access_count, alpha=hit_boost_alpha, cap=hit_boost_cap
                ) if hit_boost_enabled else 1.0
                decay = decay_lambda_for(
                    pinned=row.pinned,
                    row_lambda=row.decay_lambda,
                    default_lambda=lam,
                    pinned_no_decay=pinned_no_decay,
                    access_count=row.access_count,
                    boost_enabled=hit_boost_enabled,
                    boost_alpha=hit_boost_alpha,
                    boost_cap=hit_boost_cap,
                    max_half_life_days=max_half_life_days,
                )
                base = effective_score(
                    importance=row.importance,
                    weight=row.weight,
                    created_at=row.created_at,
                    decay_lambda=decay,
                    now=now,
                )
                sim = clamp01(cosine(query_vec, row_vec))
                lex = _lex_of(row.content)
                relevance = vector_weight * sim + lexical_weight * lex
                by_id[row.id] = RecallItem(
                    id=row.id,
                    content=row.content,
                    memory_type=row.memory_type,
                    score=base * (0.15 + 0.85 * relevance),
                    pinned=True,
                    layer="L2",
                    relevance=relevance,
                    lexical=lex,
                    vector_sim=sim,
                    base=base,
                    hit_boost=boost_f,
                    decay_lambda_eff=decay,
                )

        # L1 session items (on-the-fly embedding)
        if session_id:
            # 归属校验：带上别人的 session_id 就能读到别人的 L1 原文。
            session_row = self.repo.get_session(session_id)
            if (
                session_row is not None
                and session_row.user_id
                and session_row.user_id != user_id
            ):
                logger.warning(
                    "l1_recall_skipped_foreign_session",
                    extra={"user_id": user_id, "detail": f"session {session_id}"},
                )
                session_id = None
        if session_id:
            l1_items = list(self.cache.list(session_id))
            l1_vecs = (
                self.embedding.embed([item.content for item in l1_items]) if l1_items else []
            )
            for item, item_vec in zip(l1_items, l1_vecs):
                # L1 会话条目没有 access_count → 不参与命中增稳（boost 恒为 1.0）
                decay = decay_lambda_for(
                    pinned=item.pinned,
                    row_lambda=None,
                    default_lambda=lam,
                    pinned_no_decay=pinned_no_decay,
                )
                base = effective_score(
                    importance=item.importance,
                    weight=item.weight,
                    created_at=item.created_at,
                    decay_lambda=decay,
                    now=now,
                )
                sim = clamp01(cosine(query_vec, item_vec))
                lex = _lex_of(item.content)
                relevance = vector_weight * clamp01(sim) + lexical_weight * lex
                score = base * (0.15 + 0.85 * relevance)
                # Prefer L2 entry if same id already promoted
                if item.id in by_id and by_id[item.id].layer == "L2":
                    continue
                by_id[item.id] = RecallItem(
                    id=item.id,
                    content=item.content,
                    memory_type=item.memory_type,
                    score=score,
                    pinned=item.pinned,
                    layer="L1",
                    relevance=relevance,
                    lexical=lex,
                    vector_sim=sim,
                    base=base,
                    decay_lambda_eff=decay,
                )

        boost = self.settings.recall_pinned_score_boost
        no_lex_floor = self.settings.recall_min_score_no_lexical
        # 门禁量纲：relevance 模式只判相关性（与年龄解耦）；score 模式为旧行为（回滚开关）。
        rel_min = self.settings.recall_rel_min
        rel_min_no_lex = self.settings.recall_rel_min_no_lexical
        if gate_mode == "relevance":
            # 兼容旧的绝对分门禁配置：按「默认点」比例折算到相关性空间。
            # 旧实现 rel=(score-0.15)/0.85 在默认值处不连续（0.25→0.18 而 0.26→0.129），
            # 于是「调高门禁」反而放宽了门禁 —— 详见 app/memory/gate.py 模块 docstring。
            rel_min = legacy_relevance_floor(
                self.settings.recall_min_score,
                score_default=_DEFAULT_MIN_SCORE,
                relevance_default=self.settings.recall_rel_min,
            )
            rel_min_no_lex = legacy_relevance_floor(
                self.settings.recall_min_score_no_lexical,
                score_default=_DEFAULT_MIN_SCORE_NO_LEXICAL,
                relevance_default=self.settings.recall_rel_min_no_lexical,
            )
            if min_score is not None:
                if min_score <= 0:
                    rel_min = 0.0
                    rel_min_no_lex = 0.0
                else:
                    rel_min = max(rel_min, min_score)
        candidates = [
            c
            for c in by_id.values()
            if passes_recall_gates(
                score=c.score,
                relevance=c.relevance,
                lexical=c.lexical,
                min_score=threshold if gate_mode == "score" else rel_min,
                min_score_no_lexical=(
                    no_lex_floor if gate_mode == "score" else rel_min_no_lex
                ),
                mode="score" if gate_mode == "score" else "relevance",
            )
        ]
        # Rank by score; pinned only gets a mild tie-break boost (no hard prepend —
        # avoids identity/db/food pinned fighting for unrelated queries).
        if not include_pinned:
            candidates = [c for c in candidates if not c.pinned]
        if gate_mode == "relevance":
            # 二段重排：relevance 主导 + base 小幅加权。时间/重要度只影响名次，不再决定生死。
            # base 是 0.02~0.1 量纲，直接乘权重会低 relevance 两个数量级（等于没参与排序），
            # 故在候选集内相对归一化后加权：base 项铺满 [0, base_w]，且永远压不过 relevance。
            base_w = self.settings.recall_rank_base_weight
            if base_normalize and candidates:
                bmax = max(max(c.base, 0.0) for c in candidates)
                if bmax <= 0:
                    bmax = 1.0
            else:
                bmax = 1.0

            def _rank_key(x: RecallItem) -> float:
                b = max(x.base, 0.0)
                if base_normalize:
                    b = min(b / bmax, 1.0)
                else:
                    b = min(b, 1.0)
                return (
                    x.relevance
                    + base_w * b
                    + (boost if x.pinned and include_pinned else 0.0)
                )

            candidates.sort(key=_rank_key, reverse=True)
        else:
            candidates.sort(
                key=lambda x: x.score + (boost if x.pinned and include_pinned else 0.0),
                reverse=True,
            )
        result = candidates[:top_k]

        self._touch_access([i.id for i in result if i.layer == "L2"])
        return result

    def _touch_access(self, memory_ids: Sequence[str]) -> None:
        """命中计数 +1。

        以前是「逐条 get_memory → 改字段 → save_memory（merge 整行）」：
        默认 top_k=8 就是 8 次 SELECT + 8 个写事务，而且整行回写会把并发写者
        （例如 feedback 改过的 weight）用陈旧快照覆盖掉。现在一条 UPDATE 搞定。
        """
        if not memory_ids:
            return
        self.repo.bump_access(list(memory_ids), self._now_iso())

    def recommend_sidecar(
        self,
        *,
        user_id: str,
        query: str,
        exclude_memory_ids: list[str] | None = None,
        top_k: int | None = None,
        reason: str = "similar_topic",
        tenant_id: str | None = None,
    ) -> list[Recommendation]:
        if self.proactive is None:
            return []
        return self.proactive.recommend(
            user_id=user_id,
            query=query,
            exclude_memory_ids=exclude_memory_ids,
            top_k=top_k,
            reason=reason,
            tenant_id=tenant_id,
        )

    def apply_decay_deletions(
        self,
        *,
        user_id: str,
        score_threshold: float = 0.05,
        tenant_id: str | None = None,
    ) -> int:
        """Soft-delete non-pinned L2 memories below effective score threshold."""
        now = self.clock.now()
        lam = self.settings.decay_lambda_default
        rows = self.repo.list_active_by_user(user_id, tenant_id=tenant_id)
        to_delete: list[str] = []
        for row in rows:
            if row.pinned:
                continue
            # 与召回路径共用同一套衰减语义（命中增稳 + 半衰期护栏）。
            # 以前这里直接用 row.decay_lambda，忽略 boost 和护栏 —— 同一个库两套衰减标准。
            decay = decay_lambda_for(
                pinned=row.pinned,
                row_lambda=row.decay_lambda,
                default_lambda=lam,
                pinned_no_decay=self.settings.recall_pinned_no_decay,
                access_count=row.access_count,
                boost_enabled=bool(self.settings.recall_hit_boost_enabled),
                boost_alpha=self.settings.recall_hit_boost_alpha,
                boost_cap=self.settings.recall_hit_boost_cap,
                max_half_life_days=self.settings.recall_max_half_life_days,
            )
            score = effective_score(
                importance=row.importance,
                weight=row.weight,
                created_at=row.created_at,
                decay_lambda=decay,
                now=now,
            )
            if score < score_threshold:
                to_delete.append(row.id)
        deleted = self.repo.soft_delete_memories(to_delete, self._now_iso())
        if to_delete:
            self.vectors.delete(to_delete)
        return deleted

    def adjust_weights(
        self, memory_ids: Sequence[str], *, delta: float, user_id: str | None = None
    ) -> int:
        """Apply feedback weight delta to existing L2 memories. Returns updated count.

        单条 UPDATE（带夹取），不再逐行读改写：避免与 recall 的整行回写互相覆盖。
        传入 ``user_id`` 时会跳过不属于该用户的记忆（防止用别人的 memory_id 调权重）。
        """
        ids = [m for m in memory_ids if m]
        if not ids or delta == 0:
            return 0
        if user_id:
            allowed: list[str] = []
            for mid in ids:
                row = self.repo.get_memory(mid)
                if row is None or row.deleted_at is not None:
                    continue
                if row.user_id and row.user_id != user_id:
                    logger.warning(
                        "weight_update_skipped_foreign_memory",
                        extra={"memory_id": mid, "user_id": user_id},
                    )
                    continue
                allowed.append(mid)
            ids = allowed
            if not ids:
                return 0
        return self.repo.add_weight(ids, delta=delta, updated_at=self._now_iso())

    def supersede_memories(self, memory_ids: Sequence[str], *, superseded_by: str) -> int:
        """把被纠正的旧记忆标记为「已被取代」（ADR 0013）。

        **不删除**：历史仍可审计、可回滚；只是召回默认跳过它们
        （``ERAHERM_RECALL_EXCLUDE_SUPERSEDED``）。
        """
        ids = [m for m in memory_ids if m and m != superseded_by]
        if not ids:
            return 0
        return self.repo.supersede(
            ids, superseded_by=superseded_by, superseded_at=self._now_iso()
        )

    def reembed_memories(self, memory_ids: Sequence[str]) -> int:
        """为已存在的记忆重建向量（恢复归档 / 修复缺失向量时用）。

        单条失败不影响其它条目：只记日志并继续（该条仍可被词法路径召回）。
        """
        done = 0
        for mid in memory_ids:
            row = self.repo.get_memory(mid)
            if row is None or row.deleted_at is not None:
                continue
            try:
                self._embed_memory(row)
                done += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "reembed_failed",
                    extra={"memory_id": mid, "detail": str(exc)[:200]},
                )
        return done

    def restore_memories(self, memory_ids: Sequence[str]) -> int:
        """恢复被软删的记忆，并重新建立向量。返回恢复条数。

        这是「整理误删」的兜底出口：consolidate 会软删冲突/低权重条目且不删向量，
        没有这个接口就只能手改数据库。
        """
        ids = [m for m in memory_ids if m]
        if not ids:
            return 0
        restored = self.repo.restore_memories(ids)
        self.reembed_memories(ids)
        return restored

    def _write_l2_from_l1(self, item: L1Item, *, source: str) -> MemoryRow:
        now = self._now_iso()
        row = MemoryRow(
            id=item.id,
            tenant_id=item.tenant_id,
            user_id=item.user_id,
            session_id=item.session_id,
            content=item.content,
            memory_type=item.memory_type,
            importance=item.importance,
            weight=item.weight,
            pinned=item.pinned,
            source=source,
            meta_json=json.dumps(item.meta, ensure_ascii=False),
            created_at=item.created_at,
            updated_at=now,
        )
        existing = self.repo.get_memory(item.id)
        if existing is None:
            saved = self.repo.create_memory(row)
        else:
            saved = self.repo.save_memory(row)
        self._embed_memory(saved)
        return saved

    def _embed_memory(self, row: MemoryRow) -> None:
        self._assert_embeddable(row.content)
        vector = self.embedding.embed([row.content])[0]
        self.vectors.upsert(
            memory_id=row.id,
            user_id=row.user_id,
            vector=vector,
            model=self.embedding.model_name,
            tenant_id=row.tenant_id,
        )

    def _assert_embeddable(self, *texts: str) -> None:
        """远端 embedding + 敏感内容 = 拒绝外发（fail-closed）。

        以前这份词表只挡 LLM 抽取/反射，而 ``embedding_backend=openai`` 会把
        记忆正文原样发给外部服务 —— 于是「敏感内容绝不出网」是假的。现在
        在入口就把这条承诺变成真的：要么换本地 embedding，要么显式关掉这个开关。
        """
        assert_remote_embedding_allowed(
            list(texts),
            is_remote=bool(getattr(self.embedding, "is_remote", False)),
            enforced=bool(self.settings.sensitive_requires_local_embedding),
        )

    def _now_iso(self) -> str:
        return self.clock.now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


# 旧门禁配置的默认值：作为「旧绝对分配置 → 相关性门禁」折算的锚点
_DEFAULT_MIN_SCORE = float(Settings.model_fields["recall_min_score"].default)
_DEFAULT_MIN_SCORE_NO_LEXICAL = float(
    Settings.model_fields["recall_min_score_no_lexical"].default
)


# --- 向后兼容别名 ---------------------------------------------------------
# 这些名字以前定义在本模块，测试与示例仍按旧名导入。实现已迁到 app/memory/gate.py。
_tokenize = tokenize
_lexical_similarity = lexical_similarity
_clamp01 = clamp01
_length_adjusted_lexical = length_adjusted_lexical
_passes_recall_gates = passes_recall_gates
_LEX_EVIDENCE_MIN = LEX_EVIDENCE_MIN

