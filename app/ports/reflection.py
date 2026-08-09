# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


@dataclass
class ReflectionDraft:
    analysis: str
    summary: str
    confidence: float
    memory_type: str = "reflection"  # reflection | negative | fact
    pinned: bool = False


@runtime_checkable
class ReflectionPipeline(Protocol):
    def reflect(
        self,
        *,
        feedback_type: str,
        correction_text: str | None,
        answer_text: str | None,
        related_contents: Sequence[str],
    ) -> ReflectionDraft: ...
