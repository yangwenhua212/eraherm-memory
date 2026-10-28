# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Memory consolidation: reweight, compress, conflict retire, forget."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from app.adapters.sqlite_vector_store import cosine
from app.config import Settings
from app.memory.service import MemoryService, age_days
from app.models import MemoryRow, MemorySource, MemoryType
from app.observability.logging import logger
from app.ports.clock import Clock
from app.ports.embedding import EmbeddingClient
from app.ports.memory_repo import MemoryRepository
from app.ports.vector_store import VectorStore
from app.proclock import ProcessLock
from app.sensitive import assert_remote_embedding_allowed, contains_sensitive

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
    #: 本次是否为 dry-run（只统计、不落库）
    dry_run: bool = False
    #: 被跳过的原因（例如「另一个进程正持有整理锁」）
    skipped_reason: str | None = None
    #: 删除前自动归档的归档 id（为空 = 未归档）
    archive_id: str | None = None

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
            "dry_run": self.dry_run,
            "skipped_reason": self.skipped_reason,
            "archive_id": self.archive_id,
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
        joined = "；".join(uniq)
        # 不拼模板前缀：`【精华摘要·X】` 在语义空间是纯噪声，会把弱相关查询拉高
        # （2026-08-25 实测「服务器配置」0.501 命中摘要，弱相关探针 FAIL）
        return joined


class LLMSummarizer:
    def __init__(self, llm: Any) -> None:
        self.llm = llm

    def summarize(self, contents: list[str], *, topic_hint: str = "") -> str:
        # 敏感内容绝不外发：LLM 压缩会把多条记忆原文拼进 prompt，
        # 这是继「LLM 抽取」「LLM 反射」之后的第三个出网点 —— 之前唯一漏掉守卫的一处。
        if any(contains_sensitive(c) for c in contents):
            return HeuristicSummarizer().summarize(contents, topic_hint=topic_hint)
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
        # 同样不拼模板前缀（噪声，见 HeuristicSummarizer）
        return summary


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
        archiver: Callable[[str], str | None] | None = None,
    ) -> None:
        self.repo = repo
        self.memory = memory
        self.embedding = embedding
        self.vectors = vectors
        self.settings = settings
        self.clock = clock
        self.summarizer = summarizer or HeuristicSummarizer()
        # 破坏性动作前的自动归档钩子：入参 user_id，返回归档 id。
        # 由组合根注入 L3ArchiveService.dump（避免 consolidate 直接依赖归档服务）。
        self.archiver = archiver

    # --- 统一的对外入口 ----------------------------------------------------

    def consolidate_all(
        self,
        *,
        tenant_id: str | None = None,
        dry_run: bool = False,
        use_lock: bool = True,
    ) -> list[ConsolidationReport]:
        """跨进程互斥 + dry-run 的整理入口（scheduler / CLI / admin 都用它）。

        没有这把锁时，``ERAHERM_CONSOLIDATION_ENABLED=true`` + 多 worker
        会让每个进程各跑一遍：重复摘要、重复软删原文（见 ADR 0013 与 KNOWN_ISSUES）。
        """
        lock: ProcessLock | None = None
        if use_lock:
            lock = ProcessLock(
                Path(self.settings.data_dir) / "consolidation.lock",
                stale_after_seconds=float(self.settings.consolidation_lock_stale_seconds),
            )
            if not lock.try_acquire():
                logger.info(
                    "consolidation_skipped_locked",
                    extra={"detail": f"another process holds {lock.path}"},
                )
                return [
                    ConsolidationReport(
                        user_id="*",
                        skipped_reason="another process holds the consolidation lock",
                        dry_run=dry_run,
                    )
                ]
        try:
            users = self.repo.list_distinct_user_ids()
            return [
                self.run_for_user(uid, tenant_id=tenant_id, dry_run=dry_run)
                for uid in users
            ]
        finally:
            if lock is not None:
                lock.release()

    def run_for_user(
        self,
        user_id: str,
        *,
        tenant_id: str | None = None,
        dry_run: bool = False,
    ) -> ConsolidationReport:
        report = ConsolidationReport(user_id=user_id, dry_run=dry_run)
        rows = self.repo.list_active_by_user(user_id, tenant_id=tenant_id)
        if not rows:
            return report

        report.reweighted = self._reweight(rows, dry_run=dry_run)
        # reload after weight updates
        rows = self.repo.list_active_by_user(user_id, tenant_id=tenant_id)

        # 删除前自动归档：整理是破坏性的（软删冲突/低权重、压缩后删原文），
        # 而此前既没有 dry-run 也没有恢复路径。归档是「能不能后悔」的前提。
        # 无法预知本次是否真的会删（要算完冲突/聚类才知道），所以只要会执行整理就先归档。
        if not dry_run and self.archiver is not None and self.settings.consolidation_archive_before_delete:
            try:
                report.archive_id = self.archiver(user_id)
            except Exception as exc:  # noqa: BLE001
                # 归档失败就不允许删除：宁可不整理，也不要不可恢复地删数据
                report.skipped_reason = f"archive before delete failed: {exc}"
                logger.warning(
                    "consolidation_archive_failed",
                    extra={"user_id": user_id, "detail": str(exc)[:200]},
                )
                return report

        conflict_n, conflict_notes = self._resolve_conflicts(rows, dry_run=dry_run)
        report.conflicts_resolved = conflict_n
        report.details.extend(conflict_notes)

        rows = self.repo.list_active_by_user(user_id, tenant_id=tenant_id)
        c_clusters, c_deleted, summary_ids, notes = self._compress_clusters(
            user_id=user_id, rows=rows, tenant_id=tenant_id, dry_run=dry_run
        )
        report.compressed_clusters = c_clusters
        report.compressed_deleted = c_deleted
        report.summary_memory_ids = summary_ids
        report.details.extend(notes)

        rows = self.repo.list_active_by_user(user_id, tenant_id=tenant_id)
        report.forgotten = self._forget_low_weight(rows, dry_run=dry_run)
        return report

    def run_all(self, *, tenant_id: str | None = None) -> list[ConsolidationReport]:
        """不带锁的版本（测试/嵌入式用）。生产请用 ``consolidate_all``。"""
        return [
            self.run_for_user(uid, tenant_id=tenant_id)
            for uid in self.repo.list_distinct_user_ids()
        ]

    def _reweight(self, rows: list[MemoryRow], *, dry_run: bool = False) -> int:
        now = self.clock.now()
        lam = self.settings.decay_lambda_default
        updates: list[tuple[str, float, str]] = []
        stamp = self._now_iso()
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
            updates.append((row.id, new_weight, stamp))
        if dry_run or not updates:
            return len(updates)
        # 一个事务批量更新（以前逐行 save_memory = 每条一个提交）
        self.repo.set_weights_bulk(updates)
        return len(updates)

    def _forget_low_weight(self, rows: list[MemoryRow], *, dry_run: bool = False) -> int:
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
        if dry_run:
            return len(to_drop)
        n = self.repo.soft_delete_memories(to_drop, self._now_iso())
        if to_drop:
            self.vectors.delete(to_drop)
        return n

    def _resolve_conflicts(
        self, rows: list[MemoryRow], *, dry_run: bool = False
    ) -> tuple[int, list[str]]:
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
            if dry_run:
                notes.append(f"conflict(dry-run):{topic} keep={winner.id} would_drop={ids}")
                continue
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
        dry_run: bool = False,
    ) -> tuple[int, int, list[str], list[str]]:
        candidates = [
            r
            for r in rows
            if not r.pinned
            and r.memory_type in {MemoryType.FACT.value, MemoryType.EPISODE.value}
            # 摘要本身不再参与聚类：否则「摘要的摘要」会一轮轮丢掉细节（语义漂移）
            and r.source != MemorySource.CONSOLIDATION.value
        ]
        # 全对全相似度是 O(N²·dim)：先截断，别让夜间任务在库变大后永远跑不完
        max_candidates = max(1, int(self.settings.consolidation_max_candidates))
        if len(candidates) > max_candidates:
            logger.warning(
                "consolidation_candidates_truncated",
                extra={
                    "detail": (
                        f"{len(candidates)} candidates > ERAHERM_CONSOLIDATION_MAX_CANDIDATES="
                        f"{max_candidates}; clustering the {max_candidates} most recent"
                    ),
                    "user_id": user_id,
                },
            )
            candidates = sorted(candidates, key=lambda r: r.updated_at, reverse=True)[
                :max_candidates
            ]
        if len(candidates) < self.settings.consolidation_cluster_min_size:
            return 0, 0, [], []

        vectors = self._embed_in_batches([r.content for r in candidates])
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
            contents = [c.content for c in cluster]
            if dry_run:
                notes.append(
                    f"compress(dry-run):{topic} n={len(cluster)} would_drop="
                    f"{[c.id for c in cluster]}"
                )
                continue
            summary = self.summarizer.summarize(contents, topic_hint=topic)
            # 摘要会进入记忆库，也就可能被再次 embedding：敏感内容同样要 fail-closed
            assert_remote_embedding_allowed(
                [summary],
                is_remote=bool(getattr(self.embedding, "is_remote", False)),
                enforced=bool(self.settings.sensitive_requires_local_embedding),
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

    def _embed_in_batches(self, texts: list[str], *, batch_size: int = 64) -> list[list[float]]:
        """分批 embedding。

        以前是一次性 ``embed([全部候选])`` —— 大库会撞上 OpenAI 的请求体上限，
        本地模型也会顶出内存峰值。顺带在这里做敏感内容检查。
        """
        is_remote = bool(getattr(self.embedding, "is_remote", False))
        enforced = bool(self.settings.sensitive_requires_local_embedding)
        vectors: list[list[float]] = []
        for i in range(0, len(texts), max(1, batch_size)):
            batch = texts[i : i + batch_size]
            assert_remote_embedding_allowed(
                batch, is_remote=is_remote, enforced=enforced
            )
            vectors.extend(self.embedding.embed(batch))
        return vectors

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
