# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ArchivePutResult:
    uri: str
    checksum: str
    bytes_written: int


@runtime_checkable
class ArchiveStore(Protocol):
    def put(self, *, relative_name: str, payload: bytes) -> ArchivePutResult: ...

    def list(self) -> list[str]: ...
