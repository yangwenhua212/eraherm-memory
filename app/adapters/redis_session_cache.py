# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from typing import Any

from app.models import L1Item


def _item_to_dict(item: L1Item) -> dict[str, Any]:
    return {
        "id": item.id,
        "content": item.content,
        "memory_type": item.memory_type,
        "importance": item.importance,
        "weight": item.weight,
        "pinned": item.pinned,
        "user_id": item.user_id,
        "tenant_id": item.tenant_id,
        "session_id": item.session_id,
        "meta": item.meta,
        "created_at": item.created_at,
    }


def _item_from_dict(data: dict[str, Any]) -> L1Item:
    return L1Item(
        id=data["id"],
        content=data["content"],
        memory_type=data.get("memory_type", "fact"),
        importance=float(data.get("importance", 0.5)),
        weight=float(data.get("weight", 1.0)),
        pinned=bool(data.get("pinned", False)),
        user_id=data.get("user_id"),
        tenant_id=data.get("tenant_id"),
        session_id=data.get("session_id"),
        meta=data.get("meta") or {},
        created_at=data.get("created_at"),
    )


class RedisSessionCache:
    """L1 session cache backed by Redis list (JSON items)."""

    def __init__(
        self,
        *,
        url: str = "redis://localhost:6379/0",
        key_prefix: str = "eraherm:l1:",
        client=None,
    ) -> None:
        if client is not None:
            self._r = client
        else:
            try:
                import redis
            except ImportError as exc:  # pragma: no cover
                raise ImportError("Install redis extra: pip install 'eraherm-memory[redis]'") from exc
            self._r = redis.Redis.from_url(url, decode_responses=True)
        self._prefix = key_prefix

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    def append(self, session_id: str, item: L1Item) -> None:
        self._r.rpush(self._key(session_id), json.dumps(_item_to_dict(item), ensure_ascii=False))

    def list(self, session_id: str) -> list[L1Item]:
        raw = self._r.lrange(self._key(session_id), 0, -1)
        return [_item_from_dict(json.loads(x)) for x in raw]

    def clear(self, session_id: str) -> int:
        key = self._key(session_id)
        n = self._r.llen(key)
        self._r.delete(key)
        return int(n)

    def drop_lowest(self, session_id: str, keep: int) -> int:
        items = self.list(session_id)
        if len(items) <= keep:
            return 0
        ranked = sorted(items, key=lambda x: (x.importance * x.weight, x.created_at), reverse=True)
        kept = ranked[:keep]
        dropped = len(items) - len(kept)
        key = self._key(session_id)
        pipe = self._r.pipeline()
        pipe.delete(key)
        if kept:
            pipe.rpush(key, *[json.dumps(_item_to_dict(i), ensure_ascii=False) for i in kept])
        pipe.execute()
        return dropped
