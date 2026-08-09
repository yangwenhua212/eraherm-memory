# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""CLI: dump L2 memories/graph to L3 cold archive.

Usage:
  python -m app.ops.l3_dump
  python -m app.ops.l3_dump --user-id u_123
"""

from __future__ import annotations

import argparse
import json

from app.adapters.filesystem_archive import FilesystemArchiveStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.archive.service import L3ArchiveService
from app.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="EraHerm L3 cold dump")
    parser.add_argument("--user-id", default=None, help="Optional user filter")
    args = parser.parse_args()

    settings = get_settings()
    repo = SqliteMemoryRepository(settings.database_url)
    archive = FilesystemArchiveStore(settings.data_dir / "l3")
    service = L3ArchiveService(engine=repo.engine, archive_store=archive)
    result = service.dump(user_id=args.user_id)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
