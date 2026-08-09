# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Sequence


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,.;:!?，。；：！？、/\-_()（）\[\]{}]+", text.lower()) if t]


class HashingEmbeddingClient:
    """Deterministic local embedding (feature hashing). Zero network dependency.

    Good for tests and offline MVP; swap to OpenAI-compatible via settings.
    """

    def __init__(self, dimensions: int = 256, model_name: str = "hashing-v1") -> None:
        if dimensions < 8:
            raise ValueError("dimensions must be >= 8")
        self._dim = dimensions
        self._model = model_name

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        tokens = _tokenize(text) or ["__empty__"]
        counts = Counter(tokens)
        for token, tf in counts.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self._dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign * (1.0 + math.log(1.0 + tf))
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
