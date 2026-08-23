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
