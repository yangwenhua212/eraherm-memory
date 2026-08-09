# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Full-vector re-embed migration (no dual-track hashing/fastembed).

Recomputes embeddings with the *current* embedding backend and overwrites the
vector store. Optionally assigns ``user_id`` for orphan memories so they become
recallable again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.config import Settings
from app.models import utc_now_iso
from app.ports.embedding import EmbeddingClient
from app.ports.memory_repo import MemoryRepository
from app.ports.vector_store import VectorStore

OrphanPolicy = Literal["assign", "skip", "fail"]


@dataclass
class ReembedReport:
    scanned: int = 0
    reembedded: int = 0
    skipped_current: int = 0
    orphans_assigned: int = 0
    orphans_skipped: int = 0
    dangling_vectors_removed: int = 0
    errors: list[str] = field(default_factory=list)
    target_model: str = ""
    target_dim: int = 0
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "reembedded": self.reembedded,
            "skipped_current": self.skipped_current,
            "orphans_assigned": self.orphans_assigned,
            "orphans_skipped": self.orphans_skipped,
            "dangling_vectors_removed": self.dangling_vectors_removed,
            "errors": list(self.errors),
            "target_model": self.target_model,
            "target_dim": self.target_dim,
            "dry_run": self.dry_run,
        }


@dataclass(frozen=True)
class _VectorMeta:
    user_id: str | None
    model: str
    dim: int


class ReembedService:
    """One-shot / repeatable migration onto the active embedding space."""

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

    def run(
        self,
        *,
        user_id: str | None = None,
        orphan_policy: OrphanPolicy = "assign",
        orphan_user_id: str | None = None,
        batch_size: int = 32,
        force: bool = False,
        dry_run: bool = False,
        cleanup_dangling: bool = True,
        recreate_collection: bool = False,
    ) -> ReembedReport:
        target_model = self.embedding.model_name
        target_dim = int(self.embedding.dimensions)
        report = ReembedReport(
            target_model=target_model,
            target_dim=target_dim,
            dry_run=dry_run,
        )

        if target_dim != self.settings.embedding_dim:
            report.errors.append(
                f"embedding.dimensions={target_dim} != ERAHERM_EMBEDDING_DIM="
                f"{self.settings.embedding_dim}; fix config before migrating"
            )
            return report

        if recreate_collection and not dry_run:
            reset = getattr(self.vectors, "reset_collection", None)
            if callable(reset):
                reset(vector_size=target_dim)
            else:
                report.errors.append(
                    "vector store does not support reset_collection "
                    f"({type(self.vectors).__name__}); recreate manually if dim changed"
                )

        rows = self.repo.list_active_memories(user_id=user_id, include_orphans=True)
        report.scanned = len(rows)

        orphans = [r for r in rows if not r.user_id]
        if orphans and orphan_policy == "fail":
            report.errors.append(
                f"found {len(orphans)} orphan memories (user_id=None); "
                "pass --orphan-policy assign --orphan-user-id ... or skip"
            )
            return report
        if orphans and orphan_policy == "assign" and not orphan_user_id:
            report.errors.append(
                f"found {len(orphans)} orphan memories; "
                "provide --orphan-user-id when --orphan-policy=assign"
            )
            return report

        work: list = []
        for row in rows:
            if not row.user_id:
                if orphan_policy == "skip":
                    report.orphans_skipped += 1
                    continue
                # assign
                if not dry_run:
                    row.user_id = orphan_user_id
                    row.updated_at = utc_now_iso()
                    self.repo.save_memory(row)
                report.orphans_assigned += 1

            uid = row.user_id or orphan_user_id
            if not force and self._is_current(row.id, uid, target_model, target_dim):
                report.skipped_current += 1
                continue
            work.append(row)

        for i in range(0, len(work), max(1, batch_size)):
            batch = work[i : i + batch_size]
            try:
                vectors = self.embedding.embed([r.content for r in batch])
            except Exception as exc:  # noqa: BLE001 — surface per-batch in report
                report.errors.append(f"embed batch@{i}: {exc}")
                continue
            if len(vectors) != len(batch):
                report.errors.append(
                    f"embed batch@{i}: expected {len(batch)} vectors, got {len(vectors)}"
                )
                continue
            for row, vec in zip(batch, vectors, strict=True):
                if len(vec) != target_dim:
                    report.errors.append(
                        f"{row.id}: vector dim={len(vec)} != target {target_dim}"
                    )
                    continue
                if dry_run:
                    report.reembedded += 1
                    continue
                try:
                    self.vectors.upsert(
                        memory_id=row.id,
                        user_id=row.user_id,
                        vector=vec,
                        model=target_model,
                    )
                    report.reembedded += 1
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"{row.id}: upsert failed: {exc}")

        if cleanup_dangling and not dry_run:
            report.dangling_vectors_removed = self._cleanup_dangling(
                keep_ids={r.id for r in rows if r.user_id}
            )

        return report

    def _is_current(
        self,
        memory_id: str,
        user_id: str | None,
        target_model: str,
        target_dim: int,
    ) -> bool:
        getter = getattr(self.vectors, "get_meta", None)
        if not callable(getter):
            return False
        meta = getter(memory_id)
        if meta is None:
            return False
        if isinstance(meta, _VectorMeta):
            return (
                meta.dim == target_dim
                and meta.model == target_model
                and meta.user_id == user_id
            )
        # duck-typed tuple/dict from adapters
        if isinstance(meta, dict):
            return (
                int(meta.get("dim", -1)) == target_dim
                and meta.get("model") == target_model
                and meta.get("user_id") == user_id
            )
        return False

    def _cleanup_dangling(self, *, keep_ids: set[str]) -> int:
        lister = getattr(self.vectors, "list_memory_ids", None)
        if not callable(lister):
            return 0
        existing = set(lister())
        dangling = sorted(existing - keep_ids)
        if not dangling:
            return 0
        return int(self.vectors.delete(dangling))
