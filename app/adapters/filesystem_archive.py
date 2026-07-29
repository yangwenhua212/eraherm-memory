# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

import hashlib
from pathlib import Path

from app.ports.archive_store import ArchivePutResult


class FilesystemArchiveStore:
    """L3 cold archive on local filesystem (swap to S3 later)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, *, relative_name: str, payload: bytes) -> ArchivePutResult:
        path = self.root / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        checksum = hashlib.sha256(payload).hexdigest()
        return ArchivePutResult(
            uri=str(path.resolve()),
            checksum=checksum,
            bytes_written=len(payload),
        )

    def list(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(str(p.resolve()) for p in self.root.rglob("*") if p.is_file())
