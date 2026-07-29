# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from collections import defaultdict

from app.models import L1Item


class InMemorySessionCache:
    """L1 session cache (process-local)."""

    def __init__(self) -> None:
        self._items: dict[str, list[L1Item]] = defaultdict(list)

    def append(self, session_id: str, item: L1Item) -> None:
        self._items[session_id].append(item)

    def list(self, session_id: str) -> list[L1Item]:
        return list(self._items.get(session_id, []))

    def clear(self, session_id: str) -> int:
        items = self._items.pop(session_id, [])
        return len(items)

    def drop_lowest(self, session_id: str, keep: int) -> int:
        items = self._items.get(session_id, [])
        if len(items) <= keep:
            return 0
        ranked = sorted(items, key=lambda x: (x.importance * x.weight, x.created_at), reverse=True)
        kept = ranked[:keep]
        dropped = len(items) - len(kept)
        self._items[session_id] = kept
        return dropped
