# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from typing import Optional, Sequence

from app.models import MemoryRow, SessionRow, utc_now_iso


class FakeMemoryRepository:
    """In-memory MemoryRepository for contract tests."""

    def __init__(self) -> None:
        self.sessions: dict[str, SessionRow] = {}
        self.memories: dict[str, MemoryRow] = {}

    def create_session(self, session: SessionRow) -> SessionRow:
        self.sessions[session.id] = session.model_copy(deep=True)
        return self.sessions[session.id].model_copy(deep=True)

    def get_session(self, session_id: str) -> Optional[SessionRow]:
        row = self.sessions.get(session_id)
        return row.model_copy(deep=True) if row else None

    def save_session(self, session: SessionRow) -> SessionRow:
        self.sessions[session.id] = session.model_copy(deep=True)
        return self.sessions[session.id].model_copy(deep=True)

    def create_memory(self, memory: MemoryRow) -> MemoryRow:
        self.memories[memory.id] = memory.model_copy(deep=True)
        return self.memories[memory.id].model_copy(deep=True)

    def get_memory(self, memory_id: str) -> Optional[MemoryRow]:
        row = self.memories.get(memory_id)
        return row.model_copy(deep=True) if row else None

    def get_memories_by_ids(self, memory_ids: Sequence[str]) -> list[MemoryRow]:
        out: list[MemoryRow] = []
        for mid in memory_ids:
            row = self.memories.get(mid)
            if row is not None:
                out.append(row.model_copy(deep=True))
        return out

    def save_memory(self, memory: MemoryRow) -> MemoryRow:
        self.memories[memory.id] = memory.model_copy(deep=True)
        return self.memories[memory.id].model_copy(deep=True)

    def list_active_by_user(
        self,
        user_id: str,
        *,
        tenant_id: str | None = None,
        pinned_only: bool = False,
        limit: int | None = None,
    ) -> list[MemoryRow]:
        rows = [
            m
            for m in self.memories.values()
            if m.user_id == user_id and m.deleted_at is None
        ]
        if tenant_id is not None:
            rows = [m for m in rows if m.tenant_id == tenant_id]
        if pinned_only:
            rows = [m for m in rows if m.pinned]
        rows.sort(key=lambda m: (not m.pinned, m.updated_at))
        if limit is not None:
            rows = rows[:limit]
        return [m.model_copy(deep=True) for m in rows]

    def soft_delete_memories(self, memory_ids: Sequence[str], deleted_at: str) -> int:
        count = 0
        for mid in memory_ids:
            row = self.memories.get(mid)
            if row is None or row.deleted_at is not None:
                continue
            if row.pinned:
                continue
            row.deleted_at = deleted_at
            row.updated_at = deleted_at or utc_now_iso()
            count += 1
        return count

    def list_distinct_user_ids(self) -> list[str]:
        users = {
            m.user_id
            for m in self.memories.values()
            if m.deleted_at is None and m.user_id
        }
        return sorted(users)

    def list_active_memories(
        self,
        *,
        user_id: str | None = None,
        include_orphans: bool = True,
        tenant_id: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryRow]:
        rows = [m for m in self.memories.values() if m.deleted_at is None]
        if user_id is not None:
            rows = [m for m in rows if m.user_id == user_id]
        elif not include_orphans:
            rows = [m for m in rows if m.user_id]
        if tenant_id is not None:
            rows = [m for m in rows if m.tenant_id == tenant_id]
        rows.sort(key=lambda m: m.updated_at, reverse=True)
        if limit is not None:
            rows = rows[:limit]
        return [m.model_copy(deep=True) for m in rows]
