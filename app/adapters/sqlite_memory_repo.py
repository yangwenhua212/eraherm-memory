# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Optional, Sequence

from sqlmodel import Session, SQLModel, col, create_engine, select

from app.models import MemoryRow, SessionRow


class SqliteMemoryRepository:
    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, connect_args=connect_args)
        SQLModel.metadata.create_all(self.engine)

    def session(self) -> Session:
        return Session(self.engine)

    def create_session(self, session: SessionRow) -> SessionRow:
        with self.session() as db:
            db.add(session)
            db.commit()
            db.refresh(session)
            db.expunge(session)
            return session

    def get_session(self, session_id: str) -> Optional[SessionRow]:
        with self.session() as db:
            row = db.get(SessionRow, session_id)
            if row is not None:
                db.expunge(row)
            return row

    def save_session(self, session: SessionRow) -> SessionRow:
        with self.session() as db:
            merged = db.merge(session)
            db.commit()
            db.refresh(merged)
            db.expunge(merged)
            return merged

    def create_memory(self, memory: MemoryRow) -> MemoryRow:
        with self.session() as db:
            db.add(memory)
            db.commit()
            db.refresh(memory)
            db.expunge(memory)
            return memory

    def get_memory(self, memory_id: str) -> Optional[MemoryRow]:
        with self.session() as db:
            row = db.get(MemoryRow, memory_id)
            if row is not None:
                db.expunge(row)
            return row

    def get_memories_by_ids(self, memory_ids: Sequence[str]) -> list[MemoryRow]:
        if not memory_ids:
            return []
        with self.session() as db:
            rows: list[MemoryRow] = []
            for mid in memory_ids:
                row = db.get(MemoryRow, mid)
                if row is not None:
                    db.expunge(row)
                    rows.append(row)
            return rows

    def save_memory(self, memory: MemoryRow) -> MemoryRow:
        with self.session() as db:
            merged = db.merge(memory)
            db.commit()
            db.refresh(merged)
            db.expunge(merged)
            return merged

    def list_active_by_user(
        self,
        user_id: str,
        *,
        tenant_id: str | None = None,
        pinned_only: bool = False,
        limit: int | None = None,
    ) -> list[MemoryRow]:
        with self.session() as db:
            stmt = select(MemoryRow).where(
                MemoryRow.user_id == user_id,
                col(MemoryRow.deleted_at).is_(None),
            )
            if tenant_id is not None:
                stmt = stmt.where(MemoryRow.tenant_id == tenant_id)
            if pinned_only:
                stmt = stmt.where(MemoryRow.pinned == True)  # noqa: E712
            stmt = stmt.order_by(col(MemoryRow.pinned).desc(), col(MemoryRow.updated_at).desc())
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = list(db.exec(stmt).all())
            for row in rows:
                db.expunge(row)
            return rows

    def soft_delete_memories(self, memory_ids: Sequence[str], deleted_at: str) -> int:
        if not memory_ids:
            return 0
        count = 0
        with self.session() as db:
            for mid in memory_ids:
                row = db.get(MemoryRow, mid)
                if row is None or row.deleted_at is not None:
                    continue
                if row.pinned:
                    # Hard rule: pinned memories are never decay-deleted.
                    continue
                row.deleted_at = deleted_at
                row.updated_at = deleted_at
                count += 1
            db.commit()
        return count

    def list_distinct_user_ids(self) -> list[str]:
        with self.session() as db:
            stmt = (
                select(MemoryRow.user_id)
                .where(col(MemoryRow.deleted_at).is_(None), col(MemoryRow.user_id).is_not(None))
                .distinct()
            )
            return [u for u in db.exec(stmt).all() if u]

    def list_active_memories(
        self,
        *,
        user_id: str | None = None,
        include_orphans: bool = True,
        tenant_id: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryRow]:
        with self.session() as db:
            stmt = select(MemoryRow).where(col(MemoryRow.deleted_at).is_(None))
            if user_id is not None:
                stmt = stmt.where(MemoryRow.user_id == user_id)
            elif not include_orphans:
                stmt = stmt.where(col(MemoryRow.user_id).is_not(None))
            if tenant_id is not None:
                stmt = stmt.where(MemoryRow.tenant_id == tenant_id)
            stmt = stmt.order_by(col(MemoryRow.updated_at).desc())
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = list(db.exec(stmt).all())
            for row in rows:
                db.expunge(row)
            return rows
