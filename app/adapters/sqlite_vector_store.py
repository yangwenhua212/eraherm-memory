# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import struct
from typing import Optional, Sequence

from sqlalchemy import Column, LargeBinary
from sqlmodel import Field, Session, SQLModel, col, create_engine, select

from app.models import utc_now_iso
from app.ports.vector_store import VectorHit


class EmbeddingRow(SQLModel, table=True):
    __tablename__ = "embeddings"

    memory_id: str = Field(primary_key=True)
    user_id: Optional[str] = Field(default=None, index=True)
    model: str = Field(default="")
    dim: int = Field(default=0)
    vector: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: str = Field(default_factory=utc_now_iso)


def pack_vector(vector: Sequence[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *[float(v) for v in vector])


def unpack_vector(blob: bytes, dim: int) -> list[float]:
    return list(struct.unpack(f"{dim}f", blob))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = sum(a[i] * b[i] for i in range(n))
    na = sum(a[i] * a[i] for i in range(n)) ** 0.5
    nb = sum(b[i] * b[i] for i in range(n)) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class SqliteVectorStore:
    """SQLite BLOB vectors + in-process cosine search (replaceable by Qdrant later)."""

    def __init__(self, database_url: str, engine=None) -> None:
        if engine is not None:
            self.engine = engine
        else:
            connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
            self.engine = create_engine(database_url, connect_args=connect_args)
        SQLModel.metadata.create_all(self.engine)

    def upsert(
        self,
        *,
        memory_id: str,
        user_id: str | None,
        vector: Sequence[float],
        model: str,
    ) -> None:
        blob = pack_vector(vector)
        row = EmbeddingRow(
            memory_id=memory_id,
            user_id=user_id,
            model=model,
            dim=len(vector),
            vector=blob,
            created_at=utc_now_iso(),
        )
        with Session(self.engine) as db:
            existing = db.get(EmbeddingRow, memory_id)
            if existing is None:
                db.add(row)
            else:
                existing.user_id = user_id
                existing.model = model
                existing.dim = len(vector)
                existing.vector = blob
                existing.created_at = row.created_at
            db.commit()

    def delete(self, memory_ids: Sequence[str]) -> int:
        if not memory_ids:
            return 0
        count = 0
        with Session(self.engine) as db:
            for mid in memory_ids:
                row = db.get(EmbeddingRow, mid)
                if row is not None:
                    db.delete(row)
                    count += 1
            db.commit()
        return count

    def get_meta(self, memory_id: str) -> dict | None:
        with Session(self.engine) as db:
            row = db.get(EmbeddingRow, memory_id)
            if row is None:
                return None
            return {"user_id": row.user_id, "model": row.model, "dim": row.dim}

    def list_memory_ids(self) -> list[str]:
        with Session(self.engine) as db:
            rows = list(db.exec(select(EmbeddingRow.memory_id)).all())
        return [str(mid) for mid in rows]

    def search(
        self,
        *,
        query: Sequence[float],
        user_id: str,
        top_k: int,
    ) -> list[VectorHit]:
        with Session(self.engine) as db:
            stmt = select(EmbeddingRow).where(EmbeddingRow.user_id == user_id)
            rows = list(db.exec(stmt).all())
        scored: list[VectorHit] = []
        for row in rows:
            vec = unpack_vector(row.vector, row.dim)
            scored.append(VectorHit(memory_id=row.memory_id, score=cosine(query, vec)))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]
