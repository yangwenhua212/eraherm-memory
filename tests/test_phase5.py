# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.filesystem_archive import FilesystemArchiveStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.archive.service import L3ArchiveService
from app.config import Settings, get_settings
from app.main import create_app
from app.models import MemoryRow, utc_now_iso


def test_l3_dump_writes_file_and_metadata(tmp_path: Path):
    db = tmp_path / "l3.db"
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{db.as_posix()}",
    )
    settings.ensure_dirs()
    repo = SqliteMemoryRepository(settings.database_url)
    now = utc_now_iso()
    repo.create_memory(
        MemoryRow(
            id="mem_l3",
            user_id="u_l3",
            content="EraHerm uses SQLite",
            importance=0.9,
            created_at=now,
            updated_at=now,
        )
    )
    svc = L3ArchiveService(
        engine=repo.engine,
        archive_store=FilesystemArchiveStore(tmp_path / "l3"),
    )
    result = svc.dump(user_id="u_l3")
    assert result.memory_count >= 1
    assert Path(result.uri).exists()
    assert len(result.checksum) == 64
    archives = svc.list_archives()
    assert any(a.id == result.archive_id for a in archives)


def test_admin_l3_and_metrics_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "api5.db"
    monkeypatch.setenv("ERAHERM_DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("ERAHERM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ERAHERM_ADMIN_TOKEN", "test-admin")
    monkeypatch.setenv("ERAHERM_EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("ERAHERM_RECALL_MIN_SCORE", "0")
    monkeypatch.setenv("ERAHERM_JSON_LOGS", "false")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        mem = client.post(
            "/v1/memories",
            json={"user_id": "u5", "content": "fact for dump", "importance": 0.9, "extract_graph": False},
        )
        assert mem.status_code == 201

        denied = client.post("/v1/admin/l3/dump", json={})
        assert denied.status_code == 401

        dump = client.post(
            "/v1/admin/l3/dump",
            json={"user_id": "u5"},
            headers={"X-Admin-Token": "test-admin"},
        )
        assert dump.status_code == 200
        body = dump.json()
        assert body["memory_count"] >= 1
        assert Path(body["uri"]).exists()

        listed = client.get(
            "/v1/admin/l3/archives",
            headers={"X-Admin-Token": "test-admin"},
        )
        assert listed.status_code == 200
        assert len(listed.json()["items"]) >= 1

        metrics = client.get("/v1/metrics")
        assert metrics.status_code == 200
        counters = metrics.json()["counters"]
        assert counters.get("remember_total", 0) >= 1
        assert counters.get("l3_dump_total", 0) >= 1
        assert counters.get("http_requests_total", 0) >= 1

        demo = client.get("/demo/")
        assert demo.status_code == 200
        assert "反馈" in demo.text
    get_settings.cache_clear()


def test_alembic_upgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from alembic import command
    from alembic.config import Config

    db = tmp_path / "mig.db"
    url = f"sqlite:///{db.as_posix()}"
    monkeypatch.setenv("ERAHERM_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    assert db.exists()
