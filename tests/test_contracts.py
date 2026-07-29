# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.fake_memory_repo import FakeMemoryRepository
from app.adapters.fake_vector_store import FakeVectorStore
from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.adapters.sqlite_vector_store import SqliteVectorStore
from app.models import MemoryRow, utc_now_iso
from app.ports.memory_repo import MemoryRepository
from app.ports.vector_store import VectorStore


def _repo_cases(repo: MemoryRepository) -> None:
    now = utc_now_iso()
    pinned = MemoryRow(
        id="mem_pin",
        user_id="u_c",
        content="用户名为 cc",
        memory_type="identity",
        importance=1.0,
        weight=1.0,
        pinned=True,
        created_at=now,
        updated_at=now,
    )
    normal = MemoryRow(
        id="mem_norm",
        user_id="u_c",
        content="临时闲聊",
        memory_type="episode",
        importance=0.2,
        weight=1.0,
        pinned=False,
        created_at=now,
        updated_at=now,
    )
    repo.create_memory(pinned)
    repo.create_memory(normal)

    active = repo.list_active_by_user("u_c")
    assert {m.id for m in active} == {"mem_pin", "mem_norm"}

    deleted = repo.soft_delete_memories(["mem_pin", "mem_norm"], deleted_at=now)
    assert deleted == 1  # pinned skipped

    still_pin = repo.get_memory("mem_pin")
    gone = repo.get_memory("mem_norm")
    assert still_pin is not None and still_pin.deleted_at is None
    assert gone is not None and gone.deleted_at is not None

    by_ids = repo.get_memories_by_ids(["mem_pin", "missing"])
    assert len(by_ids) == 1
    assert by_ids[0].id == "mem_pin"


def _vector_cases(store: VectorStore, embed: HashingEmbeddingClient) -> None:
    v1 = embed.embed(["FastAPI web framework"])[0]
    v2 = embed.embed(["random cooking recipe noodles"])[0]
    store.upsert(memory_id="m1", user_id="u_v", vector=v1, model=embed.model_name)
    store.upsert(memory_id="m2", user_id="u_v", vector=v2, model=embed.model_name)
    q = embed.embed(["FastAPI framework"])[0]
    hits = store.search(query=q, user_id="u_v", top_k=2)
    assert hits[0].memory_id == "m1"
    assert store.delete(["m2"]) == 1
    hits2 = store.search(query=q, user_id="u_v", top_k=2)
    assert all(h.memory_id != "m2" for h in hits2)


def test_memory_repo_contract_fake():
    _repo_cases(FakeMemoryRepository())


def test_memory_repo_contract_sqlite(tmp_path: Path):
    db = tmp_path / "c.db"
    _repo_cases(SqliteMemoryRepository(f"sqlite:///{db.as_posix()}"))


def test_vector_store_contract_fake():
    embed = HashingEmbeddingClient(dimensions=64)
    _vector_cases(FakeVectorStore(), embed)


def test_vector_store_contract_sqlite(tmp_path: Path):
    db = tmp_path / "v.db"
    embed = HashingEmbeddingClient(dimensions=64)
    _vector_cases(SqliteVectorStore(f"sqlite:///{db.as_posix()}"), embed)
