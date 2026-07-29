# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from typing import Optional, Protocol, Sequence, runtime_checkable

from app.models import MemoryRow, SessionRow


@runtime_checkable
class MemoryRepository(Protocol):
    def create_session(self, session: SessionRow) -> SessionRow: ...

    def get_session(self, session_id: str) -> Optional[SessionRow]: ...

    def save_session(self, session: SessionRow) -> SessionRow: ...

    def create_memory(self, memory: MemoryRow) -> MemoryRow: ...

    def get_memory(self, memory_id: str) -> Optional[MemoryRow]: ...

    def get_memories_by_ids(self, memory_ids: Sequence[str]) -> list[MemoryRow]: ...

    def save_memory(self, memory: MemoryRow) -> MemoryRow: ...

    def list_active_by_user(
        self,
        user_id: str,
        *,
        tenant_id: str | None = None,
        pinned_only: bool = False,
        limit: int | None = None,
    ) -> list[MemoryRow]: ...

    def soft_delete_memories(self, memory_ids: Sequence[str], deleted_at: str) -> int: ...

    def list_distinct_user_ids(self) -> list[str]: ...

    def list_active_memories(
        self,
        *,
        user_id: str | None = None,
        include_orphans: bool = True,
        tenant_id: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryRow]: ...
