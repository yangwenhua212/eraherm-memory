# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models import L1Item


@runtime_checkable
class SessionCache(Protocol):
    def append(self, session_id: str, item: L1Item) -> None: ...

    def list(self, session_id: str) -> list[L1Item]: ...

    def clear(self, session_id: str) -> int: ...

    def drop_lowest(self, session_id: str, keep: int) -> int: ...
