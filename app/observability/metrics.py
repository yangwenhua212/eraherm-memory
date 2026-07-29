# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class MetricsRegistry:
    """Process-local counters (swap to Prometheus later)."""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def incr(self, name: str, value: int = 1) -> None:
        with self._lock:
            self.counters[name] += value

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self.counters.items()))


METRICS = MetricsRegistry()
