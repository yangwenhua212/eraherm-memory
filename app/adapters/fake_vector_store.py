# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Sequence

from app.adapters.sqlite_vector_store import cosine
from app.ports.vector_store import VectorHit


class FakeVectorStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str | None, str, list[float]]] = {}

    def upsert(
        self,
        *,
        memory_id: str,
        user_id: str | None,
        vector: Sequence[float],
        model: str,
    ) -> None:
        self._data[memory_id] = (user_id, model, [float(v) for v in vector])

    def delete(self, memory_ids: Sequence[str]) -> int:
        n = 0
        for mid in memory_ids:
            if self._data.pop(mid, None) is not None:
                n += 1
        return n

    def get_meta(self, memory_id: str) -> dict | None:
        row = self._data.get(memory_id)
        if row is None:
            return None
        uid, model, vec = row
        return {"user_id": uid, "model": model, "dim": len(vec)}

    def list_memory_ids(self) -> list[str]:
        return list(self._data.keys())

    def search(
        self,
        *,
        query: Sequence[float],
        user_id: str,
        top_k: int,
    ) -> list[VectorHit]:
        hits: list[VectorHit] = []
        for mid, (uid, _model, vec) in self._data.items():
            if uid != user_id:
                continue
            hits.append(VectorHit(memory_id=mid, score=cosine(query, vec)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]
