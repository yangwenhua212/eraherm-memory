# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""命中增稳（间隔重复的轻量版）+ base 归一化 —— ADR 0011。

三件事必须锁死：
1. `stability_boost` 单调、有界，命中 0 次 = 1.0（等价旧行为）；
2. `decay_lambda_for` 在 boost 关闭时**返回值与旧版完全一致**（回滚保证）；
3. 排序里 base 只做「相关性相同时的破平」——永远压不过 relevance。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.adapters.memory_session_cache import InMemorySessionCache
from app.adapters.networkx_graph_store import NetworkXSqliteGraphStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.adapters.sqlite_vector_store import SqliteVectorStore
from app.config import Settings
from app.graph.extractor import RuleGraphExtractor
from app.graph.service import GraphService
from app.memory.service import MemoryService, decay_lambda_for, stability_boost
from app.ports.clock import Clock

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
BASE_LAMBDA = 0.05


class ShiftableClock(Clock):
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


def _build(tmp_path: Path, name: str, **overrides) -> tuple[MemoryService, ShiftableClock]:
    db = tmp_path / f"{name}.db"
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{db.as_posix()}",
        extract_on_remember=False,
        embedding_backend="hashing",
        embedding_dim=128,
        recall_vector_weight=0.7,
        json_logs=False,
        **overrides,
    )
    repo = SqliteMemoryRepository(settings.database_url)
    clock = ShiftableClock(NOW)
    svc = MemoryService(
        repo=repo,
        cache=InMemorySessionCache(),
        settings=settings,
        clock=clock,
        embedding=HashingEmbeddingClient(dimensions=128),
        vectors=SqliteVectorStore(settings.database_url, engine=repo.engine),
        graph_service=GraphService(
            store=NetworkXSqliteGraphStore(repo.engine),
            extractor=RuleGraphExtractor(),
            settings=settings,
            memory_repo=repo,
        ),
    )
    return svc, clock


# --- 单元：stability_boost -------------------------------------------------


def test_boost_is_one_without_hits() -> None:
    assert stability_boost(0, alpha=0.35, cap=3.0) == 1.0
    assert stability_boost(None, alpha=0.35, cap=3.0) == 1.0  # type: ignore[arg-type]
    assert stability_boost(-5, alpha=0.35, cap=3.0) == 1.0


def test_boost_monotonic_and_capped() -> None:
    values = [stability_boost(n, alpha=0.35, cap=3.0) for n in range(0, 200)]
    assert values == sorted(values), "命中次数增加，boost 不得下降"
    assert all(v <= 3.0 for v in values), "boost 必须有上界"
    assert values[1] > 1.0, "命中过就该变慢"
    assert stability_boost(10**6, alpha=0.35, cap=3.0) == 3.0


def test_boost_disabled_or_zero_alpha_is_noop() -> None:
    assert stability_boost(10**6, alpha=0.0, cap=3.0) == 1.0


# --- 单元：decay_lambda_for ------------------------------------------------


def test_decay_lambda_unchanged_when_boost_off() -> None:
    """回滚保证：boost 关掉时返回值必须与旧实现逐位一致。"""
    for pinned, row_lambda, no_decay in [
        (True, None, True),
        (False, None, True),
        (False, 0.2, True),
        (True, 0.2, False),
    ]:
        expected = 0.0 if (pinned and no_decay) else (BASE_LAMBDA if row_lambda is None else row_lambda)
        assert (
            decay_lambda_for(
                pinned=pinned,
                row_lambda=row_lambda,
                default_lambda=BASE_LAMBDA,
                pinned_no_decay=no_decay,
                access_count=999,
                boost_enabled=False,
            )
            == expected
        )


def test_decay_lambda_slows_down_with_hits() -> None:
    def lam(n: int) -> float:
        return decay_lambda_for(
            pinned=False,
            row_lambda=None,
            default_lambda=BASE_LAMBDA,
            pinned_no_decay=True,
            access_count=n,
            boost_enabled=True,
            boost_alpha=0.35,
            boost_cap=3.0,
        )

    assert lam(0) == BASE_LAMBDA
    assert lam(1) < lam(0)
    assert lam(10) < lam(1)
    assert lam(10) == pytest.approx(BASE_LAMBDA / stability_boost(10, alpha=0.35, cap=3.0))
    # 半衰期单调变长
    assert math.log(2) / lam(10) > math.log(2) / lam(0)


def test_pinned_still_never_decays() -> None:
    assert (
        decay_lambda_for(
            pinned=True,
            row_lambda=None,
            default_lambda=BASE_LAMBDA,
            pinned_no_decay=True,
            access_count=10**6,
            boost_enabled=True,
        )
        == 0.0
    )


def test_half_life_guard_bounds_runaway_stability() -> None:
    """极端命中次数 + 极宽 cap：护栏必须把半衰期压回 max_half_life_days。"""
    lam = decay_lambda_for(
        pinned=False,
        row_lambda=None,
        default_lambda=BASE_LAMBDA,
        pinned_no_decay=True,
        access_count=10**6,
        boost_enabled=True,
        boost_alpha=1.0,
        boost_cap=1000.0,
        max_half_life_days=2.0,
    )
    assert math.log(2) / lam <= 2.0 + 1e-9

    # 默认参数下的真实上界：cap=3.0 → 半衰期 ≤ 41.6 天（远小于 365 天护栏）
    lam_default = decay_lambda_for(
        pinned=False,
        row_lambda=None,
        default_lambda=BASE_LAMBDA,
        pinned_no_decay=True,
        access_count=10**9,
        boost_enabled=True,
    )
    assert math.log(2) / lam_default < 42.0


# --- 集成：常用记忆排前 ------------------------------------------------------


def test_frequently_recalled_memory_outranks_its_twin(tmp_path: Path) -> None:
    """两条内容完全相同的记忆（relevance 相同、年龄相同），被召回多的排前面。"""
    svc, clock = _build(tmp_path, "hit_boost_rank")
    old = NOW - timedelta(days=300)
    clock.current = old
    cold = svc.remember(
        content="项目后端使用 FastAPI", user_id="u_hb", memory_type="fact", importance=0.9
    )
    hot = svc.remember(
        content="项目后端使用 FastAPI", user_id="u_hb", memory_type="fact", importance=0.9
    )
    clock.current = NOW

    # 只有 hot 被反复召回
    row = svc.repo.get_memory(hot.id)
    assert row is not None
    row.access_count = 100
    svc.repo.save_memory(row)

    hits = svc.recall(user_id="u_hb", query="项目后端使用 FastAPI", top_k=5)
    assert len(hits) >= 2
    assert hits[0].id == hot.id, "命中增稳后，常用的那条应排前"
    assert hits[0].hit_boost > 1.5
    assert hits[0].base > hits[1].base
    # 300 天前的记忆依然召回得到（门禁与年龄解耦，ADR 0010）
    assert all("FastAPI" in h.content for h in hits)


def test_boost_switch_restores_baseline_behaviour(tmp_path: Path) -> None:
    svc, clock = _build(tmp_path, "hit_boost_off", recall_hit_boost_enabled=False)
    old = NOW - timedelta(days=300)
    clock.current = old
    a = svc.remember(
        content="项目后端使用 FastAPI", user_id="u_hb2", memory_type="fact", importance=0.9
    )
    clock.current = NOW
    row = svc.repo.get_memory(a.id)
    assert row is not None
    row.access_count = 100
    svc.repo.save_memory(row)

    hits = svc.recall(user_id="u_hb2", query="项目后端使用 FastAPI", top_k=5)
    assert hits
    assert hits[0].hit_boost == 1.0, "关掉开关后不得有增稳"
    assert hits[0].decay_lambda_eff == BASE_LAMBDA
    expected = 0.9 * 1.0 * math.exp(-BASE_LAMBDA * 300)
    assert abs(hits[0].base - expected) / expected < 1e-6


def test_relevance_still_dominates_base(tmp_path: Path) -> None:
    """base 再高也压不过 relevance：无关但「重要又常用」的记忆不得挤掉更相关的。"""
    svc, clock = _build(tmp_path, "base_no_outvote")
    clock.current = NOW - timedelta(days=300)
    relevant = svc.remember(
        content="项目后端使用 FastAPI", user_id="u_norm", memory_type="fact", importance=0.1
    )
    noisy = svc.remember(
        content="项目后端使用 FastAPI 与 PostgreSQL 以及 Redis 缓存与 Celery 队列",
        user_id="u_norm",
        memory_type="fact",
        importance=1.0,
    )
    row = svc.repo.get_memory(noisy.id)
    assert row is not None
    row.access_count = 10**5
    svc.repo.save_memory(row)
    clock.current = NOW

    hits = svc.recall(user_id="u_norm", query="项目后端使用 FastAPI", top_k=5)
    assert hits
    # 相关性最高的那条（更短、更聚焦）必须排在前面的候选里
    assert hits[0].relevance == max(h.relevance for h in hits)
    assert relevant.id in [h.id for h in hits]
