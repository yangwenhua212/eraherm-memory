# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Sequence

from app.adapters.sqlite_vector_store import cosine
from app.config import Settings
from app.graph.service import GraphService
from app.memory.importance import resolve_importance
from app.models import (
    L1Item,
    MemoryRow,
    MemorySource,
    MemoryType,
    SessionRow,
    SessionStatus,
)
from app.ports.clock import Clock
from app.ports.embedding import EmbeddingClient
from app.ports.memory_repo import MemoryRepository
from app.ports.session_cache import SessionCache
from app.ports.vector_store import VectorStore

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


def decay_lambda_for(
    *,
    pinned: bool,
    row_lambda: float | None,
    default_lambda: float,
    pinned_no_decay: bool,
) -> float:
    """pinned（核心记忆）不参与年龄衰减——兑现 ROADMAP「pinned 永不为衰减」。

    绝对分门禁 + 年龄衰减会让 age > ~28 天的记忆永远召不回（2026-10-08 实测全库召回为空）。
    """
    if pinned_no_decay and pinned:
        return 0.0
    return default_lambda if row_lambda is None else row_lambda


@dataclass
class RememberResult:
    id: str
    layer: str
    pinned: bool
    entities_extracted: int = 0
    relations_extracted: int = 0
    importance: float = 0.0
    alerts: list[MemoryAlert] = field(default_factory=list)


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

    def close_session(self, session_id: str) -> CloseSessionResult:
        session = self.repo.get_session(session_id)
        if session is None:
            raise KeyError(f"session not found: {session_id}")
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
        if session_id:
            self.cache.append(session_id, item)
            self.cache.drop_lowest(session_id, self.settings.l1_max_items_per_session)

        if write_l2:
            row = self._write_l2_from_l1(item, source=MemorySource.INGEST.value)
            layer = "L2"
            mem_id = row.id
        else:
            layer = "L1"
            mem_id = item.id

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
        )

    def pin_existing(self, memory_id: str, pinned: bool = True) -> MemoryRow:
        row = self.repo.get_memory(memory_id)
        if row is None or row.deleted_at is not None:
            raise KeyError(f"memory not found: {memory_id}")
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
        gate_mode = (self.settings.recall_gate_mode or "relevance").strip().lower()
        tokens = _tokenize(query)
        query_vec = self.embedding.embed([query])[0]
        vector_weight = self.settings.recall_vector_weight
        lexical_weight = 1.0 - vector_weight

        by_id: dict[str, RecallItem] = {}

        # L2 via vector search (semantic)
        hits = self.vectors.search(
            query=query_vec,
            user_id=user_id,
            top_k=max(top_k * 3, 20),
        )
        hit_ids = [h.memory_id for h in hits]
        hit_scores = {h.memory_id: h.score for h in hits}
        rows = self.repo.get_memories_by_ids(hit_ids)
        row_map = {r.id: r for r in rows if r.deleted_at is None}
        if tenant_id is not None:
            row_map = {k: v for k, v in row_map.items() if v.tenant_id == tenant_id}

        # 词法信号按内容长度折扣（防长文「大杂烩」绕过门禁）
        lex_norm = self.settings.recall_lexical_len_norm

        def _lex_of(content: str) -> float:
            return _length_adjusted_lexical(
                _lexical_similarity(content, tokens), len(content), lex_norm
            )

        for mid, row in row_map.items():
            decay = decay_lambda_for(
                pinned=row.pinned,
                row_lambda=row.decay_lambda,
                default_lambda=lam,
                pinned_no_decay=pinned_no_decay,
            )
            base = effective_score(
                importance=row.importance,
                weight=row.weight,
                created_at=row.created_at,
                decay_lambda=decay,
                now=now,
            )
            sim = _clamp01(hit_scores.get(mid, 0.0))
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
            )

        # Also include pinned L2 not returned by vector top list
        if include_pinned:
            for row in self.repo.list_active_by_user(
                user_id, tenant_id=tenant_id, pinned_only=True, limit=self.settings.recall_pinned_cap
            ):
                if row.id in by_id:
                    continue
                decay = decay_lambda_for(
                    pinned=row.pinned,
                    row_lambda=row.decay_lambda,
                    default_lambda=lam,
                    pinned_no_decay=pinned_no_decay,
                )
                base = effective_score(
                    importance=row.importance,
                    weight=row.weight,
                    created_at=row.created_at,
                    decay_lambda=decay,
                    now=now,
                )
                sim = _clamp01(cosine(query_vec, self.embedding.embed([row.content])[0]))
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
                )

        # L1 session items (on-the-fly embedding)
        if session_id:
            for item in self.cache.list(session_id):
                base = effective_score(
                    importance=item.importance,
                    weight=item.weight,
                    created_at=item.created_at,
                    decay_lambda=decay_lambda_for(
                        pinned=item.pinned,
                        row_lambda=None,
                        default_lambda=lam,
                        pinned_no_decay=pinned_no_decay,
                    ),
                    now=now,
                )
                sim = _clamp01(cosine(query_vec, self.embedding.embed([item.content])[0]))
                lex = _lex_of(item.content)
                relevance = vector_weight * _clamp01(sim) + lexical_weight * lex
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
                )

        boost = self.settings.recall_pinned_score_boost
        no_lex_floor = self.settings.recall_min_score_no_lexical
        # 门禁量纲：relevance 模式只判相关性（与年龄解耦）；score 模式为旧行为（回滚开关）。
        rel_min = self.settings.recall_rel_min
        rel_min_no_lex = self.settings.recall_rel_min_no_lexical
        if gate_mode == "relevance":
            # 兼容旧的绝对分门禁配置：<=0 关闭该档，非默认值换算到相关性空间。
            legacy_lex = _legacy_rel_floor(
                self.settings.recall_min_score, _DEFAULT_MIN_SCORE
            )
            legacy_nolex = _legacy_rel_floor(
                self.settings.recall_min_score_no_lexical, _DEFAULT_MIN_SCORE_NO_LEXICAL
            )
            if legacy_lex is not None:
                rel_min = legacy_lex
            if legacy_nolex is not None:
                rel_min_no_lex = legacy_nolex
            if min_score is not None:
                if min_score <= 0:
                    rel_min = 0.0
                    rel_min_no_lex = 0.0
                else:
                    rel_min = max(rel_min, min_score)
        candidates = [
            c
            for c in by_id.values()
            if _passes_recall_gates(
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
            base_w = self.settings.recall_rank_base_weight
            candidates.sort(
                key=lambda x: (
                    x.relevance
                    + base_w * min(max(x.base, 0.0), 1.0)
                    + (boost if x.pinned and include_pinned else 0.0)
                ),
                reverse=True,
            )
        else:
            candidates.sort(
                key=lambda x: x.score + (boost if x.pinned and include_pinned else 0.0),
                reverse=True,
            )
        result = candidates[:top_k]

        self._touch_access([i.id for i in result if i.layer == "L2"])
        return result

    def _touch_access(self, memory_ids: Sequence[str]) -> None:
        if not memory_ids:
            return
        now = self._now_iso()
        for mid in memory_ids:
            row = self.repo.get_memory(mid)
            if row is None or row.deleted_at is not None:
                continue
            row.access_count = int(row.access_count or 0) + 1
            row.last_accessed_at = now
            self.repo.save_memory(row)

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
            decay = row.decay_lambda if row.decay_lambda is not None else lam
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

    def adjust_weights(self, memory_ids: Sequence[str], *, delta: float) -> int:
        """Apply feedback weight delta to existing L2 memories. Returns updated count."""
        if not memory_ids or delta == 0:
            return 0
        updated = 0
        now = self._now_iso()
        for mid in memory_ids:
            row = self.repo.get_memory(mid)
            if row is None or row.deleted_at is not None:
                continue
            row.weight = max(0.05, min(3.0, row.weight + delta))
            row.updated_at = now
            self.repo.save_memory(row)
            updated += 1
        return updated

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
        vector = self.embedding.embed([row.content])[0]
        self.vectors.upsert(
            memory_id=row.id,
            user_id=row.user_id,
            vector=vector,
            model=self.embedding.model_name,
        )

    def _now_iso(self) -> str:
        return self.clock.now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,.;:!?，。；：！？、]+", text.lower()) if t]


def _lexical_similarity(content: str, tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    hay = content.lower()
    hits = sum(1 for t in tokens if t in hay)
    if hits:
        return hits / len(tokens)
    # CJK often arrives as one unsegmented token — use character bigrams.
    joined = "".join(tokens)
    cjk = [ch for ch in joined if "\u4e00" <= ch <= "\u9fff"]
    if len(cjk) >= 2:
        bigrams = {"".join(cjk[i : i + 2]) for i in range(len(cjk) - 1)}
        shared = sum(1 for bg in bigrams if bg in hay)
        return shared / len(bigrams) if bigrams else 0.0
    return 0.0


def _clamp01(x: float) -> float:
    # Cosine can be negative for hashing collisions; floor at 0 for ranking blend.
    return max(0.0, min(1.0, x))


# 旧门禁配置的默认值（用来判断调用方是否显式改过）
_DEFAULT_MIN_SCORE = float(Settings.model_fields["recall_min_score"].default)
_DEFAULT_MIN_SCORE_NO_LEXICAL = float(
    Settings.model_fields["recall_min_score_no_lexical"].default
)


def _legacy_rel_floor(score_floor: float, default: float) -> float | None:
    """把旧的「绝对分门禁」配置换算到相关性空间。

    score = base × (0.15 + 0.85·rel) ⇒ rel = (score - 0.15) / 0.85。
    - `<= 0`    → 0.0（显式关闭这一档门禁）
    - 等于默认值 → None（表示「改用新的相关性默认值」）
    - 其他      → 按上式换算，保证老配置的严格度语义不变
    """
    if score_floor <= 0:
        return 0.0
    if abs(score_floor - default) < 1e-9:
        return None
    return max(0.0, (score_floor - 0.15) / 0.85)


# 判定「有词法证据」的最小值：低于此视为零词法（从严门禁）。
# 长文二次折扣后零星命中的 lex 会掉到这以下，从而被归入从严档。
_LEX_EVIDENCE_MIN = 0.02


def _length_adjusted_lexical(lex: float, content_len: int, full_credit_len: int) -> float:
    """长文里「命中一个词」是弱证据：超过 full_credit_len 后按长度**二次**折扣。

    不折扣的话，一条几千字的「大杂烩」记忆会与几乎所有查询产生词法重叠，
    从而绕过词法门禁（2026-10-08 hermes-user 实测：2920 字 sync_turn 镜像长文
    对 6/8 个无关查询都产生了词法重叠）。二次折扣保证长文里的零星命中
    掉到 _LEX_EVIDENCE_MIN 以下，归入「零词法」从严门禁。
    """
    if full_credit_len <= 0 or content_len <= full_credit_len:
        return lex
    ratio = full_credit_len / content_len
    return lex * ratio * ratio


def _passes_recall_gates(
    *,
    score: float,
    relevance: float = 0.0,
    lexical: float,
    min_score: float,
    min_score_no_lexical: float,
    mode: str = "relevance",
) -> bool:
    """Recall gate.

    mode="relevance"（默认）：只判相关性，与记忆年龄解耦。score 含 exp(-λ·age)，
    卡绝对分会让 age > ~28 天的记忆永远召不回（2026-10-08 实测全库召回为空）。
    mode="score"：旧行为（绝对分门禁），保留作回滚开关。
    """
    if mode == "score":
        if min_score > 0 and score < min_score:
            return False
        if lexical <= 0 and min_score_no_lexical > 0 and score < min_score_no_lexical:
            return False
        return True
    # 零词法重叠 → 用更严的相关性门槛（挡纯向量蹭分，如「服务器配置」）
    has_lex = lexical >= _LEX_EVIDENCE_MIN
    floor = min_score if has_lex else min_score_no_lexical
    return relevance >= floor
