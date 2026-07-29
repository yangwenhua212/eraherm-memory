# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from app.ports.vector_store import VectorHit


class QdrantVectorStore:
    """VectorStore adapter for Qdrant (server or local :memory: / path)."""

    def __init__(
        self,
        *,
        url: str | None = None,
        api_key: str | None = None,
        path: str | None = None,
        collection: str = "eraherm_memories",
        vector_size: int = 256,
    ) -> None:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qm
        except ImportError as exc:  # pragma: no cover
            raise ImportError("Install qdrant extra: pip install 'eraherm-memory[qdrant]'") from exc

        self._qm = qm
        if path:
            self._client = QdrantClient(path=path)
        elif url:
            self._client = QdrantClient(url=url, api_key=api_key)
        else:
            self._client = QdrantClient(location=":memory:")
        self._collection = collection
        self._vector_size = vector_size
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        names = {c.name for c in self._client.get_collections().collections}
        if self._collection not in names:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=self._qm.VectorParams(
                    size=self._vector_size,
                    distance=self._qm.Distance.COSINE,
                ),
            )

    def upsert(
        self,
        *,
        memory_id: str,
        user_id: str | None,
        vector: Sequence[float],
        model: str,
    ) -> None:
        point = self._qm.PointStruct(
            id=self._point_id(memory_id),
            vector=[float(v) for v in vector],
            payload={
                "memory_id": memory_id,
                "user_id": user_id,
                "model": model,
            },
        )
        self._client.upsert(collection_name=self._collection, points=[point])

    def delete(self, memory_ids: Sequence[str]) -> int:
        if not memory_ids:
            return 0
        ids = [self._point_id(mid) for mid in memory_ids]
        self._client.delete(
            collection_name=self._collection,
            points_selector=self._qm.PointIdsList(points=ids),
        )
        return len(memory_ids)

    def search(
        self,
        *,
        query: Sequence[float],
        user_id: str,
        top_k: int,
    ) -> list[VectorHit]:
        qfilter = self._qm.Filter(
            must=[self._qm.FieldCondition(key="user_id", match=self._qm.MatchValue(value=user_id))]
        )
        vector = [float(v) for v in query]
        # qdrant-client >=1.12 uses query_points; older used search
        if hasattr(self._client, "query_points"):
            raw = self._client.query_points(
                collection_name=self._collection,
                query=vector,
                query_filter=qfilter,
                limit=top_k,
            )
            results = raw.points
        else:  # pragma: no cover
            results = self._client.search(
                collection_name=self._collection,
                query_vector=vector,
                query_filter=qfilter,
                limit=top_k,
            )
        hits: list[VectorHit] = []
        for r in results:
            payload = r.payload or {}
            mid = payload.get("memory_id")
            if not mid:
                continue
            hits.append(VectorHit(memory_id=str(mid), score=float(r.score)))
        return hits

    @staticmethod
    def _point_id(memory_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, memory_id))
