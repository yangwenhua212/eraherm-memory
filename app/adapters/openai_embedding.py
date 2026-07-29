# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from typing import Sequence

import httpx


class OpenAICompatibleEmbeddingClient:
    """OpenAI-compatible /embeddings client."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "text-embedding-3-small",
        dimensions: int | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dimensions = dimensions
        self._timeout = timeout
        self._resolved_dim: int | None = dimensions

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        if self._resolved_dim is None:
            raise RuntimeError("dimensions unknown until first embed() call")
        return self._resolved_dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload: dict = {"model": self._model, "input": list(texts)}
        if self._dimensions is not None:
            payload["dimensions"] = self._dimensions
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                f"{self._base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            data = sorted(data, key=lambda x: x["index"])
            vectors = [row["embedding"] for row in data]
        if vectors and self._resolved_dim is None:
            self._resolved_dim = len(vectors[0])
        return vectors
