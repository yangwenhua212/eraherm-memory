# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

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

    def bump_access(self, memory_ids: Sequence[str], accessed_at: str) -> int: ...

    def add_weight(
        self,
        memory_ids: Sequence[str],
        *,
        delta: float,
        updated_at: str,
        min_weight: float = 0.05,
        max_weight: float = 3.0,
    ) -> int: ...

    def set_weight(self, memory_id: str, *, weight: float, updated_at: str) -> int: ...

    def set_weights_bulk(
        self, updates: Sequence[tuple[str, float, str]]
    ) -> int:
        """[(memory_id, weight, updated_at)] —— 一个事务内批量更新。

        整理（consolidation）会对整个用户库重排权重；逐行开事务在 5000 条时
        就是 5000 次提交，这里收敛成一次。
        """
        ...

    def supersede(
        self, memory_ids: Sequence[str], *, superseded_by: str, superseded_at: str
    ) -> int:
        """把若干记忆标记为「已被取代」（不删除，只在召回时让路）。"""
        ...

    def list_deleted_by_user(
        self, user_id: str, *, limit: int | None = None
    ) -> list[MemoryRow]:
        """列出已软删的记忆（restore 用）。"""
        ...

    def restore_memories(self, memory_ids: Sequence[str]) -> int:
        """把软删的记忆恢复（deleted_at 置空）。"""
        ...

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
