# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

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

    def read(self, uri: str) -> bytes:
        """按归档 URI 读回内容（l3 restore 用）。

        实现必须拒绝读到归档根之外（见 FilesystemArchiveStore.read）。
        """
        ...

    def list(self) -> list[str]: ...
