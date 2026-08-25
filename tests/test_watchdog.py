# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""主动感知看门狗测试：倒计时 / 被遗忘宝石 / 健康信号 / admin 鉴权。"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.adapters.memory_session_cache import InMemorySessionCache
from app.adapters.networkx_graph_store import NetworkXSqliteGraphStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.adapters.sqlite_vector_store import SqliteVectorStore
from app.config import Settings
from app.graph.extractor import RuleGraphExtractor
from app.graph.service import GraphService
from app.main import create_app
from app.memory.service import MemoryService
from app.ports.clock import SystemClock
from app.watchdog.service import WatchdogService

@pytest.fixture()
def wd(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/watchdog.db",
        data_dir=tmp_path,
        embedding_backend="hashing",
        embedding_dim=64,
    )
    repo = SqliteMemoryRepository(settings.database_url)
    vectors = SqliteVectorStore(settings.database_url, engine=repo.engine)
    memory = MemoryService(
        repo=repo,
        cache=InMemorySessionCache(),
        settings=settings,
        clock=SystemClock(),
        embedding=HashingEmbeddingClient(dimensions=64),
        vectors=vectors,
        graph_service=GraphService(
            store=NetworkXSqliteGraphStore(repo.engine),
            extractor=RuleGraphExtractor(),
            settings=settings,
            memory_repo=repo,
        ),
    )
    wd_svc = WatchdogService(repo=repo, settings=settings)
    return memory, wd_svc


def test_countdown_detects_upcoming_event(wd):
    memory, svc = wd
    # 10 天后的考研（D-7 命中窗口）
    memory.remember(
        content="考研初试 2026-12-19 考试，22408 方向",
        user_id="u_wd",
        importance=0.9,
        extract_graph=False,
    )
    items = svc.run(user_id="u_wd", today=date(2026, 12, 12))
    countdowns = [i for i in items if i.kind == "countdown"]
    assert countdowns, "应检测到倒计时事件"
    assert "2026-12-19" in countdowns[0].detail
    assert countdowns[0].severity == "normal"  # D-7 不是 urgent


def test_countdown_ignores_past_and_non_event_dates(wd):
    memory, svc = wd
    memory.remember(
        content="纠正（2026-08-03）：老大喜欢西红柿炒鸡蛋饭",
        user_id="u_wd",
        importance=0.8,
        extract_graph=False,
    )
    # 过去日期 + 无事件关键词（纠正类）都不该触发
    items = svc.run(user_id="u_wd", today=date(2026, 8, 25))
    assert not [i for i in items if i.kind == "countdown"]


def test_forgotten_gems_flags_unused_high_importance(wd):
    memory, svc = wd
    memory.remember(
        content="老大毕设=水库水文监测可视化系统（重要长期事实）",
        user_id="u_wd",
        importance=1.0,
        extract_graph=False,
    )
    items = svc.run(user_id="u_wd", today=date(2026, 8, 25))
    gems = [i for i in items if i.kind == "forgotten_gems"]
    assert gems, "高 importance + access_count=0 应被标记"
    assert "水库" in gems[0].detail


def test_sensitive_memory_never_pushed(wd):
    """秘密/红线类记忆绝不主动推送（推送=泄露）。"""
    memory, svc = wd
    memory.remember(
        content="秘密：我在准备考研二战（不要告诉任何人）",
        user_id="u_wd",
        importance=1.0,
        extract_graph=False,
    )
    items = svc.run(user_id="u_wd", today=date(2026, 8, 25))
    # 敏感记忆即使 importance 高 + 未访问，也不该出现在 forgotten_gems
    assert not [i for i in items if i.kind == "forgotten_gems"]
    # 敏感记忆即使带考试关键词 + 未来日期，也不该出现在 countdown
    memory.remember(
        content="秘密：考研初试 2026-12-19 考试",
        user_id="u_wd",
        importance=1.0,
        extract_graph=False,
    )
    items = svc.run(user_id="u_wd", today=date(2026, 12, 12))
    assert not [i for i in items if i.kind == "countdown"]


def test_watchdog_admin_endpoint_requires_token(wd, monkeypatch):
    memory, _ = wd
    memory.remember(content="测试记忆", user_id="u_api_wd", importance=0.5, extract_graph=False)
    settings = Settings(
        database_url=memory.repo.engine.url.render_as_string(hide_password=False),
        data_dir=memory.repo.engine.url.database.rsplit("/", 1)[0] if memory.repo.engine.url.database else "/tmp",
        embedding_backend="hashing",
        embedding_dim=64,
        admin_token="wd-test-token",
    )
    monkeypatch.setenv("ERAHERM_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("ERAHERM_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("ERAHERM_EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("ERAHERM_ADMIN_TOKEN", "wd-test-token")
    from app.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        # 无 token → 401
        r = client.post("/v1/admin/watchdog", json={"user_id": "u_api_wd"})
        assert r.status_code == 401
        # 带 token → 200
        r = client.post(
            "/v1/admin/watchdog",
            json={"user_id": "u_api_wd"},
            headers={"X-Admin-Token": "wd-test-token"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["users"] == ["u_api_wd"]
        assert isinstance(body["items"], list)
