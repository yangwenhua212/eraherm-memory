# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class VectorHit:
    memory_id: str
    score: float  # cosine similarity in [-1, 1], typically [0, 1] for normalized


@runtime_checkable
class VectorStore(Protocol):
    def upsert(
        self,
        *,
        memory_id: str,
        user_id: str | None,
        vector: Sequence[float],
        model: str,
    ) -> None: ...

    def delete(self, memory_ids: Sequence[str]) -> int: ...

    def search(
        self,
        *,
        query: Sequence[float],
        user_id: str,
        top_k: int,
    ) -> list[VectorHit]: ...
