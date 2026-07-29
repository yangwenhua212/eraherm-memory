# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

"""CLI: re-embed all memories into the current embedding space.

Use after switching hashing → fastembed/openai (or changing model/dim).
Does **not** keep a dual-track hashing fallback.

Examples:
  python -m app.ops.reembed --dry-run
  python -m app.ops.reembed --orphan-user-id hermes_default
  python -m app.ops.reembed --orphan-policy skip --force
  eraherm-reembed --user-id u_123 --json
"""

from __future__ import annotations

import argparse
import json
import sys

from app.container import build_container
from app.migrate.service import ReembedService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-embed EraHerm memories into the active embedding backend"
    )
    parser.add_argument("--user-id", default=None, help="Limit to one user_id")
    parser.add_argument(
        "--orphan-policy",
        choices=("assign", "skip", "fail"),
        default="assign",
        help="How to handle memories with user_id=None (default: assign)",
    )
    parser.add_argument(
        "--orphan-user-id",
        default=None,
        help="Target user_id when --orphan-policy=assign",
    )
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed even when model/dim/user_id already match",
    )
    parser.add_argument("--dry-run", action="store_true", help="Scan only, write nothing")
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Do not delete dangling vectors without an active memory",
    )
    parser.add_argument(
        "--recreate-collection",
        action="store_true",
        help="Qdrant: drop/recreate collection when embedding dim changed",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args(argv)

    container = build_container()
    mem = container.memory_service
    svc = ReembedService(
        repo=mem.repo,
        embedding=mem.embedding,
        vectors=mem.vectors,
        settings=container.settings,
    )
    report = svc.run(
        user_id=args.user_id,
        orphan_policy=args.orphan_policy,
        orphan_user_id=args.orphan_user_id,
        batch_size=args.batch_size,
        force=args.force,
        dry_run=args.dry_run,
        cleanup_dangling=not args.no_cleanup,
        recreate_collection=args.recreate_collection,
    )

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(
            f"model={report.target_model} dim={report.target_dim} dry_run={report.dry_run}\n"
            f"scanned={report.scanned} reembedded={report.reembedded} "
            f"skipped_current={report.skipped_current}\n"
            f"orphans_assigned={report.orphans_assigned} "
            f"orphans_skipped={report.orphans_skipped} "
            f"dangling_removed={report.dangling_vectors_removed}"
        )
        for err in report.errors:
            print(f"ERROR: {err}", file=sys.stderr)

    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
