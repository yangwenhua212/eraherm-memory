# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

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
