# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
from pathlib import Path

from app.ports.archive_store import ArchivePutResult
from app.security import resolve_within


class FilesystemArchiveStore:
    """L3 cold archive on local filesystem (swap to S3 later)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, *, relative_name: str, payload: bytes) -> ArchivePutResult:
        # 路径收敛：拒绝绝对路径/盘符/UNC，以及解析后逃出 root 的 `..` 组合。
        # 以前这里是裸 `self.root / relative_name`，而 relative_name 里带着
        # 调用方传入的 user_id → 可写到归档目录之外。
        path = resolve_within(self.root, relative_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        checksum = hashlib.sha256(payload).hexdigest()
        return ArchivePutResult(
            uri=str(path.resolve()),
            checksum=checksum,
            bytes_written=len(payload),
        )

    def read(self, uri: str) -> bytes:
        """按 url 读取归档内容；越出归档根一律拒绝。

        uri 来自我们自己的 l3_archives 表，但仍然做一次收敛 —— 表可以被写坏，
        而「读任意文件」的代价太大。
        """
        root = self.root.resolve()
        path = Path(uri).resolve()
        if path != root and not path.is_relative_to(root):
            raise ValueError(f"refusing to read outside archive root: {path}")
        return path.read_bytes()

    def list(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(str(p.resolve()) for p in self.root.rglob("*") if p.is_file())
