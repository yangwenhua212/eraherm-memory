# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class EmbeddingClient(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    @property
    def is_remote(self) -> bool:
        """True = 文本会离开本机（远端 API）。用于敏感内容的 fail-closed 判定。"""
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
