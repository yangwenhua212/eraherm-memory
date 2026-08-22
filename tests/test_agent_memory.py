# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""AgentMemory five-capability facade (docs/HERMES_INTEGRATION.md §0)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from eraherm_memory import AgentMemory, MemoryClient


@pytest.fixture()
def sdk_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "agent.db"
    monkeypatch.setenv("ERAHERM_DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("ERAHERM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ERAHERM_ADMIN_TOKEN", "test-admin")
    monkeypatch.setenv("ERAHERM_EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("ERAHERM_EMBEDDING_DIM", "64")
    monkeypatch.setenv("ERAHERM_RECALL_MIN_SCORE", "0")
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


def test_remember_then_recall(sdk_client: MemoryClient):
    memory = AgentMemory(sdk_client, user_id="u_agent")
    mem = memory.remember("数据库使用 PostgreSQL", pinned=True)
    assert mem["pinned"] is True

    recall = memory.recall("我们用什么数据库")
    assert "items" in recall
    assert any("PostgreSQL" in i["content"] for i in recall["items"])
    assert memory._last_memory_ids


def test_learn_extracts_fact_and_skips_chitchat(sdk_client: MemoryClient):
    memory = AgentMemory(sdk_client, user_id="u_agent")
    mem = memory.learn("用户说：项目用 Python，数据库用 PostgreSQL")
    assert mem is not None
    assert "Python" in mem["content"]

    none = memory.learn("哈哈好的")
    assert none is None


def test_evolve_corrects(sdk_client: MemoryClient):
    memory = AgentMemory(sdk_client, user_id="u_agent")
    memory.learn("用户喜欢喝冰美式")
    fb = memory.evolve("用户喜欢喝热美式，不是冰美式", wrong_answer="冰美式")
    assert fb is not None
    assert fb.get("status") in ("queued", "completed") or "reflection" in fb


def test_reflect_requires_admin_token(sdk_client: MemoryClient):
    memory = AgentMemory(sdk_client, user_id="u_agent")
    memory.remember("临时事实 A")
    memory.remember("临时事实 B")
    out = memory.reflect(admin_token="test-admin")
    assert "reports" in out


def test_recall_text_human_readable(sdk_client: MemoryClient):
    memory = AgentMemory(sdk_client, user_id="u_agent")
    memory.remember("用户叫杨文华", pinned=True, memory_type="identity")
    text = memory.recall_text("用户名")
    assert "杨文华" in text
