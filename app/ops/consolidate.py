# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

"""CLI: run memory consolidation once.

  python -m app.ops.consolidate
  python -m app.ops.consolidate --user-id u_123
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
    args = parser.parse_args(argv)

    container = build_container()
    svc = container.consolidation_service
    if svc is None:
        print("consolidation service unavailable", file=sys.stderr)
        return 1

    if args.user_id:
        reports = [svc.run_for_user(args.user_id)]
    else:
        reports = svc.run_all()

    payload = [r.to_dict() for r in reports]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for r in reports:
            print(
                f"user={r.user_id} reweighted={r.reweighted} forgotten={r.forgotten} "
                f"compressed={r.compressed_clusters} conflicts={r.conflicts_resolved}"
            )
        print(f"users={len(reports)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
