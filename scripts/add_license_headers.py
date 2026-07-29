#!/usr/bin/env python3
# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md
"""Add SPDX copyright headers to project Python sources (idempotent)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER_LINES = [
    "# Copyright (c) 2026 EraHerm-Memory Authors.",
    "# SPDX-License-Identifier: AGPL-3.0-only",
    "# Commercial licensing: see COMMERCIAL.md",
]
HEADER = "\n".join(HEADER_LINES) + "\n"

SKIP_DIRS = {
    ".venv",
    "venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    "eraherm_memory.egg-info",
    "storage",
    "dist",
    "build",
}


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def main() -> None:
    updated = 0
    for path in sorted(ROOT.rglob("*.py")):
        if should_skip(path):
            continue
        text = path.read_text(encoding="utf-8")
        if "SPDX-License-Identifier: AGPL-3.0-only" in text:
            continue

        if text.startswith("#!"):
            line0, _, rest = text.partition("\n")
            new_text = line0 + "\n" + HEADER + rest.lstrip("\n")
            if not rest.startswith("\n") and rest:
                new_text = line0 + "\n" + HEADER + "\n" + rest
        else:
            new_text = HEADER + "\n" + text

        path.write_text(new_text, encoding="utf-8")
        updated += 1
        print(path.relative_to(ROOT).as_posix())
    print(f"updated={updated}")


if __name__ == "__main__":
    main()
