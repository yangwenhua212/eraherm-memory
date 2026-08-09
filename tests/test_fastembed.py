# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.adapters.fastembed_embedding import (
    DEFAULT_FASTEMBED_MODEL,
    FastEmbedEmbeddingClient,
)
from app.config import Settings
from app.container import build_embedding_client


def _install_fake_fastembed(monkeypatch: pytest.MonkeyPatch, fake_model: MagicMock) -> MagicMock:
    fake_cls = MagicMock(return_value=fake_model)
    fake_cls.list_supported_models.return_value = []
    fake_mod = SimpleNamespace(TextEmbedding=fake_cls)
    monkeypatch.setitem(__import__("sys").modules, "fastembed", fake_mod)
    return fake_cls


def test_fastembed_adapter_embeds_with_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model = MagicMock()
    fake_model.embed.return_value = iter([[0.6, 0.8], [1.0, 0.0]])
    _install_fake_fastembed(monkeypatch, fake_model)

    client = FastEmbedEmbeddingClient(model_name="custom/tiny-test", dimensions=2)
    out = client.embed(["你好", "世界"])
    assert out == [[0.6, 0.8], [1.0, 0.0]]
    assert client.model_name == "custom/tiny-test"
    assert client.dimensions == 2
    fake_model.embed.assert_called_once_with(["你好", "世界"])


def test_fastembed_dim_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_fastembed(monkeypatch, MagicMock())

    with pytest.raises(ValueError, match="ERAHERM_EMBEDDING_DIM"):
        FastEmbedEmbeddingClient(
            model_name=DEFAULT_FASTEMBED_MODEL,
            dimensions=256,
        )


def test_build_embedding_client_fastembed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model = MagicMock()
    fake_cls = _install_fake_fastembed(monkeypatch, fake_model)

    settings = Settings(
        embedding_backend="fastembed",
        embedding_model="text-embedding-3-small",  # should fall back to bge-zh
        embedding_dim=512,
    )
    client = build_embedding_client(settings)
    assert client.model_name == DEFAULT_FASTEMBED_MODEL
    assert client.dimensions == 512
    fake_cls.assert_called_once()
    assert fake_cls.call_args.kwargs["model_name"] == DEFAULT_FASTEMBED_MODEL


def test_fastembed_import_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _deny_fastembed(name: str, *args, **kwargs):
        if name == "fastembed" or name.startswith("fastembed."):
            raise ImportError("nope")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _deny_fastembed)
    with pytest.raises(ImportError, match=r"eraherm-memory\[fastembed\]"):
        FastEmbedEmbeddingClient(model_name=DEFAULT_FASTEMBED_MODEL, dimensions=512)
