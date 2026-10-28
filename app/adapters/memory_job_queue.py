# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

from app.observability.logging import logger


@dataclass
class Job:
    name: str
    payload: dict[str, Any]


@runtime_checkable
class JobQueue(Protocol):
    def enqueue(self, job: Job) -> None: ...


class InMemoryJobQueue:
    """Thread-backed FIFO queue for async reflection (swap to ARQ/Redis later).

    明确的取舍与护栏：

    - **进程内**：重启即丢任务；多 worker 下提交到 A、轮询打到 B 会永远 pending。
      要可靠投递请换 ARQ/Redis（见 DEPLOYMENT.md 的升级路径）。
    - **有界**：``max_size`` 装不下时丢弃**最旧**的任务并计数/log。
      以前 deque 无上限，而 LLM 反射比提交慢时它会无界增长。
    - **可关闭**：``stop()`` 会被 lifespan 调用（以前从不调用 → daemon 线程泄漏）。
    """

    def __init__(self, handler: Callable[[Job], None], *, max_size: int = 1000) -> None:
        self._handler = handler
        self._q: deque[Job] = deque()
        self._cv = threading.Condition()
        self._stop = False
        self._max_size = max(1, int(max_size))
        self.dropped_total = 0
        self._thread = threading.Thread(target=self._loop, name="eraherm-jobs", daemon=True)
        self._thread.start()

    def enqueue(self, job: Job) -> None:
        with self._cv:
            while len(self._q) >= self._max_size:
                self._q.popleft()
                self.dropped_total += 1
            if self.dropped_total:
                # 只提示一次量级，避免日志被刷爆
                logger.warning(
                    "job_queue_overflow",
                    extra={
                        "detail": (
                            f"queue full (max_size={self._max_size}); dropped oldest job(s), "
                            f"total dropped={self.dropped_total}. "
                            "Async reflection cannot keep up — lower feedback volume or switch to ARQ/Redis."
                        )
                    },
                )
                self.dropped_total = 0
            self._q.append(job)
            self._cv.notify()

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if self._thread.is_alive():
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
