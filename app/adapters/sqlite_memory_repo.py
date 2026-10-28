# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Optional, Sequence

from sqlmodel import Session, SQLModel, col, select
from sqlalchemy import func, update

from app.db import create_sqlite_engine
from app.models import MemoryRow, SessionRow


class SqliteMemoryRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_sqlite_engine(database_url)
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

    # --- 定向单语句更新 ---------------------------------------------------
    # 下面三个方法替代「读整行 → 改字段 → merge 回写」。
    # 后者在并发下会丢更新：recall 线程读到 weight=1.0，feedback 线程改成 1.5，
    # recall 再 merge 整行 → weight 被打回 1.0。整行回写 = 用陈旧快照覆盖别的写者。

    def bump_access(self, memory_ids: Sequence[str], accessed_at: str) -> int:
        """一条 UPDATE 累加访问计数与时间，不整行回写。"""
        ids = [m for m in memory_ids if m]
        if not ids:
            return 0
        stmt = (
            update(MemoryRow)
            .where(MemoryRow.id.in_(ids), col(MemoryRow.deleted_at).is_(None))
            .values(access_count=MemoryRow.access_count + 1, last_accessed_at=accessed_at)
        )
        with self.session() as db:
            result = db.execute(stmt)
            db.commit()
            return int(result.rowcount or 0)

    def add_weight(
        self,
        memory_ids: Sequence[str],
        *,
        delta: float,
        updated_at: str,
        min_weight: float = 0.05,
        max_weight: float = 3.0,
    ) -> int:
        """一条 UPDATE 做带夹取的权重增减（反馈点赞/点踩）。"""
        ids = [m for m in memory_ids if m]
        if not ids or delta == 0:
            return 0
        stmt = (
            update(MemoryRow)
            .where(MemoryRow.id.in_(ids), col(MemoryRow.deleted_at).is_(None))
            .values(
                weight=func.max(min_weight, func.min(max_weight, MemoryRow.weight + delta)),
                updated_at=updated_at,
            )
        )
        with self.session() as db:
            result = db.execute(stmt)
            db.commit()
            return int(result.rowcount or 0)

    def set_weight(self, memory_id: str, *, weight: float, updated_at: str) -> int:
        """只改 weight/updated_at 两列（整理重排用）。"""
        if not memory_id:
            return 0
        stmt = (
            update(MemoryRow)
            .where(MemoryRow.id == memory_id, col(MemoryRow.deleted_at).is_(None))
            .values(weight=weight, updated_at=updated_at)
        )
        with self.session() as db:
            result = db.execute(stmt)
            db.commit()
            return int(result.rowcount or 0)

    def set_weights_bulk(self, updates: Sequence[tuple[str, float, str]]) -> int:
        """批量权重更新：一个连接、一个事务（不要逐行 commit）。"""
        rows = [(mid, float(weight), ts) for mid, weight, ts in updates if mid]
        if not rows:
            return 0
        with self.session() as db:
            for mid, weight, ts in rows:
                db.execute(
                    update(MemoryRow)
                    .where(MemoryRow.id == mid, col(MemoryRow.deleted_at).is_(None))
                    .values(weight=weight, updated_at=ts)
                )
            db.commit()
        return len(rows)

    def supersede(
        self, memory_ids: Sequence[str], *, superseded_by: str, superseded_at: str
    ) -> int:
        ids = [m for m in memory_ids if m and m != superseded_by]
        if not ids:
            return 0
        stmt = (
            update(MemoryRow)
            .where(MemoryRow.id.in_(ids), col(MemoryRow.deleted_at).is_(None))
            .values(
                superseded_by=superseded_by,
                superseded_at=superseded_at,
                updated_at=superseded_at,
            )
        )
        with self.session() as db:
            result = db.execute(stmt)
            db.commit()
            return int(result.rowcount or 0)

    def list_deleted_by_user(
        self, user_id: str, *, limit: int | None = None
    ) -> list[MemoryRow]:
        with self.session() as db:
            stmt = (
                select(MemoryRow)
                .where(
                    MemoryRow.user_id == user_id,
                    col(MemoryRow.deleted_at).is_not(None),
                )
                .order_by(col(MemoryRow.deleted_at).desc())
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = list(db.exec(stmt).all())
            for row in rows:
                db.expunge(row)
            return rows

    def restore_memories(self, memory_ids: Sequence[str]) -> int:
        ids = [m for m in memory_ids if m]
        if not ids:
            return 0
        stmt = (
            update(MemoryRow)
            .where(MemoryRow.id.in_(ids), col(MemoryRow.deleted_at).is_not(None))
            .values(deleted_at=None)
        )
        with self.session() as db:
            result = db.execute(stmt)
            db.commit()
            return int(result.rowcount or 0)

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
