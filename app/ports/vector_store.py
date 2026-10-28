# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class VectorHit:
    memory_id: str
    score: float  # cosine similarity in [-1, 1], typically [0, 1] for normalized


@runtime_checkable
class VectorStore(Protocol):
    def upsert(
        self,
        *,
        memory_id: str,
        user_id: str | None,
        vector: Sequence[float],
        model: str,
        tenant_id: str | None = None,
    ) -> None: ...

    def delete(self, memory_ids: Sequence[str]) -> int: ...

    def get_meta(self, memory_id: str) -> dict | None:
        """返回 {"user_id", "model", "dim"}；不存在返回 None。

        reembed 靠它判断「这条向量是否已经是当前模型/维度」——缺了它就会
        每次都全量重嵌（Qdrant 适配器曾经如此）。
        """
        ...

    def list_memory_ids(self) -> list[str]:
        """列出全部已存向量 id（悬空向量清理用）。"""
        ...

    def search(
        self,
        *,
        query: Sequence[float],
        user_id: str,
        top_k: int,
        tenant_id: str | None = None,
    ) -> list[VectorHit]:
        """按 user_id 检索 top-k。

        ``tenant_id`` 非空时必须**在检索层**过滤（而不是取回 top-k 之后再过滤）——
        否则某租户的候选会被其它租户占满，表现为「本租户有匹配却召回为空」。
        """
        ...
