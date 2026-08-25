# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""静态检查：MCP 服务器 HTTP 转发路径必须带 /v1 前缀。

背景：2026-08-23 发现 app/mcp_server.py 与 eraherm_mcp_server.py 都把
/graph/impact 写错（路由前缀是 /v1，实际是 /v1/graph/impact），HTTP 模式
下 impact 一直 404。此测试防止路径类 bug 复发（无需起服务）。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP_FILES = ["eraherm_mcp_server.py", "app/mcp_server.py"]

# 允许无 /v1 前缀的路径（根路径 / 或明确的非版本路径）
_ALLOWED_BARE = {"/", "/demo/", "/docs", "/openapi.json", "/v1/health"}


def _http_paths(file: Path) -> list[str]:
    src = file.read_text(encoding="utf-8")
    return re.findall(r'"(/[^"]+)"', src)


def test_mcp_forward_paths_have_v1_prefix() -> None:
    for name in MCP_FILES:
        for p in _http_paths(ROOT / name):
            # 只检查转发用的 API 路径：/v1、/graph、/admin 开头
            if p.startswith("/graph") or p.startswith("/admin") or p.startswith("/v"):
                assert p.startswith("/v1/"), f"{name}: {p} 缺 /v1 前缀（路由前缀是 /v1）"


def test_mcp_admin_auth_header_is_x_admin_token() -> None:
    """MCP HTTP 转发必须带 X-Admin-Token 头（后端只认这个头）。

    背景：2026-08-25 发现两处漂移——
    1. app/mcp_server.py 的 _post 完全不带头 → admin 端点 401；
    2. eraherm_mcp_server.py 错用 Authorization: Bearer → 后端不认，401。
    此测试防止头字段再漂移。
    """
    src_app = (ROOT / "app" / "mcp_server.py").read_text(encoding="utf-8")
    src_cursor = (ROOT / "eraherm_mcp_server.py").read_text(encoding="utf-8")

    # 1. app/mcp_server.py：_post 必须设置 X-Admin-Token（从 ERAHERM_ADMIN_TOKEN）
    assert '"X-Admin-Token"' in src_app, "app/mcp_server.py: _post 缺 X-Admin-Token 头"
    assert "ERAHERM_ADMIN_TOKEN" in src_app, "app/mcp_server.py: 未从 ERAHERM_ADMIN_TOKEN 读取 token"

    # 2. eraherm_mcp_server.py：必须用 X-Admin-Token，禁止 Authorization: Bearer
    assert '"X-Admin-Token"' in src_cursor, "eraherm_mcp_server.py: 缺 X-Admin-Token 头"
    assert "Authorization" not in src_cursor, "eraherm_mcp_server.py: 误用 Authorization 头（后端只认 X-Admin-Token）"
