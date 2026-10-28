# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""HTTP 认证依赖。

只做一件事：当 ``ERAHERM_API_TOKEN`` 被真正配置时，``/v1/*`` 除健康检查外
一律要求 ``X-API-Token: <token>``（兼容 ``Authorization: Bearer <token>``）。

未配置 token 时**不启用**认证——这是有意为之，因为此时启动守卫
（``app.security.exposure_problem``，在 ``app/main.py`` 里执行）已经保证
进程只绑定回环地址，不会把记忆库暴露到网络上。

本模块刻意只依赖 ``fastapi`` 与 ``app.security``，不碰 sqlmodel，
这样它可以被 TestClient 直接单测。
"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request, status

from app.security import extract_token, token_is_configured, tokens_equal

#: 免认证路径：只有健康检查，方便探针/负载均衡。
PUBLIC_PATHS: frozenset[str] = frozenset({"/v1/health"})

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


async def require_api_token(
    request: Request,
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI 依赖：校验 API token（未配置则直接放行，见模块 docstring）。"""
    if request.url.path in PUBLIC_PATHS:
        return

    settings = getattr(request.app.state, "settings", None)
    expected = getattr(settings, "api_token", None)
    if not token_is_configured(expected):
        return

    provided = extract_token(x_api_token=x_api_token, authorization=authorization)
    if not tokens_equal(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API token",
            headers=_UNAUTHORIZED_HEADERS,
        )
