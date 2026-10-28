# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""进程内限流原语（令牌桶 + 纯 ASGI 中间件）。

设计约束（都是一次真实事故的产物）：

* **只依赖标准库**：本模块不 import ``app.config`` / ``app.models`` / ``app.api.*``，
  配置全部由构造参数传入。这样它既能被 API 进程用，也能被脚本、测试、
  甚至嵌入到别的 ASGI 应用里用，而不会拖进 sqlmodel / DB 初始化。
* **不保存明文密钥**：限流 key 是 ``X-API-Token`` 的 sha256，而不是令牌本身。
  否则一次 ``/v1/health`` 探测失败就会把别人的 key 写进进程内存与任何 dump 里。
* **内存有界**：桶数量上限 ``max_keys``（默认 10000），超过时按 LRU 淘汰；
  同时懒清理空闲超过 ``idle_ttl``（默认 600s = 10 分钟）的桶 ——
  否则任意伪造 header 的攻击者可以把 ``dict`` 撑到 OOM（无界 key 增长 = 一键 DoS）。
* **限流失败必须 fail-open**：中间件内部任何异常都放行请求。限流是防滥用，
  不是授权；限流器崩了不能把全部合法流量一起拒掉（可用性 > 限流）。

限流本身仍然是 fail-closed：超过额度一定返回 429。

用法（app/main.py 里接线，**注意 limiter 必须是进程级单例**）::

    from app.ratelimit import RateLimitMiddleware, TokenBucketLimiter

    app.add_middleware(
        RateLimitMiddleware,
        limiter=TokenBucketLimiter(
            per_minute=settings.rate_limit_per_minute,
            burst=settings.rate_limit_burst,
        ),
        enabled=settings.rate_limit_enabled,
    )

**坑**：不要在 lambda / 工厂里 new limiter —— 那样每个请求都会拿到一个崭新满桶，
限流器就变成一个纯粹的 CPU 消耗器（永不 429）。桶是**进程内**状态：多 worker /
多副本部署时每个进程各自计数，真实上限是 ``N × per_minute``。
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = [
    "DEFAULT_EXEMPT_PATHS",
    "DEFAULT_IDLE_TTL_SECONDS",
    "DEFAULT_MAX_KEYS",
    "RateLimitMiddleware",
    "TokenBucketLimiter",
]

#: 桶数量硬上限。每个桶约 100 字节级（dataclass + dict 槽位 + OrderedDict 链），
#: 10000 个桶 ≈ 1~2MB 常驻内存；超过就 LRU 淘汰最久未用的 key。
DEFAULT_MAX_KEYS = 10_000
#: 空闲超过该秒数的桶会被直接丢弃（下次出现时按「满桶」重新开始）。
DEFAULT_IDLE_TTL_SECONDS = 600.0
#: 默认豁免路径。写成「裸路径」= 该方法无关地全部豁免；
#: 也可以写成 ``"GET /v1/health"`` 形式只豁免某个方法（见 ``_is_exempt``）。
DEFAULT_EXEMPT_PATHS: frozenset[str] = frozenset({"/v1/health"})


@dataclass
class _Bucket:
    """单个 key 的令牌桶状态。

    ``tokens`` 是浮点数：重填按时间连续进行，不做整秒对齐，
    否则「59 秒时用掉最后一个令牌」这类抖动会导致突发误杀。
    """

    tokens: float
    updated_at: float


def _refill(bucket: _Bucket, rate_per_second: float, burst: int, now: float) -> None:
    """按经过的时间把令牌补回桶里（惰性重填，不需要后台线程）。"""
    elapsed = now - bucket.updated_at
    if elapsed <= 0.0:
        return
    bucket.tokens = min(float(burst), bucket.tokens + elapsed * rate_per_second)
    bucket.updated_at = now


class TokenBucketLimiter:
    """线程安全、内存有界的进程内令牌桶限流器。

    Args:
        per_minute: 每分钟补充的令牌数（也即长期平均速率）。
        burst: 桶容量（允许的瞬时突发）。默认与 ``per_minute`` 相同。
        max_keys: 同时跟踪的 key 上限，超出按 LRU 淘汰最久未使用的桶。
        idle_ttl: 空闲超过该秒数的桶在下次操作时被清理（默认 600s）。
        clock: 时钟函数，默认 ``time.monotonic``；便于测试注入。

    Raises:
        ValueError: ``per_minute <= 0``、``burst <= 0``、``max_keys <= 0``
            或 ``idle_ttl < 0``。静默接受 ``per_minute=0`` 会得到
            「除 health 外全部 429」的诡异行为，早失败更好。
    """

    def __init__(
        self,
        *,
        per_minute: int,
        burst: int | None = None,
        max_keys: int = DEFAULT_MAX_KEYS,
        idle_ttl: float = DEFAULT_IDLE_TTL_SECONDS,
        clock: Any | None = None,
    ) -> None:
        if per_minute <= 0:
            raise ValueError("per_minute 必须为正整数")
        if burst is None:
            burst = per_minute
        if burst <= 0:
            raise ValueError("burst 必须为正整数")
        if max_keys <= 0:
            raise ValueError("max_keys 必须为正整数")
        if idle_ttl < 0:
            raise ValueError("idle_ttl 不能为负")

        self.per_minute = int(per_minute)
        self.burst = int(burst)
        self.max_keys = int(max_keys)
        self.idle_ttl = float(idle_ttl)
        self._rate_per_second = self.per_minute / 60.0
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        # OrderedDict 兼任 LRU：move_to_end = 标记最近使用，popitem(last=False) = 淘汰最旧。
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._evicted_total = 0

    # --- 内部 ---------------------------------------------------------------

    def _now(self, now: float | None) -> float:
        return self._clock() if now is None else float(now)

    def _prune_locked(self, now: float) -> None:
        """清掉空闲桶并把桶数量压回上限。调用方必须已持锁。"""
        if self.idle_ttl > 0:
            for key in [k for k, b in self._buckets.items() if now - b.updated_at > self.idle_ttl]:
                del self._buckets[key]
        while len(self._buckets) > self.max_keys:
            self._buckets.popitem(last=False)
            self._evicted_total += 1

    def _decide(self, key: str, now: float, *, consume: bool) -> tuple[bool, float]:
        """核心判定：返回 ``(是否可用/已扣减, 距下一个令牌的秒数)``。"""
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                # 新 key 从「满桶」开始：不能因为攻击者先耗尽自己的桶就顺带惩罚别人。
                bucket = _Bucket(tokens=float(self.burst), updated_at=now)
                self._buckets[key] = bucket

            # 这里**不能**先写 bucket.updated_at = now 再 _refill：那会把 elapsed 抹成 0，
            # 令牌永远补不回来（429 就成了永久封禁，而不是限流）。只由 _refill 推进时间戳。
            _refill(bucket, self._rate_per_second, self.burst, now)

            if bucket.tokens >= 1.0:
                if consume:
                    bucket.tokens -= 1.0
                self._buckets.move_to_end(key)
                self._prune_locked(now)
                return True, 0.0

            deficit = 1.0 - bucket.tokens
            wait = deficit / self._rate_per_second
            self._buckets.move_to_end(key)
            self._prune_locked(now)
            return False, wait

    # --- 公开 API -----------------------------------------------------------

    def allow(self, key: str, *, now: float | None = None) -> bool:
        """尝试消耗一个令牌；返回是否放行。

        未知 key 视为「刚创建的空闲桶」（满桶），因此首次调用总是放行。
        """
        ts = self._now(now)
        allowed, _ = self._decide(str(key), ts, consume=True)
        return allowed

    def retry_after(self, key: str, *, now: float | None = None) -> float:
        """距下一个令牌可用的秒数；可用时返回 ``0.0``。

        只读语义：不会消耗令牌。未知 key 视为满桶 → ``0.0``。
        """
        ts = self._now(now)
        _, wait = self._decide(str(key), ts, consume=False)
        return wait

    def keys(self) -> list[str]:
        """当前被跟踪的 key（一律是哈希后的短标识，绝不含明文密钥）。"""
        with self._lock:
            return list(self._buckets.keys())

    def bucket_count(self) -> int:
        """当前跟踪的桶数量，用于断言内存上限。"""
        with self._lock:
            return len(self._buckets)

    def evicted_total(self) -> int:
        """累计因超出 ``max_keys`` 被淘汰的桶数量（可观测性用）。"""
        with self._lock:
            return self._evicted_total


def _hash_key(raw: str) -> str:
    """把任意标识收敛成定长哈希；空/异常输入退化为 ``"anonymous"``。"""
    try:
        return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()
    except Exception:  # noqa: BLE001 - 绝不让 key 推导把请求打挂
        return "anonymous"


def _limit_key(scope: Scope) -> str:
    """推导限流 key（已哈希）。

    优先级：``X-API-Token`` 头（sha256）> ``scope["client"]`` 的主机 > ``"anonymous"``。
    明文令牌永不进入内存；哈希后也无法从内存反推令牌。
    """
    raw_token: str | None = None
    try:
        for name, value in scope.get("headers") or ():
            if name == b"x-api-token":
                raw_token = value.decode("latin-1").strip()
                break
    except Exception:  # noqa: BLE001
        raw_token = None

    if raw_token:
        return _hash_key(raw_token)

    client = scope.get("client")
    if client:
        try:
            host = client[0]
        except Exception:  # noqa: BLE001
            host = None
        if host:
            return _hash_key(str(host))

    return "anonymous"


def _is_exempt(method: str, path: str, exempt_paths: frozenset[str]) -> bool:
    """豁免判定：同时支持裸路径与 ``"METHOD path"`` 两种写法。

    * ``"/v1/health"`` → 该方法无关地豁免（健康检查最需要这样）
    * ``"GET /v1/health"`` → 只豁免 GET；``POST /v1/health`` 仍受限
    """
    if not exempt_paths:
        return False
    if path in exempt_paths:
        return True
    return f"{method} {path}" in exempt_paths


class RateLimitMiddleware:
    """纯 ASGI 限流中间件（不是 ``BaseHTTPMiddleware``）。

    用裸 ASGI 而不是 ``BaseHTTPMiddleware``：后者给每个请求再套一层 anyio
    task group + 流式包装，在限流这种「可能直接短路返回」的场景里纯属额外开销，
    而且它的 ``call_next`` 异常语义更容易把 429 变成 500。

    行为：
        * 只处理 ``scope["type"] == "http"``；lifespan / websocket 原样透传。
        * ``enabled`` 为假 → 完全透传（等于没装）。
        * 命中 ``exempt_paths`` → 透传（默认豁免 ``GET /v1/health``）。
        * 触发限流 → ``429`` + 项目统一错误信封 + ``Retry-After``（整数秒，≥1）。
        * 内部任何异常 → 透传（fail-open）；超限则一定拒绝（fail-closed）。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: TokenBucketLimiter | None = None,
        enabled: bool = True,
        exempt_paths: frozenset[str] = DEFAULT_EXEMPT_PATHS,
    ) -> None:
        self.app = app
        self.enabled = bool(enabled)
        self.exempt_paths = frozenset(exempt_paths or ())
        self.limiter = limiter if limiter is not None else TokenBucketLimiter(per_minute=60)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        try:
            method = str(scope.get("method") or "GET").upper()
            path = str(scope.get("path") or "")
            if _is_exempt(method, path, self.exempt_paths):
                await self.app(scope, receive, send)
                return
            key = _limit_key(scope)
            allowed = self.limiter.allow(key)
            if not allowed:
                # 二次读取等待时间；上限分支里 retry_after 必然 > 0（除非被淘汰），
                # 因此 max(1, ...) 保证 Retry-After 恒为 >= 1 的整数。
                wait = float(self.limiter.retry_after(key) or 0.0)
                await self._reject(wait, send)
                return
        except Exception:  # noqa: BLE001 - 限流器故障不能拖垮请求
            pass

        await self.app(scope, receive, send)

    async def _reject(self, wait: float, send: Send) -> None:
        """发送 429 响应（项目统一信封 + Retry-After 头）。

        不调用 ``scope["app"]`` 之类的东西，也不需要读请求体 —— 但 ``Response.__call__``
        会看 ``scope["type"]``（websocket 分支），所以这里显式构造一个最小的 http scope，
        而不是传空 dict。
        """
        retry_after = max(1, math.ceil(wait)) if wait > 0 else 1
        response = JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "rate_limited",
                    "message": "rate limit exceeded: too many requests, retry later",
                    "details": {"retry_after": round(float(wait), 3)},
                }
            },
            headers={"Retry-After": str(retry_after)},
        )
        await response(
            scope={"type": "http", "method": "GET", "path": "", "headers": []},
            receive=_noop_receive,
            send=send,
        )


async def _noop_receive() -> Message:  # pragma: no cover - 429 不读请求体
    return {"type": "http.disconnect"}
