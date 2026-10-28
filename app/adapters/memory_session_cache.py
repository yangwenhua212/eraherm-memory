# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from app.models import L1Item


class InMemorySessionCache:
    """L1 session cache (process-local).

    带容量上限：以前任意 `session_id` 都能让这个 dict 无界增长
    （一个可远程触发的内存放大面）。超出上限时淘汰「最久未被写入」的会话。
    """

    def __init__(self, *, max_sessions: int = 2000) -> None:
        self._items: dict[str, list[L1Item]] = {}
        self._max_sessions = max(1, int(max_sessions))

    def _touch(self, session_id: str) -> None:
        """把会话移到 MRU 位置（dict 保持插入序）。"""
        if session_id in self._items:
            self._items[session_id] = self._items.pop(session_id)

    def _evict_if_needed(self) -> None:
        while len(self._items) > self._max_sessions:
            oldest = next(iter(self._items), None)
            if oldest is None:
                break
            self._items.pop(oldest, None)

    def append(self, session_id: str, item: L1Item) -> None:
        self._touch(session_id)
        self._items.setdefault(session_id, []).append(item)
        self._evict_if_needed()

    def list(self, session_id: str) -> list[L1Item]:
        self._touch(session_id)
        return list(self._items.get(session_id, []))

    def clear(self, session_id: str) -> int:
        items = self._items.pop(session_id, [])
        return len(items)

    def drop_lowest(self, session_id: str, keep: int) -> int:
        items = self._items.get(session_id, [])
        if len(items) <= keep:
            return 0
        ranked = sorted(
            items, key=lambda x: (x.importance * x.weight, x.created_at), reverse=True
        )
        kept = ranked[:keep]
        dropped = len(items) - len(kept)
        self._items[session_id] = kept
        return dropped
