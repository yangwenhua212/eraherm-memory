# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.fake_memory_repo import FakeMemoryRepository
from app.adapters.fake_vector_store import FakeVectorStore
from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.config import Settings, get_settings
from app.main import create_app
from app.migrate.service import ReembedService
from app.models import MemoryRow, utc_now_iso


def _settings(tmp_path: Path, *, dim: int = 64) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{(tmp_path / 're.db').as_posix()}",
        embedding_backend="hashing",
        embedding_dim=dim,
        json_logs=False,
    )


def test_reembed_assigns_orphans_and_overwrites_vectors(tmp_path: Path) -> None:
    settings = _settings(tmp_path, dim=64)
    repo = FakeMemoryRepository()
    vectors = FakeVectorStore()
    emb = HashingEmbeddingClient(dimensions=64, model_name="hashing-v1")

    now = utc_now_iso()
    orphan = MemoryRow(
        id="mem_orphan",
        user_id=None,
        content="旧 hashing 记忆：老大喜欢螺蛳粉",
        created_at=now,
        updated_at=now,
    )
    ok = MemoryRow(
        id="mem_ok",
        user_id="u_boss",
        content="数据库是 PostgreSQL",
        created_at=now,
        updated_at=now,
    )
    repo.create_memory(orphan)
    repo.create_memory(ok)
    # stale 32-dim vectors under wrong model / null user
    vectors.upsert(memory_id="mem_orphan", user_id=None, vector=[0.1] * 32, model="old-hash")
    vectors.upsert(memory_id="mem_ok", user_id="u_boss", vector=[0.2] * 32, model="old-hash")
    vectors.upsert(memory_id="mem_ghost", user_id="u_boss", vector=[0.3] * 32, model="old-hash")

    report = ReembedService(
        repo=repo, embedding=emb, vectors=vectors, settings=settings
    ).run(orphan_policy="assign", orphan_user_id="u_boss", force=True)

    assert report.errors == []
    assert report.scanned == 2
    assert report.reembedded == 2
    assert report.orphans_assigned == 1
    assert report.dangling_vectors_removed == 1
    assert repo.get_memory("mem_orphan").user_id == "u_boss"

    meta = vectors.get_meta("mem_ok")
    assert meta is not None
    assert meta["dim"] == 64
    assert meta["model"] == "hashing-v1"
    assert meta["user_id"] == "u_boss"
    assert "mem_ghost" not in vectors.list_memory_ids()

    # second run without force should skip current rows
    report2 = ReembedService(
        repo=repo, embedding=emb, vectors=vectors, settings=settings
    ).run(orphan_policy="assign", orphan_user_id="u_boss", force=False)
    assert report2.reembedded == 0
    assert report2.skipped_current == 2


def test_reembed_skip_orphans(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repo = FakeMemoryRepository()
    vectors = FakeVectorStore()
    emb = HashingEmbeddingClient(dimensions=64)
    now = utc_now_iso()
    repo.create_memory(
        MemoryRow(id="m1", user_id=None, content="孤岛", created_at=now, updated_at=now)
    )
    report = ReembedService(
        repo=repo, embedding=emb, vectors=vectors, settings=settings
    ).run(orphan_policy="skip")
    assert report.orphans_skipped == 1
    assert report.reembedded == 0
    assert repo.get_memory("m1").user_id is None


def test_reembed_fail_on_orphans(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repo = FakeMemoryRepository()
    emb = HashingEmbeddingClient(dimensions=64)
    now = utc_now_iso()
    repo.create_memory(
        MemoryRow(id="m1", user_id=None, content="孤岛", created_at=now, updated_at=now)
    )
    report = ReembedService(
        repo=repo, embedding=emb, vectors=FakeVectorStore(), settings=settings
    ).run(orphan_policy="fail")
    assert report.errors
    assert report.reembedded == 0


def test_admin_reembed_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "api_re.db"
    monkeypatch.setenv("ERAHERM_DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("ERAHERM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ERAHERM_EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("ERAHERM_EMBEDDING_DIM", "64")
    monkeypatch.setenv("ERAHERM_ADMIN_TOKEN", "test-admin")
    monkeypatch.setenv("ERAHERM_EXTRACT_ON_REMEMBER", "false")
    monkeypatch.setenv("ERAHERM_RECALL_MIN_SCORE", "0")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        # remember without user_id is not allowed via API; insert orphan via remember with user then wipe — use service path
        client.post(
            "/v1/memories",
            json={"user_id": "u_api", "content": "螺蛳粉加炸蛋", "importance": 1.0},
        )
        res = client.post(
            "/v1/admin/reembed",
            headers={"X-Admin-Token": "test-admin"},
            json={"force": True, "orphan_policy": "skip"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["reembedded"] >= 1
        assert body["target_dim"] == 64

        denied = client.post("/v1/admin/reembed", json={"force": True})
        assert denied.status_code == 401
    get_settings.cache_clear()
