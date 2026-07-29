# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

"""Proactive memory: conflict alerts on remember + sidecar recommendations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import Settings
from app.ports.embedding import EmbeddingClient
from app.ports.memory_repo import MemoryRepository
from app.ports.vector_store import VectorStore

_TECH_STACKS: dict[str, set[str]] = {
    "java": {"java", "spring", "springboot", "jvm", "maven", "gradle", "hibernate"},
    "go": {"go", "golang", "gin", "echo", "fiber"},
    "python": {"python", "django", "flask", "fastapi", "pytorch"},
    "nodejs": {"node", "nodejs", "express", "nestjs", "typescript", "javascript"},
    "dotnet": {".net", "csharp", "c#", "aspnet"},
    "rust": {"rust", "actix", "axum"},
    "php": {"php", "laravel", "symfony"},
    "ruby": {"ruby", "rails"},
}

_SHIFT_HINTS = re.compile(
    r"(改用|换成|迁移到|切换到|新项目用|改为|采用|不是|不再用|替代)",
    re.I,
)


@dataclass
class MemoryAlert:
    type: str
    severity: float
    message: str
    related_memory_ids: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    memory_id: str
    content: str
    score: float
    reason: str


class ProactiveService:
    def __init__(
        self,
        *,
        repo: MemoryRepository,
        embedding: EmbeddingClient,
        vectors: VectorStore,
        settings: Settings,
    ) -> None:
        self.repo = repo
        self.embedding = embedding
        self.vectors = vectors
        self.settings = settings

    def detect_alerts(
        self,
        *,
        user_id: str,
        content: str,
        exclude_memory_id: str | None = None,
        tenant_id: str | None = None,
    ) -> list[MemoryAlert]:
        if not self.settings.proactive_alerts_enabled or not user_id:
            return []

        alerts: list[MemoryAlert] = []
        new_stacks = _detect_stacks(content)
        threshold = self.settings.alert_similarity_threshold
        has_shift_hint = bool(_SHIFT_HINTS.search(content))

        # Pass 1: vector neighbors (semantic conflict / nearby stack change)
        query_vec = self.embedding.embed([content])[0]
        hits = self.vectors.search(
            query=query_vec,
            user_id=user_id,
            top_k=max(self.settings.alert_neighbor_k, 5),
        )
        rows = self._rows_for_hits(hits, tenant_id=tenant_id)
        for hit in hits:
            if exclude_memory_id and hit.memory_id == exclude_memory_id:
                continue
            row = rows.get(hit.memory_id)
            if row is None:
                continue
            sim = max(0.0, float(hit.score))
            if sim < threshold:
                continue
            old_stacks = _detect_stacks(row.content)
            shift = _stack_shift(old_stacks, new_stacks)
            if shift and (has_shift_hint or sim >= threshold):
                alerts.append(_shift_alert(row.content, row.id, shift, sim))
                continue
            # Near-duplicates of the same fact are not conflicts (re-click Demo).
            if _near_duplicate(content, row.content):
                continue
            if sim >= threshold + 0.08 and _looks_conflicting(content, row.content):
                alerts.append(
                    MemoryAlert(
                        type="conflict",
                        severity=min(1.0, sim),
                        message=(
                            f"新内容可能与既有记忆冲突：「{row.content[:48]}」。"
                            "建议确认后纠正或钉死新事实。"
                        ),
                        related_memory_ids=[row.id],
                    )
                )

        # Pass 2: lexical scan — hashing embeddings often miss Java↔Go; use recent L2
        if has_shift_hint and new_stacks:
            recent = self.repo.list_active_by_user(
                user_id,
                tenant_id=tenant_id,
                limit=self.settings.alert_scan_limit,
            )
            for row in recent:
                if exclude_memory_id and row.id == exclude_memory_id:
                    continue
                old_stacks = _detect_stacks(row.content)
                shift = _stack_shift(old_stacks, new_stacks)
                if not shift:
                    continue
                alerts.append(_shift_alert(row.content, row.id, shift, 0.75))

        return _dedupe_alerts(alerts)[: self.settings.alert_max_items]

    def recommend(
        self,
        *,
        user_id: str,
        query: str,
        exclude_memory_ids: list[str] | None = None,
        top_k: int | None = None,
        reason: str = "similar_topic",
        tenant_id: str | None = None,
    ) -> list[Recommendation]:
        if not self.settings.proactive_recommend_enabled or not user_id or not query.strip():
            return []

        top_k = top_k or self.settings.recommend_top_k
        exclude = set(exclude_memory_ids or [])
        query_vec = self.embedding.embed([query])[0]
        hits = self.vectors.search(
            query=query_vec,
            user_id=user_id,
            top_k=max(top_k * 3, 10),
        )
        rows = self._rows_for_hits(hits, tenant_id=tenant_id)

        out: list[Recommendation] = []
        seen: set[str] = set()
        for hit in hits:
            if hit.memory_id in exclude:
                continue
            row = rows.get(hit.memory_id)
            if row is None:
                continue
            lex = _lexical_hit_score(query, row.content)
            score = max(0.0, float(hit.score), lex)
            if score < self.settings.recommend_min_score:
                continue
            seen.add(row.id)
            out.append(
                Recommendation(
                    memory_id=row.id,
                    content=row.content,
                    score=score,
                    reason=reason,
                )
            )
            if len(out) >= top_k:
                return out

        # Lexical fallback — hashing embeddings often score ~0 on CJK without shared tokens
        if len(out) < top_k:
            recent = self.repo.list_active_by_user(
                user_id,
                tenant_id=tenant_id,
                limit=max(self.settings.alert_scan_limit, 40),
            )
            ranked = sorted(
                (
                    (_lexical_hit_score(query, r.content), r)
                    for r in recent
                    if r.id not in exclude and r.id not in seen
                ),
                key=lambda x: x[0],
                reverse=True,
            )
            for score, row in ranked:
                if score < self.settings.recommend_min_score:
                    break
                out.append(
                    Recommendation(
                        memory_id=row.id,
                        content=row.content,
                        score=score,
                        reason=reason,
                    )
                )
                if len(out) >= top_k:
                    break
        return out

    def _rows_for_hits(self, hits, *, tenant_id: str | None) -> dict:
        rows = {
            r.id: r
            for r in self.repo.get_memories_by_ids([h.memory_id for h in hits])
            if r.deleted_at is None
        }
        if tenant_id is not None:
            rows = {k: v for k, v in rows.items() if v.tenant_id == tenant_id}
        return rows


def _shift_alert(
    old_content: str, memory_id: str, shift: tuple[str, str], sim: float
) -> MemoryAlert:
    old_s, new_s = shift
    return MemoryAlert(
        type="tech_stack_shift",
        severity=min(1.0, 0.55 + sim * 0.45),
        message=(
            f"检测到技术栈切换（{old_s}→{new_s}）。"
            f"相关旧记忆：「{old_content[:48]}」。"
            "是否要将迁移经验/对照指南也写入记忆？"
        ),
        related_memory_ids=[memory_id],
    )


def _detect_stacks(text: str) -> set[str]:
    low = text.lower()
    found: set[str] = set()
    for name, keys in _TECH_STACKS.items():
        if any(k in low for k in keys):
            # Avoid matching bare "go" inside other words when possible.
            if name == "go" and "go" in low:
                if not re.search(r"(?:\bgo\b|golang)", low):
                    continue
            found.add(name)
    return found


def _stack_shift(old: set[str], new: set[str]) -> tuple[str, str] | None:
    if not old or not new:
        return None
    added = new - old
    removed_or_old = old - new
    if added and removed_or_old:
        return (sorted(removed_or_old)[0], sorted(added)[0])
    if added and old and not (new & old):
        return (sorted(old)[0], sorted(added)[0])
    return None


def _looks_conflicting(new: str, old: str) -> bool:
    """True only when contents likely disagree — not merely because new has '改用'."""
    if _near_duplicate(new, old):
        return False
    new_s, old_s = _detect_stacks(new), _detect_stacks(old)
    if new_s and old_s and not (new_s & old_s):
        return True
    if re.search(r"(不是|而非|不要|禁止|避免|应该是)", new) and len(
        set(_tokenize(new)) & set(_tokenize(old))
    ) >= 2:
        return True
    # Shift wording + different stacks already handled above; same-stack "改用" is not conflict.
    return False


def _near_duplicate(a: str, b: str, *, threshold: float = 0.72) -> bool:
    if a.strip() == b.strip():
        return True
    return _lexical_hit_score(a, b) >= threshold and _lexical_hit_score(b, a) >= threshold


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,.;:!?，。；：！？、]+", text.lower()) if len(t) > 1]


def _query_keys(query: str) -> list[str]:
    keys: list[str] = []
    for t in _tokenize(query):
        keys.append(t)
        chars = [c for c in t if "\u4e00" <= c <= "\u9fff"]
        for i in range(len(chars) - 1):
            keys.append(chars[i] + chars[i + 1])
    # de-dupe preserve order
    return list(dict.fromkeys(keys))


def _lexical_hit_score(query: str, content: str) -> float:
    keys = _query_keys(query)
    if not keys:
        return 0.0
    hay = content.lower()
    hits = sum(1 for k in keys if k in hay)
    return hits / len(keys)


def _dedupe_alerts(alerts: list[MemoryAlert]) -> list[MemoryAlert]:
    seen: set[str] = set()
    out: list[MemoryAlert] = []
    for a in sorted(alerts, key=lambda x: x.severity, reverse=True):
        # Collapse same type + same message shape (multiple near-dup related memories).
        key = f"{a.type}:{a.message[:80]}"
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out
