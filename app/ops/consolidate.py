# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""CLI: run memory consolidation once.

  python -m app.ops.consolidate
  python -m app.ops.consolidate --user-id u_123
  python -m app.ops.consolidate --dry-run      # 只看会动什么，不落库

推荐用 CLI / 独立进程而不是 API 进程内的 scheduler：后者在每个 uvicorn worker
里都会起一份（现在有跨进程文件锁兜底，但独立进程更干净）。
"""

from __future__ import annotations

import argparse
import json
import sys

from app.container import build_container


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run EraHerm memory consolidation")
    parser.add_argument("--user-id", default=None, help="Limit to one user_id")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would change; do not write anything",
    )
    args = parser.parse_args(argv)

    container = build_container()
    svc = container.consolidation_service
    if svc is None:
        print("consolidation service unavailable", file=sys.stderr)
        return 1

    if args.user_id:
        reports = [svc.run_for_user(args.user_id, dry_run=args.dry_run)]
    else:
        # 跨进程互斥：多 worker / 与 API 进程内的 scheduler 同时跑时只执行一次
        reports = svc.consolidate_all(dry_run=args.dry_run)

    payload = [r.to_dict() for r in reports]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for r in reports:
            if r.skipped_reason:
                print(f"user={r.user_id} SKIPPED: {r.skipped_reason}")
                continue
            print(
                f"user={r.user_id} reweighted={r.reweighted} forgotten={r.forgotten} "
                f"compressed={r.compressed_clusters} conflicts={r.conflicts_resolved}"
                + (" [dry-run]" if r.dry_run else "")
                + (f" archive={r.archive_id}" if r.archive_id else "")
            )
        print(f"users={len(reports)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
