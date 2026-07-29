# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session, col, select

from app.models import (
    EntityRow,
    L3ArchiveRow,
    MemoryRow,
    RelationRow,
    new_id,
    utc_now_iso,
)
from app.ports.archive_store import ArchiveStore


@dataclass
class L3DumpResult:
    archive_id: str
    uri: str
    checksum: str
    memory_count: int
    entity_count: int
    relation_count: int


class L3ArchiveService:
    def __init__(self, *, engine, archive_store: ArchiveStore) -> None:
        self.engine = engine
        self.archive_store = archive_store

    def dump(self, *, user_id: str | None = None) -> L3DumpResult:
        with Session(self.engine) as db:
            mem_stmt = select(MemoryRow).where(col(MemoryRow.deleted_at).is_(None))
            ent_stmt = select(EntityRow)
            rel_stmt = select(RelationRow).where(col(RelationRow.deleted_at).is_(None))
            if user_id:
                mem_stmt = mem_stmt.where(MemoryRow.user_id == user_id)
                ent_stmt = ent_stmt.where(EntityRow.user_id == user_id)
                rel_stmt = rel_stmt.where(RelationRow.user_id == user_id)
            memories = list(db.exec(mem_stmt).all())
            entities = list(db.exec(ent_stmt).all())
            relations = list(db.exec(rel_stmt).all())

        payload = {
            "version": 1,
            "dumped_at": utc_now_iso(),
            "user_id": user_id,
            "memories": [_row_dict(m) for m in memories],
            "entities": [_row_dict(e) for e in entities],
            "relations": [_row_dict(r) for r in relations],
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = f"_{user_id}" if user_id else "_all"
        relative = f"dump_{stamp}{suffix}.json"
        put = self.archive_store.put(relative_name=relative, payload=body)

        row = L3ArchiveRow(
            id=new_id("l3"),
            uri=put.uri,
            checksum=put.checksum,
            memory_count=len(memories),
            entity_count=len(entities),
            relation_count=len(relations),
            created_at=utc_now_iso(),
        )
        with Session(self.engine) as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            db.expunge(row)

        return L3DumpResult(
            archive_id=row.id,
            uri=row.uri,
            checksum=row.checksum,
            memory_count=row.memory_count,
            entity_count=row.entity_count,
            relation_count=row.relation_count,
        )

    def list_archives(self, *, limit: int = 20) -> list[L3ArchiveRow]:
        with Session(self.engine) as db:
            stmt = select(L3ArchiveRow).order_by(col(L3ArchiveRow.created_at).desc()).limit(limit)
            rows = list(db.exec(stmt).all())
            for row in rows:
                db.expunge(row)
            return rows


def _row_dict(row) -> dict:
    data = row.model_dump()
    # bytes not expected on these tables
    return {k: v for k, v in data.items()}
