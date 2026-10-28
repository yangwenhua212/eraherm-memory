# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

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
from app.security import safe_filename

if TYPE_CHECKING:  # pragma: no cover
    from app.memory.service import MemoryService


@dataclass
class L3DumpResult:
    archive_id: str
    uri: str
    checksum: str
    memory_count: int
    entity_count: int
    relation_count: int


@dataclass
class L3RestoreResult:
    restored_memories: int = 0
    skipped_existing: int = 0
    reembedded: int = 0
    errors: list[str] = field(default_factory=list)


class L3ArchiveService:
    def __init__(
        self,
        *,
        engine,
        archive_store: ArchiveStore,
        memory: "MemoryService | None" = None,
    ) -> None:
        self.engine = engine
        self.archive_store = archive_store
        # 恢复出来的记忆需要重新建立向量（否则只能靠词法路径召回）
        self.memory = memory

    def _get_archive(self, archive_id: str) -> L3ArchiveRow:
        with Session(self.engine) as db:
            row = db.get(L3ArchiveRow, archive_id)
            if row is None:
                raise KeyError(f"archive not found: {archive_id}")
            db.expunge(row)
            return row

    def restore(self, archive_id: str) -> L3RestoreResult:
        """从归档 JSON 恢复记忆（只补缺失的 id，不覆盖已存在的行）。

        以前 l3 dump 是「只写不读」的单向操作 —— 归档在，但没有回头路。
        """
        row = self._get_archive(archive_id)
        read = getattr(self.archive_store, "read", None)
        if not callable(read):
            raise ValueError("archive store does not support read(); restore unavailable")
        payload = json.loads(read(row.uri).decode("utf-8"))

        result = L3RestoreResult()
        mem_fields = set(MemoryRow.model_fields)
        restored_ids: list[str] = []
        with Session(self.engine) as db:
            for item in payload.get("memories") or []:
                if not isinstance(item, dict) or not item.get("id"):
                    result.errors.append("skipped malformed memory entry")
                    continue
                if db.get(MemoryRow, item["id"]) is not None:
                    result.skipped_existing += 1
                    continue
                try:
                    data: dict[str, Any] = {
                        k: v for k, v in item.items() if k in mem_fields
                    }
                    db.add(MemoryRow(**data))
                    restored_ids.append(str(item["id"]))
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(f"{item.get('id')}: {exc}")
            db.commit()
        result.restored_memories = len(restored_ids)

        if restored_ids and self.memory is not None:
            result.reembedded = self.memory.reembed_memories(restored_ids)
        return result

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
        # user_id 来自请求体，直接拼进文件名会造成路径穿越（`../../x`）。
        # 这里只保留安全字符、去掉前导点，且 user_id 原值照常写进归档内容。
        suffix = f"_{safe_filename(user_id)}" if user_id else "_all"
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
