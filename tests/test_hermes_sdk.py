# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

"""SDK surface used by Hermes host."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from eraherm_memory import MemoryClient


@pytest.fixture()
def sdk_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "sdk.db"
    monkeypatch.setenv("ERAHERM_DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("ERAHERM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ERAHERM_ADMIN_TOKEN", "test-admin")
    monkeypatch.setenv("ERAHERM_EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("ERAHERM_EMBEDDING_DIM", "64")
    monkeypatch.setenv("ERAHERM_JSON_LOGS", "false")
    monkeypatch.setenv("ERAHERM_EXTRACT_ON_REMEMBER", "false")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as http:
        class _Shim:
            def __init__(self, c: TestClient):
                self._c = c

            def request(self, method, url, **kwargs):
                return self._c.request(method, url, **kwargs)

            def get(self, url, **kwargs):
                return self._c.get(url, **kwargs)

            def post(self, url, **kwargs):
                return self._c.post(url, **kwargs)

        client = MemoryClient("http://testserver")
        client._client = _Shim(http)  # type: ignore[assignment]
        yield client
    get_settings.cache_clear()


def test_sdk_pin_and_consolidate(sdk_client: MemoryClient):
    mem = sdk_client.remember(
        content="数据库使用 MySQL",
        user_id="u_sdk",
        importance=0.9,
        extract_graph=False,
    )
    assert "alerts" in mem
    pinned = sdk_client.pin(user_id="u_sdk", content="用户名为 hermes", memory_type="identity")
    assert pinned["pinned"] is True

    recall = sdk_client.recall(user_id="u_sdk", query="用户名")
    assert "items" in recall
    assert "recommendations" in recall
    assert any("hermes" in i["content"] for i in recall["items"])

    out = sdk_client.consolidate(admin_token="test-admin", user_id="u_sdk")
    assert "reports" in out
