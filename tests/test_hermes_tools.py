# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Hermes built-in tools surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from eraherm_memory import HermesMemoryTools, MemoryClient


@pytest.fixture()
def tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HermesMemoryTools:
    db = tmp_path / "tools.db"
    monkeypatch.setenv("ERAHERM_DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("ERAHERM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ERAHERM_EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("ERAHERM_EMBEDDING_DIM", "64")
    monkeypatch.setenv("ERAHERM_RECALL_MIN_SCORE", "0")
    monkeypatch.setenv("ERAHERM_EXTRACT_ON_REMEMBER", "false")
    monkeypatch.setenv("ERAHERM_JSON_LOGS", "false")
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
        t = HermesMemoryTools(client, user_id="hermes:boss", auto_open_session=True)
        yield t
        t.end_session()
    get_settings.cache_clear()


def test_openai_schemas_bound_no_user_id(tools: HermesMemoryTools) -> None:
    specs = tools.openai_tools()
    names = {s["function"]["name"] for s in specs}
    assert names == set(tools.tool_names())
    for spec in specs:
        props = spec["function"]["parameters"]["properties"]
        assert "user_id" not in props  # bound at construction


def test_dispatch_remember_recall_correct(tools: HermesMemoryTools) -> None:
    remembered = json.loads(
        tools.dispatch(
            "memory_remember",
            {"content": "用户喜欢喝冰美式", "pinned": True, "importance": 0.95},
        )
    )
    assert remembered["ok"] is True
    assert remembered["id"]

    recalled = json.loads(tools.dispatch("memory_recall", {"query": "冰美式"}))
    assert recalled["ok"] is True
    assert recalled["count"] >= 1
    assert any("冰美式" in i["content"] for i in recalled["items"])

    corrected = json.loads(
        tools.dispatch(
            "memory_correct",
            {"correction": "用户喜欢喝冰美式不是热美式", "wrong_answer": "热美式"},
        )
    )
    assert corrected["ok"] is True
    assert "feedback" in corrected


def test_dispatch_unknown_and_json_args(tools: HermesMemoryTools) -> None:
    bad = json.loads(tools.dispatch("memory_nope", {}))
    assert bad["ok"] is False
    ok = json.loads(
        tools.dispatch("memory_remember", '{"content": "项目用 FastAPI", "pinned": false}')
    )
    assert ok["ok"] is True
