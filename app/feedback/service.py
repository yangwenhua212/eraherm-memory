# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.adapters.memory_job_queue import Job, JobQueue
from app.adapters.sqlite_feedback_store import SqliteFeedbackStore, dumps_ids, loads_ids
from app.config import Settings
from app.memory.service import MemoryService
from app.models import (
    FeedbackEventRow,
    FeedbackType,
    MemorySource,
    MemoryType,
    ReflectionRecordRow,
    ReflectionStatus,
)
from app.ports.clock import Clock
from app.ports.reflection import ReflectionPipeline


@dataclass
class ReflectionView:
    id: str
    status: str
    confidence: float
    summary: str
    analysis: str
    derived_memory_id: str | None


@dataclass
class FeedbackResult:
    feedback_id: str
    reflection: ReflectionView | None
    async_pending: bool = False


class FeedbackService:
    def __init__(
        self,
        *,
        store: SqliteFeedbackStore,
        memory: MemoryService,
        reflection: ReflectionPipeline,
        settings: Settings,
        clock: Clock,
        job_queue: JobQueue | None = None,
    ) -> None:
        self.store = store
        self.memory = memory
        self.reflection = reflection
        self.settings = settings
        self.clock = clock
        self.job_queue = job_queue

    def submit(
        self,
        *,
        user_id: str,
        answer_id: str,
        feedback_type: str,
        session_id: str | None = None,
        tenant_id: str | None = None,
        correction_text: str | None = None,
        related_memory_ids: list[str] | None = None,
        answer_text: str | None = None,
        async_mode: bool | None = None,
    ) -> FeedbackResult:
        ft = feedback_type.lower().strip()
        if ft not in {
            FeedbackType.UPVOTE.value,
            FeedbackType.DOWNVOTE.value,
            FeedbackType.CORRECT.value,
        }:
            raise ValueError(f"unsupported feedback_type: {feedback_type}")
        if ft == FeedbackType.CORRECT.value and not (correction_text or "").strip():
            raise ValueError("correction_text required for correct feedback")

        related_memory_ids = list(related_memory_ids or [])
        event = FeedbackEventRow(
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            answer_id=answer_id,
            feedback_type=ft,
            correction_text=correction_text,
            related_memory_ids_json=dumps_ids(related_memory_ids),
            answer_text=answer_text,
            created_at=self._now_iso(),
        )
        event = self.store.create_feedback(event)

        if ft == FeedbackType.UPVOTE.value:
            self.memory.adjust_weights(
                related_memory_ids,
                delta=self.settings.upvote_weight_delta,
            )
            return FeedbackResult(feedback_id=event.id, reflection=None)

        use_async = self.settings.feedback_async if async_mode is None else async_mode
        if use_async and self.job_queue is not None:
            ref = ReflectionRecordRow(
                feedback_id=event.id,
                analysis="",
                summary="",
                confidence=0.0,
                status=ReflectionStatus.PENDING.value,
                created_at=self._now_iso(),
            )
            ref = self.store.create_reflection(ref)
            if related_memory_ids:
                self.memory.adjust_weights(
                    related_memory_ids,
                    delta=self.settings.downvote_weight_delta,
                )
            self.job_queue.enqueue(
                Job(
                    name="reflection",
                    payload={
                        "feedback_id": event.id,
                        "reflection_id": ref.id,
                        "user_id": user_id,
                        "tenant_id": tenant_id,
                        "session_id": session_id,
                        "answer_id": answer_id,
                        "feedback_type": ft,
                        "correction_text": correction_text,
                        "answer_text": answer_text,
                        "related_memory_ids": related_memory_ids,
                    },
                )
            )
            return FeedbackResult(
                feedback_id=event.id,
                reflection=ReflectionView(
                    id=ref.id,
                    status=ref.status,
                    confidence=0.0,
                    summary="",
                    analysis="",
                    derived_memory_id=None,
                ),
                async_pending=True,
            )

        return self._run_reflection_sync(
            event=event,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            answer_id=answer_id,
            ft=ft,
            correction_text=correction_text,
            answer_text=answer_text,
            related_memory_ids=related_memory_ids,
        )

    def process_job(self, job: Job) -> None:
        if job.name != "reflection":
            return
        p = job.payload
        event = self.store.get_feedback(p["feedback_id"])
        ref = self.store.get_reflection_by_feedback(p["feedback_id"])
        if event is None or ref is None:
            return
        result = self._finalize_reflection(
            event=event,
            ref=ref,
            user_id=p["user_id"],
            tenant_id=p.get("tenant_id"),
            session_id=p.get("session_id"),
            answer_id=p["answer_id"],
            ft=p["feedback_type"],
            correction_text=p.get("correction_text"),
            answer_text=p.get("answer_text"),
            related_memory_ids=list(p.get("related_memory_ids") or []),
        )
        _ = result

    def get(self, feedback_id: str) -> FeedbackResult:
        event = self.store.get_feedback(feedback_id)
        if event is None:
            raise KeyError(f"feedback not found: {feedback_id}")
        ref = self.store.get_reflection_by_feedback(feedback_id)
        if ref is None:
            return FeedbackResult(feedback_id=event.id, reflection=None)
        return FeedbackResult(
            feedback_id=event.id,
            reflection=ReflectionView(
                id=ref.id,
                status=ref.status,
                confidence=ref.confidence,
                summary=ref.summary,
                analysis=ref.analysis,
                derived_memory_id=ref.derived_memory_id,
            ),
            async_pending=ref.status == ReflectionStatus.PENDING.value,
        )

    def _run_reflection_sync(
        self,
        *,
        event: FeedbackEventRow,
        user_id: str,
        tenant_id: str | None,
        session_id: str | None,
        answer_id: str,
        ft: str,
        correction_text: str | None,
        answer_text: str | None,
        related_memory_ids: list[str],
    ) -> FeedbackResult:
        ref = ReflectionRecordRow(
            feedback_id=event.id,
            analysis="",
            summary="",
            confidence=0.0,
            status=ReflectionStatus.PENDING.value,
            created_at=self._now_iso(),
        )
        ref = self.store.create_reflection(ref)
        if related_memory_ids:
            self.memory.adjust_weights(
                related_memory_ids,
                delta=self.settings.downvote_weight_delta,
            )
        return self._finalize_reflection(
            event=event,
            ref=ref,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            answer_id=answer_id,
            ft=ft,
            correction_text=correction_text,
            answer_text=answer_text,
            related_memory_ids=related_memory_ids,
        )

    def _finalize_reflection(
        self,
        *,
        event: FeedbackEventRow,
        ref: ReflectionRecordRow,
        user_id: str,
        tenant_id: str | None,
        session_id: str | None,
        answer_id: str,
        ft: str,
        correction_text: str | None,
        answer_text: str | None,
        related_memory_ids: list[str],
    ) -> FeedbackResult:
        related_contents: list[str] = []
        for mid in related_memory_ids:
            row = self.memory.repo.get_memory(mid)
            if row is not None and row.deleted_at is None:
                related_contents.append(row.content)

        try:
            draft = self.reflection.reflect(
                feedback_type=ft,
                correction_text=correction_text,
                answer_text=answer_text,
                related_contents=related_contents,
            )
        except Exception as exc:  # noqa: BLE001
            ref.status = ReflectionStatus.FAILED.value
            ref.analysis = f"reflection failed: {exc}"
            ref = self.store.save_reflection(ref)
            return FeedbackResult(
                feedback_id=event.id,
                reflection=ReflectionView(
                    id=ref.id,
                    status=ref.status,
                    confidence=ref.confidence,
                    summary=ref.summary,
                    analysis=ref.analysis,
                    derived_memory_id=None,
                ),
            )

        ref.analysis = draft.analysis
        ref.summary = draft.summary
        ref.confidence = draft.confidence

        threshold = self.settings.reflection_confidence_threshold
        if draft.confidence < threshold or not draft.summary.strip():
            ref.status = ReflectionStatus.REJECTED_LOW_CONFIDENCE.value
            ref = self.store.save_reflection(ref)
            return FeedbackResult(
                feedback_id=event.id,
                reflection=ReflectionView(
                    id=ref.id,
                    status=ref.status,
                    confidence=ref.confidence,
                    summary=ref.summary,
                    analysis=ref.analysis,
                    derived_memory_id=None,
                ),
            )

        if ft == FeedbackType.DOWNVOTE.value and not self.settings.downvote_writes_negative_memory:
            ref.status = ReflectionStatus.ACCEPTED.value
            ref = self.store.save_reflection(ref)
            return FeedbackResult(
                feedback_id=event.id,
                reflection=ReflectionView(
                    id=ref.id,
                    status=ref.status,
                    confidence=ref.confidence,
                    summary=ref.summary,
                    analysis=ref.analysis,
                    derived_memory_id=None,
                ),
            )

        if ft == FeedbackType.CORRECT.value and draft.memory_type == MemoryType.IDENTITY.value:
            pinned = True
        elif ft == FeedbackType.CORRECT.value:
            pinned = self.settings.correct_creates_pinned
        else:
            pinned = False

        derived = self.memory.remember(
            content=draft.summary,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            memory_type=draft.memory_type,
            importance=max(0.85, draft.confidence),
            pinned=pinned,
            extract_graph=False,
            meta={
                "source": "reflection",
                "feedback_id": event.id,
                "reflection_id": ref.id,
                "answer_id": answer_id,
            },
        )
        mem = self.memory.repo.get_memory(derived.id)
        if mem is not None:
            mem.source = MemorySource.REFLECTION.value
            mem.updated_at = self._now_iso()
            self.memory.repo.save_memory(mem)

        ref.status = ReflectionStatus.ACCEPTED.value
        ref.derived_memory_id = derived.id
        ref = self.store.save_reflection(ref)
        return FeedbackResult(
            feedback_id=event.id,
            reflection=ReflectionView(
                id=ref.id,
                status=ref.status,
                confidence=ref.confidence,
                summary=ref.summary,
                analysis=ref.analysis,
                derived_memory_id=ref.derived_memory_id,
            ),
        )

    def _now_iso(self) -> str:
        return self.clock.now().replace(microsecond=0).isoformat().replace("+00:00", "Z")
