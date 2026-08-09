# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable


@dataclass
class Job:
    name: str
    payload: dict[str, Any]


@runtime_checkable
class JobQueue(Protocol):
    def enqueue(self, job: Job) -> None: ...


class InMemoryJobQueue:
    """Thread-backed FIFO queue for async reflection (swap to ARQ/Redis later)."""

    def __init__(self, handler: Callable[[Job], None]) -> None:
        self._handler = handler
        self._q: deque[Job] = deque()
        self._cv = threading.Condition()
        self._stop = False
        self._thread = threading.Thread(target=self._loop, name="eraherm-jobs", daemon=True)
        self._thread.start()

    def enqueue(self, job: Job) -> None:
        with self._cv:
            self._q.append(job)
            self._cv.notify()

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        self._thread.join(timeout=2)

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._q and not self._stop:
                    self._cv.wait(timeout=0.5)
                if self._stop and not self._q:
                    return
                job = self._q.popleft()
            try:
                self._handler(job)
            except Exception:  # noqa: BLE001
                # Keep worker alive; failures recorded by handler into reflection status.
                pass
