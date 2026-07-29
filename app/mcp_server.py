# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

"""EraHerm-Memory MCP Server — stdio tools for Cursor / Claude Desktop.

Run:
  python -m app.mcp_server

Configure (Claude Desktop / Cursor) — see mcp.json example.
"""

from __future__ import annotations

import json
from typing import Any

from app.container import Container, build_container

_container: Container | None = None


def _c() -> Container:
    global _container
    if _container is None:
        _container = build_container()
    return _container


def create_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "MCP extra required: pip install 'eraherm-memory[mcp]'"
        ) from exc

    mcp = FastMCP(
        "eraherm-memory",
        instructions=(
            "EraHerm-Memory kernel tools. Use remember to store durable facts, "
            "recall to retrieve user/project memory, impact for dependency blast radius."
        ),
    )

    @mcp.tool()
    def remember(
        content: str,
        user_id: str = "default",
        importance: float = 0.8,
        pinned: bool = False,
        memory_type: str = "fact",
        extract_graph: bool = True,
    ) -> str:
        """Store a durable memory fact for a user (L1/L2). Returns JSON with id and alerts."""
        result = _c().memory_service.remember(
            content=content,
            user_id=user_id,
            importance=importance,
            pinned=pinned,
            memory_type=memory_type,
            extract_graph=extract_graph,
        )
        return json.dumps(
            {
                "id": result.id,
                "layer": result.layer,
                "pinned": result.pinned,
                "alerts": [
                    {
                        "type": a.type,
                        "severity": a.severity,
                        "message": a.message,
                        "related_memory_ids": a.related_memory_ids,
                    }
                    for a in result.alerts
                ],
            },
            ensure_ascii=False,
        )

    @mcp.tool()
    def recall(
        query: str,
        user_id: str = "default",
        top_k: int = 8,
    ) -> str:
        """Recall relevant memories for a query. Use when asked about past project facts."""
        items = _c().memory_service.recall(user_id=user_id, query=query, top_k=top_k)
        recs = _c().memory_service.recommend_sidecar(
            user_id=user_id, query=query, exclude_memory_ids=[i.id for i in items]
        )
        return json.dumps(
            {
                "items": [
                    {
                        "id": i.id,
                        "content": i.content,
                        "score": i.score,
                        "pinned": i.pinned,
                        "layer": i.layer,
                        "memory_type": i.memory_type,
                    }
                    for i in items
                ],
                "recommendations": [
                    {
                        "memory_id": r.memory_id,
                        "content": r.content,
                        "score": r.score,
                        "reason": r.reason,
                    }
                    for r in recs
                ],
            },
            ensure_ascii=False,
        )

    @mcp.tool()
    def impact(
        entity_name: str,
        user_id: str = "default",
        direction: str = "inbound",
        max_hops: int = 2,
    ) -> str:
        """Graph impact: who is affected if entity changes (inbound) or what it depends on (outbound)."""
        result = _c().graph_service.impact(
            user_id=user_id,
            entity_name=entity_name,
            direction=direction,
            max_hops=max_hops,
        )
        payload: dict[str, Any] = {
            "seed": {
                "id": result.seed.id,
                "name": result.seed.name,
                "entity_type": result.seed.entity_type,
            },
            "direction": result.direction,
            "max_hops": result.max_hops,
            "paths": [
                {
                    "hops": p.hops,
                    "nodes": [{"id": n.id, "name": n.name, "entity_type": n.entity_type} for n in p.nodes],
                }
                for p in result.paths
            ],
        }
        return json.dumps(payload, ensure_ascii=False)

    @mcp.tool()
    def consolidate(user_id: str | None = None) -> str:
        """Run memory consolidation (reweight / compress / conflict forget) for one user or all."""
        svc = _c().consolidation_service
        if svc is None:
            return json.dumps({"error": "consolidation unavailable"})
        if user_id:
            reports = [svc.run_for_user(user_id)]
        else:
            reports = svc.run_all()
        return json.dumps([r.to_dict() for r in reports], ensure_ascii=False)

    @mcp.tool()
    def health() -> str:
        """Health check for EraHerm-Memory MCP server."""
        from app import __version__

        return json.dumps({"status": "ok", "version": __version__, "transport": "stdio"})

    return mcp


def main() -> None:
    mcp = create_mcp()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
