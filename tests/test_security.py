# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""安全原语的单测。

这些测试**不需要 sqlmodel / 数据库**（这也正是把这些判断抽成纯函数的收益之一）：
以前「未认证就暴露全库」这件事没有任何测试能覆盖，因为它埋在路由里。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.auth import require_api_token
from app.security import (
    exposure_problem,
    extract_token,
    is_loopback_host,
    resolve_within,
    safe_filename,
    token_is_configured,
    tokens_equal,
)


# --- token 判定 ------------------------------------------------------------


def test_placeholder_and_empty_tokens_are_not_configured() -> None:
    for placeholder in [None, "", "   ", "dev-admin-token", "dev-api-token", "changeme"]:
        assert token_is_configured(placeholder) is False, placeholder


def test_real_token_is_configured() -> None:
    assert token_is_configured("s3cret-token") is True
    # 注意：'test' 是占位符，但 'test-admin' 不是 —— 现有测试大量使用 test-admin
    assert token_is_configured("test") is False
    assert token_is_configured("test-admin") is True


def test_tokens_equal_is_fail_closed() -> None:
    assert tokens_equal("abc", "abc") is True
    assert tokens_equal("abc", "abd") is False
    assert tokens_equal(None, "abc") is False
    assert tokens_equal("", "abc") is False
    # 期望值是占位符/空 → 永不通过（没有可猜的默认口令）
    assert tokens_equal("dev-admin-token", "dev-admin-token") is False
    assert tokens_equal("anything", None) is False
    assert tokens_equal("anything", "") is False


def test_extract_token_headers() -> None:
    assert extract_token(x_api_token="t1") == "t1"
    assert extract_token(authorization="Bearer t2") == "t2"
    assert extract_token(authorization="bearer t2") == "t2"
    # X-API-Token 优先
    assert extract_token(x_api_token="t1", authorization="Bearer t2") == "t1"
    # 非 Bearer scheme 一律忽略
    assert extract_token(authorization="Basic dXNlcjpwYXNz") is None
    assert extract_token(authorization="") is None
    assert extract_token() is None


# --- 暴露面守卫 ------------------------------------------------------------


def test_loopback_detection() -> None:
    for host in ["127.0.0.1", "::1", "localhost", " 127.0.0.1 ", "LOCALHOST"]:
        assert is_loopback_host(host) is True
    for host in ["0.0.0.0", "::", "192.168.1.10", "", None, "example.com"]:
        assert is_loopback_host(host) is False


def test_public_bind_without_token_is_refused() -> None:
    problem = exposure_problem(host="0.0.0.0", api_token=None, admin_token=None)
    assert problem is not None
    assert "ERAHERM_API_TOKEN" in problem
    # 占位值不算配置
    assert exposure_problem(host="0.0.0.0", api_token="dev-api-token") is not None


def test_public_bind_with_token_is_allowed() -> None:
    assert exposure_problem(host="0.0.0.0", api_token="s3cret") is None


def test_loopback_bind_needs_no_token() -> None:
    assert exposure_problem(host="127.0.0.1", api_token=None) is None
    assert exposure_problem(host="localhost", api_token=None) is None


def test_explicit_override_allows_public_without_token() -> None:
    assert (
        exposure_problem(host="0.0.0.0", api_token=None, allow_insecure_public=True) is None
    )


# --- 文件名 / 路径收敛 -----------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "../../../../evil",
        "..\\..\\evil",
        "..",
        ".",
        "...",
        "/etc/passwd",
        "C:\\Windows\\Temp\\evil",
        "\\\\server\\share\\evil",
        "a/b/c",
        "line\nbreak",
    ],
)
def test_safe_filename_neutralizes_traversal(raw: str) -> None:
    safe = safe_filename(raw)
    assert "/" not in safe
    assert "\\" not in safe
    assert safe not in {".", "..", ""}
    assert "\n" not in safe


def test_safe_filename_keeps_reasonable_ids() -> None:
    # 常见的 user_id 形式必须原样保住，否则归档文件名会变形
    assert safe_filename("hermes:user") == "hermes:user"
    assert safe_filename("cursor:user") == "cursor:user"
    assert safe_filename("u-123_abc.v2") == "u-123_abc.v2"


def test_safe_filename_fallback_for_empty() -> None:
    assert safe_filename(None) == "unnamed"
    assert safe_filename("...") == "unnamed"
    assert safe_filename("", fallback="all") == "all"


def test_resolve_within_accepts_plain_name() -> None:
    root = Path(tempfile.gettempdir()) / "eraherm-security-test" / "l3"
    target = resolve_within(root, "dump_20260101T000000Z_u1.json")
    assert target.parent == root.resolve()
    assert target.name == "dump_20260101T000000Z_u1.json"


def test_resolve_within_rejects_escape_and_absolute() -> None:
    # resolve_within 只做路径运算，root 不必存在（因此这里不依赖 tmp_path）
    root = Path(tempfile.gettempdir()) / "eraherm-security-test" / "l3"
    for bad in ["../evil.json", "a/../../evil.json", "..\\evil.json"]:
        with pytest.raises(ValueError):
            resolve_within(root, bad)
    with pytest.raises(ValueError):
        resolve_within(root, "C:\\Windows\\Temp\\evil.json")
    with pytest.raises(ValueError):
        resolve_within(root, "/tmp/evil.json")
    with pytest.raises(ValueError):
        resolve_within(root, "")


# --- 认证依赖（真实 FastAPI TestClient） ----------------------------------


class _Cfg:
    def __init__(self, api_token: str | None) -> None:
        self.api_token = api_token
        self.admin_token = ""


def _app_with(api_token: str | None) -> TestClient:
    app = FastAPI()
    app.state.settings = _Cfg(api_token)

    @app.get("/v1/thing", dependencies=[Depends(require_api_token)])
    def thing() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/v1/health", dependencies=[Depends(require_api_token)])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_auth_disabled_when_token_not_configured() -> None:
    with _app_with(None) as client:
        assert client.get("/v1/thing").status_code == 200
    with _app_with("dev-api-token") as client:
        # 占位值 = 未配置，不允许拿它当口令
        assert client.get("/v1/thing").status_code == 200


def test_auth_enforced_when_token_configured() -> None:
    with _app_with("s3cret") as client:
        assert client.get("/v1/thing").status_code == 401
        assert client.get("/v1/thing", headers={"X-API-Token": "s3cret"}).status_code == 200
        assert (
            client.get("/v1/thing", headers={"X-API-Token": "wrong"}).status_code == 401
        )
        assert (
            client.get(
                "/v1/thing", headers={"Authorization": "Bearer s3cret"}
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/v1/thing", headers={"Authorization": "Basic czNjcmV0"}
            ).status_code
            == 401
        )


def test_health_is_always_public() -> None:
    with _app_with("s3cret") as client:
        assert client.get("/v1/health").status_code == 200
