# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""限流模块的单测（app/ratelimit.py）。

这些测试**不 import 项目应用**（也不碰 sqlmodel / DB / app.config），而是：
  * 直接单测 ``TokenBucketLimiter`` 的算法与内存上限（时间靠注入 ``now``，不真睡）；
  * 用一次性 FastAPI app + TestClient 走真实 ASGI 中间件路径，验证 429 报文与头。

注意：本沙箱**不能创建/列举目录**，所以不用 pytest 的 ``tmp_path``/``tmpdir``；
需要落盘时只用 ``ERAHERM_TEST_TMP`` 或系统临时目录下的**文件**。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.ratelimit import (
    DEFAULT_EXEMPT_PATHS,
    RateLimitMiddleware,
    TokenBucketLimiter,
)


# --- 测试替身 / 工具 --------------------------------------------------------


class FakeClock:
    """可手工推进的时钟，用来把「时间」变成确定性输入。"""

    def __init__(self, start: float = 0.0) -> None:
        self.value = float(start)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


class _BoomLimiter:
    """任何调用都抛异常的假限流器，用于验证 fail-open。"""

    def allow(self, key: str, *, now: float | None = None) -> bool:
        raise RuntimeError("boom")

    def retry_after(self, key: str, *, now: float | None = None) -> float:
        raise RuntimeError("boom")


def _make_app(
    *,
    limiter: Any = None,
    enabled: bool = True,
    exempt_paths: frozenset[str] | None = None,
) -> FastAPI:
    """一次性应用：/v1/thing 受限，/v1/health 默认豁免。"""
    app = FastAPI()
    if exempt_paths is None:
        app.add_middleware(
            RateLimitMiddleware, limiter=limiter, enabled=enabled
        )
    else:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=limiter,
            enabled=enabled,
            exempt_paths=exempt_paths,
        )

    @app.get("/v1/thing")
    def thing() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/health")
    def health_post() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _tmp_probe_file() -> Path:
    """确认本环境确实可以写文件（目录不可创建，因此不调用 mkdir）。"""
    root = os.environ.get("ERAHERM_TEST_TMP") or tempfile.gettempdir()
    return Path(root) / "eraherm_ratelimit_probe.txt"


# --- TokenBucketLimiter：算法 -------------------------------------------------


def test_init_rejects_non_positive_rate() -> None:
    with pytest.raises(ValueError):
        TokenBucketLimiter(per_minute=0)
    with pytest.raises(ValueError):
        TokenBucketLimiter(per_minute=60, burst=0)
    with pytest.raises(ValueError):
        TokenBucketLimiter(per_minute=60, max_keys=0)
    with pytest.raises(ValueError):
        TokenBucketLimiter(per_minute=60, idle_ttl=-1)


def test_burst_defaults_to_per_minute() -> None:
    assert TokenBucketLimiter(per_minute=7).burst == 7
    assert TokenBucketLimiter(per_minute=7, burst=3).burst == 3


def test_unknown_key_is_available_and_retry_after_is_zero() -> None:
    limiter = TokenBucketLimiter(per_minute=60)
    # 未知 key 视为满桶 → 立即可用，等待 0.0（只读，不扣令牌）
    assert limiter.retry_after("never-seen") == 0.0
    assert limiter.retry_after("never-seen") == 0.0
    assert limiter.allow("never-seen") is True


def test_burst_then_blocked_then_refill() -> None:
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(per_minute=60, burst=3, clock=clock)

    assert [limiter.allow("k") for _ in range(3)] == [True, True, True]
    assert limiter.allow("k") is False
    # 速率 1 token/s，桶已空 → 还有 1 秒
    assert limiter.retry_after("k") == pytest.approx(1.0)

    clock.advance(0.5)
    assert limiter.allow("k") is False  # 只回了 0.5 个令牌
    assert limiter.retry_after("k") == pytest.approx(0.5)

    clock.advance(0.5)  # 累计 1.0s → 恰好 1 个令牌
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False


def test_refill_is_capped_at_burst() -> None:
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(per_minute=60, burst=2, clock=clock)
    assert limiter.allow("k") is True
    clock.advance(3600.0)  # 睡一小时也不该攒出 60 个令牌
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False


def test_keys_are_independent() -> None:
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(per_minute=60, burst=1, clock=clock)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is True  # 不共享预算


def test_retry_after_does_not_consume_tokens() -> None:
    limiter = TokenBucketLimiter(per_minute=60, burst=1)
    for _ in range(5):
        assert limiter.retry_after("k") == 0.0
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False


def test_idle_buckets_are_pruned() -> None:
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(per_minute=60, burst=1, idle_ttl=600.0, clock=clock)
    for i in range(50):
        limiter.allow(f"idle-{i}")
    assert limiter.bucket_count() == 50

    clock.advance(601.0)  # 全部空闲超过 TTL
    limiter.allow("fresh")
    assert limiter.bucket_count() == 1
    assert limiter.keys() == ["fresh"]


def test_memory_bound_holds_with_many_distinct_keys() -> None:
    limiter = TokenBucketLimiter(per_minute=60, max_keys=64, idle_ttl=600.0)
    for i in range(5_000):
        limiter.allow(f"attacker-{i}")
        assert limiter.bucket_count() <= 64
    assert limiter.bucket_count() == 64
    assert limiter.evicted_total() > 0
    assert len(limiter.keys()) <= 64


def test_lru_eviction_keeps_recent_key() -> None:
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(per_minute=60, burst=1, max_keys=2, clock=clock)
    assert limiter.allow("hot") is True  # hot 用掉唯一令牌
    limiter.allow("a")
    # 重新触碰 hot，使其成为最近使用；随后插入 b 应淘汰 a 而不是 hot
    clock.advance(1.0)
    assert limiter.allow("hot") is True
    limiter.allow("b")
    assert limiter.bucket_count() == 2
    assert limiter.allow("hot") is False  # hot 的桶还在（令牌已耗尽）
    assert limiter.allow("a") is True  # a 被淘汰 → 满桶重新开始


def test_limiter_is_shared_across_requests_when_installed_once() -> None:
    """接线姿势回归测试：limiter 必须是进程级单例。

    若谁把 limiter 塞进 ``lambda``（每次请求新建一个满桶），限流会静默失效 ——
    这个测试就是那条静默失效的哨兵。
    """
    limiter = TokenBucketLimiter(per_minute=60, burst=1)
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.get("/v1/thing")
    def thing() -> dict[str, str]:
        return {"ok": "yes"}

    with TestClient(app) as client:
        assert client.get("/v1/thing").status_code == 200
        assert client.get("/v1/thing").status_code == 429
        assert limiter.bucket_count() == 1  # 复用同一个桶，而不是每请求新建


def test_time_injection_does_not_break_allow() -> None:
    # now=0.0 是合法时间戳，不能被 `if not now` 之类的写法吃掉
    limiter = TokenBucketLimiter(per_minute=60, burst=1)
    assert limiter.allow("k", now=0.0) is True
    assert limiter.allow("k", now=0.0) is False
    assert limiter.allow("k", now=60.0) is True


# --- RateLimitMiddleware：HTTP 行为 ------------------------------------------


def test_disabled_middleware_passes_everything() -> None:
    limiter = TokenBucketLimiter(per_minute=60, burst=1)
    with TestClient(_make_app(limiter=limiter, enabled=False)) as client:
        for _ in range(10):
            response = client.get("/v1/thing")
            assert response.status_code == 200
    # 一个令牌都没被扣掉
    assert limiter.bucket_count() == 0


def test_burst_then_429_with_envelope_and_headers() -> None:
    limiter = TokenBucketLimiter(per_minute=60, burst=2)
    with TestClient(_make_app(limiter=limiter)) as client:
        assert client.get("/v1/thing").status_code == 200
        assert client.get("/v1/thing").status_code == 200

        rejected = client.get("/v1/thing")
        assert rejected.status_code == 429
        assert rejected.headers["content-type"].startswith("application/json")
        retry_after = rejected.headers["retry-after"]
        assert int(retry_after) >= 1

        body = rejected.json()
        assert body["error"]["code"] == "rate_limited"
        assert isinstance(body["error"]["message"], str) and body["error"]["message"]
        assert set(body["error"]) == {"code", "message", "details"}
        assert body["error"]["details"]["retry_after"] > 0.0
        assert body["error"]["details"]["retry_after"] <= float(retry_after)
        # 信封形状与 app.api.schemas.ErrorResponse 一致（error → code/message/details）
        assert json.dumps(body).startswith('{"error":')


def test_exempt_path_is_never_limited() -> None:
    limiter = TokenBucketLimiter(per_minute=60, burst=1)
    app = _make_app(limiter=limiter, exempt_paths=DEFAULT_EXEMPT_PATHS)
    with TestClient(app) as client:
        for _ in range(20):
            assert client.get("/v1/health").status_code == 200
        # 换成受限路径立刻 429，说明豁免确实只作用于 health
        assert client.get("/v1/thing").status_code == 200
        assert client.get("/v1/thing").status_code == 429
    assert limiter.keys() == [_hash("testclient")]


def test_exempt_path_matching_forms() -> None:
    # 裸路径 = 方法无关；"METHOD path" = 只豁免该方法
    limiter = TokenBucketLimiter(per_minute=60, burst=1)
    with TestClient(_make_app(limiter=limiter, exempt_paths=frozenset({"/v1/health"}))) as c:
        assert c.get("/v1/health").status_code == 200
        assert c.post("/v1/health").status_code == 200  # 方法无关

    limiter2 = TokenBucketLimiter(per_minute=60, burst=1)
    with TestClient(
        _make_app(limiter=limiter2, exempt_paths=frozenset({"GET /v1/health"}))
    ) as c2:
        assert c2.get("/v1/health").status_code == 200
        assert c2.post("/v1/health").status_code == 200  # 首次 POST，还有令牌
        assert c2.post("/v1/health").status_code == 429  # 第二次就受限（未被豁免）

    empty = TokenBucketLimiter(per_minute=60, burst=1)
    with TestClient(_make_app(limiter=empty, exempt_paths=frozenset())) as c3:
        assert c3.get("/v1/health").status_code == 200
        assert c3.get("/v1/health").status_code == 429


def test_default_exempt_paths_cover_get_health() -> None:
    assert "/v1/health" in DEFAULT_EXEMPT_PATHS
    limiter = TokenBucketLimiter(per_minute=60, burst=1)
    with TestClient(_make_app(limiter=limiter)) as client:  # 不传 exempt_paths
        for _ in range(10):
            assert client.get("/v1/health").status_code == 200


def test_distinct_api_tokens_get_independent_budgets() -> None:
    token_a = "s3cret-token-aaa"
    token_b = "s3cret-token-bbb"
    limiter = TokenBucketLimiter(per_minute=60, burst=1)
    with TestClient(_make_app(limiter=limiter)) as client:
        headers_a = {"X-API-Token": token_a}
        headers_b = {"X-API-Token": token_b}

        assert client.get("/v1/thing", headers=headers_a).status_code == 200
        assert client.get("/v1/thing", headers=headers_a).status_code == 429
        # a 被限流不影响 b
        assert client.get("/v1/thing", headers=headers_b).status_code == 200
        # 无 token 的一条（按 client host 计 key）也不受影响
        assert client.get("/v1/thing").status_code == 200
        assert client.get("/v1/thing").status_code == 429

    assert limiter.bucket_count() == 3


def test_raw_token_never_appears_in_limiter_state() -> None:
    raw = "s3cret-token-never-stored"
    limiter = TokenBucketLimiter(per_minute=60, burst=1)
    with TestClient(_make_app(limiter=limiter)) as client:
        client.get("/v1/thing", headers={"X-API-Token": raw})

    keys = limiter.keys()
    assert keys == [_hash(raw)]
    assert raw not in keys
    buckets = getattr(limiter, "_buckets", None)
    if buckets is not None:  # 内部结构也逐字节检查一遍
        assert raw not in buckets
        assert not any(raw in str(k) for k in buckets)
        assert not any(raw in str(v) for v in buckets.values())
    assert limiter.bucket_count() == 1


def test_token_key_takes_precedence_over_client_host() -> None:
    limiter = TokenBucketLimiter(per_minute=60, burst=1)
    with TestClient(_make_app(limiter=limiter)) as client:
        assert client.get("/v1/thing").status_code == 200  # host key 用完
        assert client.get("/v1/thing").status_code == 429
        # 带 token 的请求走另一套 key → 仍然放行
        assert (
            client.get("/v1/thing", headers={"X-API-Token": "tok"}).status_code == 200
        )
    assert sorted(limiter.keys()) == sorted([_hash("testclient"), _hash("tok")])


def test_429_recovers_after_real_refill() -> None:
    # 唯一一处真实等待：per_minute=120 → 0.5s 一个令牌；睡 0.6s 足够
    limiter = TokenBucketLimiter(per_minute=120, burst=1)
    with TestClient(_make_app(limiter=limiter)) as client:
        assert client.get("/v1/thing").status_code == 200
        rejected = client.get("/v1/thing")
        assert rejected.status_code == 429
        assert int(rejected.headers["retry-after"]) >= 1
        time.sleep(0.6)
        assert client.get("/v1/thing").status_code == 200


def test_limiter_bug_fails_open() -> None:
    app = _make_app(limiter=_BoomLimiter())
    with TestClient(app, raise_server_exceptions=False) as client:
        for _ in range(5):
            assert client.get("/v1/thing").status_code == 200


def test_non_http_scopes_pass_through_untouched() -> None:
    import anyio

    limiter = TokenBucketLimiter(per_minute=60, burst=1)
    seen: list[str] = []

    async def fake_app(scope: dict, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    middleware = RateLimitMiddleware(fake_app, limiter=limiter)  # type: ignore[arg-type]

    async def scenario() -> None:
        for scope_type in ("lifespan", "websocket"):
            await middleware({"type": scope_type}, _unused_receive, _unused_send)

    anyio.run(scenario)
    assert seen == ["lifespan", "websocket"]
    assert limiter.bucket_count() == 0


async def _unused_receive() -> dict:  # pragma: no cover
    return {"type": "http.disconnect"}


async def _unused_send(message: dict) -> None:  # pragma: no cover
    return None


def test_client_host_is_used_when_no_token() -> None:
    limiter = TokenBucketLimiter(per_minute=60, burst=1)
    with TestClient(_make_app(limiter=limiter)) as client:
        assert client.get("/v1/thing").status_code == 200
        assert client.get("/v1/thing").status_code == 429
    assert limiter.keys() == [_hash("testclient")]


def test_retry_after_header_rounds_up_to_at_least_one() -> None:
    # per_minute=6000 → 0.01s 一个令牌，真实 wait 远小于 1 秒
    limiter = TokenBucketLimiter(per_minute=6000, burst=1)
    with TestClient(_make_app(limiter=limiter)) as client:
        assert client.get("/v1/thing").status_code == 200
        rejected = client.get("/v1/thing")
        assert rejected.status_code == 429
        assert int(rejected.headers["retry-after"]) == math.ceil(
            rejected.json()["error"]["details"]["retry_after"]
        )
        assert int(rejected.headers["retry-after"]) >= 1


def test_can_write_probe_file() -> None:
    """本沙箱允许建文件但禁止建/列目录 —— 断言这条前提，避免用 tmp_path 的坑。"""
    target = _tmp_probe_file()
    try:
        target.write_text("ok", encoding="utf-8")
        assert target.read_text(encoding="utf-8") == "ok"
    finally:
        # 必须清理：把 TEMP/ERAHERM_TEST_TMP 指向工作区时，留下的探针文件会一路
        # 沉淀到工作区根目录（本文件第一版就漏了 unlink，于是每次跑测试都多一个
        # eraherm_ratelimit_probe.txt）。test_proclock.py 的 fixture 同样是这个模式。
        target.unlink(missing_ok=True)
