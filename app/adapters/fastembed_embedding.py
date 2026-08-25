# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Sequence

# Common FastEmbed dense models and their fixed output dims.
# Source: https://qdrant.github.io/fastembed/examples/Supported_Models/
_KNOWN_DIMS: dict[str, int] = {
    "BAAI/bge-small-zh-v1.5": 512,
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "BAAI/bge-m3": 1024,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 384,
    "intfloat/multilingual-e5-large": 1024,
}

DEFAULT_FASTEMBED_MODEL = "BAAI/bge-small-zh-v1.5"


class FastEmbedEmbeddingClient:
    """Local ONNX embedding via [fastembed](https://github.com/qdrant/fastembed).

    Recommended for Chinese Hermes / production when you want real semantics
    without calling an external embedding API. Default model is
    ``BAAI/bge-small-zh-v1.5`` (512-dim).
    """

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_FASTEMBED_MODEL,
        dimensions: int | None = None,
        cache_dir: str | None = None,
        lazy_load: bool = False,
    ) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - exercised via unit test mock path
            raise ImportError(
                "fastembed is required for embedding_backend=fastembed. "
                "Install with: pip install 'eraherm-memory[fastembed]'"
            ) from exc

        self._model_name = model_name
        expected = _resolve_model_dim(model_name)
        if dimensions is not None and expected is not None and dimensions != expected:
            raise ValueError(
                f"ERAHERM_EMBEDDING_DIM={dimensions} does not match model "
                f"{model_name} (dim={expected}). Set ERAHERM_EMBEDDING_DIM={expected}."
            )
        self._dim = dimensions or expected
        kwargs: dict = {"model_name": model_name, "lazy_load": lazy_load}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        self._model = TextEmbedding(**kwargs)
        if self._dim is None:
            # Unknown model: probe once so vector store / health can rely on dimensions.
            probe = self.embed(["__eraherm_dim_probe__"])
            self._dim = len(probe[0])

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        if self._dim is None:
            raise RuntimeError("dimensions unknown")
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for raw in self._model.embed(list(texts)):
            vec = raw.tolist() if hasattr(raw, "tolist") else list(raw)
            vectors.append([float(x) for x in vec])
        if vectors and self._dim is None:
            self._dim = len(vectors[0])
        elif vectors and len(vectors[0]) != self._dim:
            raise RuntimeError(
                f"fastembed returned dim={len(vectors[0])}, expected {self._dim}"
            )
        return vectors


def _resolve_model_dim(model_name: str) -> int | None:
    if model_name in _KNOWN_DIMS:
        return _KNOWN_DIMS[model_name]
    try:
        from fastembed import TextEmbedding

        for meta in TextEmbedding.list_supported_models():
            name = meta.get("model") if isinstance(meta, dict) else getattr(meta, "model", None)
            dim = meta.get("dim") if isinstance(meta, dict) else getattr(meta, "dim", None)
            if name == model_name and isinstance(dim, int):
                return dim
    except Exception:
        return None
    return None
