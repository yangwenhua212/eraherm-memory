# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""EraHerm-Memory Cursor 适配器 — 独立 stdio MCP 服务器（不经 Hermes）。

Cursor / Claude Desktop 在 mcp.json 里加一段配置即可用自然语言读写记忆：

    "mcpServers": {
      "eraherm": {
        "command": "python",
        "args": ["eraherm_mcp_server.py"],
        "env": {
          "ERAHERM_API_URL": "http://127.0.0.1:8000",
          "ERAHERM_USER_ID": "cursor:laoda"
        }
      }
    }

设计要点：
- 零依赖 app.*：不加载 embedding 模型、不起本地容器，所有工具经 urllib
  转发到 ERAHERM_API_URL（uvicorn 进程持有模型，本进程保持 ~30MB）。
- 工具名带 eraherm_ 前缀，避免与 Cursor 里其它 MCP 冲突。
- evolve = 纠正即进化：POST /v1/feedback(feedback_type=correct)。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any

_API_BASE = os.getenv("ERAHERM_API_URL", "http://127.0.0.1:8000").rstrip("/")
_DEFAULT_USER = os.getenv("ERAHERM_USER_ID", "cursor:user")
_ADMIN_TOKEN = os.getenv("ERAHERM_ADMIN_TOKEN", "")


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if _ADMIN_TOKEN:
        h["Authorization"] = f"Bearer {_ADMIN_TOKEN}"
    return h


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{_API_BASE}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str) -> dict[str, Any]:
    req = urllib.request.Request(f"{_API_BASE}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _safe(fn):
    """把 HTTP 异常转成可读 JSON 错误，MCP 工具始终返回字符串。"""
    try:
        return fn()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return json.dumps({"error": f"HTTP {exc.code}", "detail": body[:300]}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {"error": type(exc).__name__, "detail": str(exc)[:300],
             "hint": f"EraHerm 服务在 {_API_BASE} 吗？先启动 uvicorn。"},
            ensure_ascii=False,
        )


def create_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise SystemExit(
            "需要 mcp SDK：pip install 'mcp>=1.9.0'"
        ) from exc

    mcp = FastMCP(
        "eraherm",
        instructions=(
            "EraHerm-Memory 记忆内核工具（经 HTTP 转发，不依赖 Hermes）。"
            "eraherm_recall 查用户/项目历史记忆；eraherm_remember 存长期事实；"
            "eraherm_evolve 处理用户纠正（纠正即进化）；eraherm_impact 查改动影响面。"
        ),
    )

    @mcp.tool()
    def eraherm_remember(
        content: str,
        user_id: str = _DEFAULT_USER,
        importance: float = 0.8,
        pinned: bool = False,
        memory_type: str = "fact",
        extract_graph: bool = True,
    ) -> str:
        """存一条长期事实记忆（L1/L2）。返回 JSON：id / layer / pinned / alerts。"""
        return _safe(lambda: json.dumps(
            _post("/v1/memories", {
                "content": content,
                "user_id": user_id,
                "importance": importance,
                "pinned": pinned,
                "memory_type": memory_type,
                "extract_graph": extract_graph,
            }),
            ensure_ascii=False,
        ))

    @mcp.tool()
    def eraherm_recall(
        query: str,
        user_id: str = _DEFAULT_USER,
        top_k: int = 8,
        min_score: float | None = None,
    ) -> str:
        """语义召回相关记忆（换词也能中）。返回 JSON：items[]（含 score/pinned）。"""
        def _run():
            payload: dict[str, Any] = {
                "user_id": user_id,
                "query": query,
                "top_k": top_k,
            }
            if min_score is not None:
                payload["min_score"] = min_score
            return _post("/v1/recall", payload)
        return _safe(lambda: json.dumps(_run(), ensure_ascii=False))

    @mcp.tool()
    def eraherm_evolve(
        correction: str,
        user_id: str = _DEFAULT_USER,
        answer: str | None = None,
        related_memory_ids: list[str] | None = None,
        async_mode: bool = False,
    ) -> str:
        """用户纠正 → 纠正即进化：写入新事实（pinned）并让旧事实让路。

        correction 例：「应该是 PostgreSQL 不是 MySQL」。返回 JSON：feedback_id / reflection。
        """
        payload: dict[str, Any] = {
            "user_id": user_id,
            "answer_id": f"cursor-{uuid.uuid4().hex[:12]}",
            "feedback_type": "correct",
            "correction_text": correction,
            "answer_text": answer,
            "related_memory_ids": list(related_memory_ids or []),
            "async_mode": async_mode,
        }
        return _safe(lambda: json.dumps(_post("/v1/feedback", payload), ensure_ascii=False))

    @mcp.tool()
    def eraherm_impact(
        entity_name: str,
        user_id: str = _DEFAULT_USER,
        direction: str = "inbound",
        max_hops: int = 2,
    ) -> str:
        """图谱影响面：改 X 会影响谁（inbound）/ X 依赖什么（outbound）。"""
        return _safe(lambda: json.dumps(
            _post("/v1/graph/impact", {
                "entity_name": entity_name,
                "user_id": user_id,
                "direction": direction,
                "max_hops": max_hops,
            }),
            ensure_ascii=False,
        ))

    @mcp.tool()
    def eraherm_consolidate(user_id: str | None = None) -> str:
        """手动触发记忆整理压缩（reweight / 冲突遗忘）。user_id 为空则全部。"""
        return _safe(lambda: json.dumps(
            _post("/v1/admin/consolidate", {"user_id": user_id}),
            ensure_ascii=False,
        ))

    @mcp.tool()
    def eraherm_health() -> str:
        """健康检查：确认 EraHerm 服务可达。"""
        return _safe(lambda: json.dumps(
            {"status": "ok", "service": _get("/v1/health")}, ensure_ascii=False
        ))

    return mcp


def main() -> None:
    create_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
