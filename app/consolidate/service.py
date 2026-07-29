# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

"""Memory consolidation: reweight, compress, conflict retire, forget."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from app.adapters.sqlite_vector_store import cosine
from app.config import Settings
from app.memory.service import MemoryService, age_days
from app.models import MemoryRow, MemorySource, MemoryType
from app.ports.clock import Clock
from app.ports.embedding import EmbeddingClient
from app.ports.memory_repo import MemoryRepository
from app.ports.vector_store import VectorStore

_TOPIC_GROUPS: dict[str, set[str]] = {
    "database": {"mysql", "postgresql", "postgres", "mongodb", "redis", "sqlite", "数据库"},
    "backend_lang": {"java", "spring", "golang", "python", "fastapi", "nodejs", "rust"},
    "auth": {"jwt", "oauth", "登录", "鉴权", "认证"},
}


class Summarizer(Protocol):
    def summarize(self, contents: list[str], *, topic_hint: str = "") -> str: ...


@dataclass
class ConsolidationReport:
    user_id: str
    reweighted: int = 0
    forgotten: int = 0
    compressed_clusters: int = 0
    compressed_deleted: int = 0
    conflicts_resolved: int = 0
    summary_memory_ids: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "reweighted": self.reweighted,
            "forgotten": self.forgotten,
            "compressed_clusters": self.compressed_clusters,
            "compressed_deleted": self.compressed_deleted,
            "conflicts_resolved": self.conflicts_resolved,
            "summary_memory_ids": self.summary_memory_ids,
            "details": self.details,
        }


class HeuristicSummarizer:
    def summarize(self, contents: list[str], *, topic_hint: str = "") -> str:
        # Keep newest-ish / longest unique fragments; one bullet summary line.
        uniq: list[str] = []
        seen: set[str] = set()
        for c in sorted(contents, key=len, reverse=True):
            key = re.sub(r"\s+", "", c.lower())[:48]
            if key in seen:
                continue
            seen.add(key)
            uniq.append(c.strip())
            if len(uniq) >= 4:
                break
        topic = topic_hint or "相关主题"
        joined = "；".join(uniq)
        return f"【精华摘要·{topic}】{joined}"


class LLMSummarizer:
    def __init__(self, llm: Any) -> None:
        self.llm = llm

    def summarize(self, contents: list[str], *, topic_hint: str = "") -> str:
        numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(contents))
        data = self.llm.complete_json(
            system=(
                "你是记忆压缩器。把多条冗余记忆压成一条中文精华事实。"
                "只输出 JSON：{\"summary\":\"...\"}。保留关键约束，去掉重复。"
            ),
            user=f"主题提示: {topic_hint or '无'}\n记忆列表:\n{numbered}",
        )
        summary = str(data.get("summary") or "").strip()
        if not summary:
            return HeuristicSummarizer().summarize(contents, topic_hint=topic_hint)
        return f"【精华摘要·{topic_hint or '相关主题'}】{summary}"


class ConsolidationService:
    def __init__(
        self,
        *,
        repo: MemoryRepository,
        memory: MemoryService,
        embedding: EmbeddingClient,
        vectors: VectorStore,
        settings: Settings,
        clock: Clock,
        summarizer: Summarizer | None = None,
    ) -> None:
        self.repo = repo
        self.memory = memory
        self.embedding = embedding
        self.vectors = vectors
        self.settings = settings
        self.clock = clock
        self.summarizer = summarizer or HeuristicSummarizer()

    def run_for_user(self, user_id: str, *, tenant_id: str | None = None) -> ConsolidationReport:
        report = ConsolidationReport(user_id=user_id)
        rows = self.repo.list_active_by_user(user_id, tenant_id=tenant_id)
        if not rows:
            return report

        report.reweighted = self._reweight(rows)
        # reload after weight updates
        rows = self.repo.list_active_by_user(user_id, tenant_id=tenant_id)

        conflict_n, conflict_notes = self._resolve_conflicts(rows)
        report.conflicts_resolved = conflict_n
        report.details.extend(conflict_notes)

        rows = self.repo.list_active_by_user(user_id, tenant_id=tenant_id)
        c_clusters, c_deleted, summary_ids, notes = self._compress_clusters(
            user_id=user_id, rows=rows, tenant_id=tenant_id
        )
        report.compressed_clusters = c_clusters
        report.compressed_deleted = c_deleted
        report.summary_memory_ids = summary_ids
        report.details.extend(notes)

        rows = self.repo.list_active_by_user(user_id, tenant_id=tenant_id)
        report.forgotten = self._forget_low_weight(rows)
        return report

    def run_all(self, *, tenant_id: str | None = None) -> list[ConsolidationReport]:
        return [
            self.run_for_user(uid, tenant_id=tenant_id)
            for uid in self.repo.list_distinct_user_ids()
        ]

    def _reweight(self, rows: list[MemoryRow]) -> int:
        now = self.clock.now()
        lam = self.settings.decay_lambda_default
        changed = 0
        for row in rows:
            accessed = row.last_accessed_at or row.updated_at or row.created_at
            recency = math.exp(-lam * age_days(accessed, now))
            freq = math.log1p(max(row.access_count, 0))
            freq_n = min(1.0, freq / math.log1p(20))
            pin = 1.35 if row.pinned else 1.0
            # Blend original importance with usage signal into weight.
            score = row.importance * (0.35 + 0.4 * recency + 0.25 * freq_n) * pin
            new_weight = max(0.05, min(2.0, score))
            if abs(new_weight - row.weight) < 1e-4:
                continue
            row.weight = new_weight
            row.updated_at = self._now_iso()
            self.repo.save_memory(row)
            changed += 1
        return changed

    def _forget_low_weight(self, rows: list[MemoryRow]) -> int:
        thr = self.settings.consolidation_forget_weight_threshold
        to_drop = [
            r.id
            for r in rows
            if (not r.pinned)
            and r.weight < thr
            and r.memory_type not in {MemoryType.IDENTITY.value}
            and r.source != MemorySource.CONSOLIDATION.value
        ]
        if not to_drop:
            return 0
        n = self.repo.soft_delete_memories(to_drop, self._now_iso())
        if to_drop:
            self.vectors.delete(to_drop)
        return n

    def _resolve_conflicts(self, rows: list[MemoryRow]) -> tuple[int, list[str]]:
        notes: list[str] = []
        deleted = 0
        by_topic: dict[str, list[MemoryRow]] = {}
        for row in rows:
            for topic, keys in _TOPIC_GROUPS.items():
                low = row.content.lower()
                if any(k in low for k in keys):
                    by_topic.setdefault(topic, []).append(row)

        for topic, group in by_topic.items():
            if len(group) < 2:
                continue
            # Prefer reflection / newer / higher weight / pinned
            ranked = sorted(group, key=_conflict_rank_key, reverse=True)
            winner = ranked[0]
            losers = []
            for other in ranked[1:]:
                if other.pinned:
                    continue
                if not _looks_topic_conflict(winner.content, other.content, topic):
                    continue
                losers.append(other)
            if not losers:
                continue
            ids = [r.id for r in losers]
            deleted += self.repo.soft_delete_memories(ids, self._now_iso())
            self.vectors.delete(ids)
            notes.append(
                f"conflict:{topic} keep={winner.id} drop={ids}"
            )
        return deleted, notes

    def _compress_clusters(
        self,
        *,
        user_id: str,
        rows: list[MemoryRow],
        tenant_id: str | None,
    ) -> tuple[int, int, list[str], list[str]]:
        candidates = [
            r
            for r in rows
            if not r.pinned and r.memory_type in {MemoryType.FACT.value, MemoryType.EPISODE.value}
        ]
        if len(candidates) < self.settings.consolidation_cluster_min_size:
            return 0, 0, [], []

        vectors = self.embedding.embed([r.content for r in candidates])
        used: set[str] = set()
        clusters: list[list[MemoryRow]] = []
        sim_thr = self.settings.consolidation_cluster_similarity
        min_size = self.settings.consolidation_cluster_min_size
        lex_thr = 0.12

        # Topic buckets first (e.g. all "database" facts) — matches product story
        for topic, keys in _TOPIC_GROUPS.items():
            bucket = [
                r
                for r in candidates
                if r.id not in used and any(k in r.content.lower() for k in keys)
            ]
            if len(bucket) >= min_size:
                for r in bucket:
                    used.add(r.id)
                clusters.append(bucket)
            if len(clusters) >= self.settings.consolidation_max_clusters:
                break

        for i, row in enumerate(candidates):
            if row.id in used:
                continue
            cluster = [row]
            for j in range(i + 1, len(candidates)):
                other = candidates[j]
                if other.id in used:
                    continue
                if cosine(vectors[i], vectors[j]) >= sim_thr or _lexical_overlap(
                    row.content, other.content
                ) >= lex_thr:
                    cluster.append(other)
            if len(cluster) >= min_size:
                for c in cluster:
                    used.add(c.id)
                clusters.append(cluster)
            if len(clusters) >= self.settings.consolidation_max_clusters:
                break

        clusters = clusters[: self.settings.consolidation_max_clusters]

        summary_ids: list[str] = []
        deleted = 0
        notes: list[str] = []
        for cluster in clusters:
            topic = _guess_topic(cluster)
            summary = self.summarizer.summarize(
                [c.content for c in cluster], topic_hint=topic
            )
            importance = max(c.importance for c in cluster)
            result = self.memory.remember(
                content=summary,
                user_id=user_id,
                tenant_id=tenant_id,
                memory_type=MemoryType.FACT.value,
                importance=max(importance, 0.75),
                pinned=False,
                extract_graph=False,
                meta={
                    "consolidated_from": [c.id for c in cluster],
                    "consolidation": True,
                },
            )
            # Tag source as consolidation
            row = self.repo.get_memory(result.id)
            if row is not None:
                row.source = MemorySource.CONSOLIDATION.value
                row.weight = max(c.weight for c in cluster)
                row.updated_at = self._now_iso()
                self.repo.save_memory(row)

            drop_ids = [c.id for c in cluster]
            deleted += self.repo.soft_delete_memories(drop_ids, self._now_iso())
            self.vectors.delete(drop_ids)
            summary_ids.append(result.id)
            notes.append(f"compress:{topic} n={len(cluster)} -> {result.id}")

        return len(clusters), deleted, summary_ids, notes

    def _now_iso(self) -> str:
        return (
            self.clock.now()
            .astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )


def _conflict_rank_key(row: MemoryRow) -> tuple:
    src_bonus = 1 if row.source == MemorySource.REFLECTION.value else 0
    return (row.pinned, src_bonus, row.weight, row.updated_at or row.created_at)


def _looks_topic_conflict(a: str, b: str, topic: str) -> bool:
    al, bl = a.lower(), b.lower()
    if topic == "database":
        dbs = ["mysql", "postgresql", "postgres", "mongodb", "sqlite"]
        a_hit = {d for d in dbs if d in al}
        b_hit = {d for d in dbs if d in bl}
        # normalize postgres
        if "postgres" in a_hit:
            a_hit.add("postgresql")
        if "postgres" in b_hit:
            b_hit.add("postgresql")
        return bool(a_hit and b_hit and a_hit != b_hit)
    if topic == "backend_lang":
        langs = ["java", "golang", "python", "nodejs", "rust"]
        # map spring->java, fastapi->python, go->golang
        def hits(text: str) -> set[str]:
            h: set[str] = set()
            if "java" in text or "spring" in text:
                h.add("java")
            if "golang" in text or re.search(r"\bgo\b", text):
                h.add("golang")
            if "python" in text or "fastapi" in text:
                h.add("python")
            if "node" in text or "typescript" in text:
                h.add("nodejs")
            if "rust" in text:
                h.add("rust")
            return h

        ah, bh = hits(al), hits(bl)
        return bool(ah and bh and ah != bh)
    # generic: high overlap tokens but negation / 不是
    if re.search(r"(不是|而非|应该是|改为|改用)", al + bl):
        return _lexical_overlap(a, b) >= 0.25
    return False


def _guess_topic(cluster: list[MemoryRow]) -> str:
    blob = " ".join(c.content for c in cluster).lower()
    for topic, keys in _TOPIC_GROUPS.items():
        if any(k in blob for k in keys):
            return topic
    return "相关主题"


def _lexical_overlap(a: str, b: str) -> float:
    def keys(text: str) -> set[str]:
        out: set[str] = set()
        for t in re.split(r"[\s,.;:!?，。；：！？、]+", text.lower()):
            if len(t) < 2:
                continue
            out.add(t)
            chars = [c for c in t if "\u4e00" <= c <= "\u9fff"]
            for i in range(len(chars) - 1):
                out.add(chars[i] + chars[i + 1])
        return out

    ka, kb = keys(a), keys(b)
    if not ka or not kb:
        return 0.0
    return len(ka & kb) / len(ka | kb)
