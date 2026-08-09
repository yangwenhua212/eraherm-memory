# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Thin HTTP SDK for EraHerm-Memory kernel."""

from __future__ import annotations

from typing import Any

import httpx


class MemoryClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, headers=headers or {})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MemoryClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def health(self) -> dict[str, Any]:
        return self._client.get("/v1/health").raise_for_status().json()

    def create_session(self, user_id: str, meta: dict | None = None) -> dict[str, Any]:
        return (
            self._client.post("/v1/sessions", json={"user_id": user_id, "meta": meta or {}})
            .raise_for_status()
            .json()
        )

    def close_session(self, session_id: str) -> dict[str, Any]:
        return self._client.post(f"/v1/sessions/{session_id}/close").raise_for_status().json()

    def remember(
        self,
        *,
        content: str,
        user_id: str,
        session_id: str | None = None,
        memory_type: str = "fact",
        importance: float = 0.5,
        pinned: bool = False,
        extract_graph: bool | None = None,
        tenant_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "content": content,
            "user_id": user_id,
            "session_id": session_id,
            "memory_type": memory_type,
            "importance": importance,
            "pinned": pinned,
            "meta": meta or {},
        }
        if tenant_id is not None:
            body["tenant_id"] = tenant_id
        if extract_graph is not None:
            body["extract_graph"] = extract_graph
        return self._client.post("/v1/memories", json=body).raise_for_status().json()

    def pin(
        self,
        *,
        memory_id: str | None = None,
        pinned: bool = True,
        user_id: str | None = None,
        content: str | None = None,
        memory_type: str = "identity",
        importance: float = 1.0,
        session_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"pinned": pinned, "memory_type": memory_type, "importance": importance}
        if memory_id:
            body["memory_id"] = memory_id
        if user_id:
            body["user_id"] = user_id
        if content:
            body["content"] = content
        if session_id:
            body["session_id"] = session_id
        if tenant_id:
            body["tenant_id"] = tenant_id
        return self._client.post("/v1/memories/pin", json=body).raise_for_status().json()

    def recall(
        self,
        *,
        user_id: str,
        query: str,
        session_id: str | None = None,
        top_k: int = 8,
        include_pinned: bool = True,
        tenant_id: str | None = None,
        min_score: float | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "user_id": user_id,
            "query": query,
            "session_id": session_id,
            "top_k": top_k,
            "include_pinned": include_pinned,
        }
        if tenant_id is not None:
            body["tenant_id"] = tenant_id
        if min_score is not None:
            body["min_score"] = min_score
        return self._client.post("/v1/recall", json=body).raise_for_status().json()

    def impact(
        self,
        *,
        user_id: str,
        entity_name: str,
        direction: str = "inbound",
        max_hops: int = 2,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "user_id": user_id,
            "entity_name": entity_name,
            "direction": direction,
            "max_hops": max_hops,
        }
        if tenant_id is not None:
            body["tenant_id"] = tenant_id
        return self._client.post("/v1/graph/impact", json=body).raise_for_status().json()

    def extract_graph(self, *, user_id: str, text: str, tenant_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"user_id": user_id, "text": text}
        if tenant_id is not None:
            body["tenant_id"] = tenant_id
        return self._client.post("/v1/graph/extract", json=body).raise_for_status().json()

    def feedback(
        self,
        *,
        user_id: str,
        answer_id: str,
        feedback_type: str,
        correction_text: str | None = None,
        related_memory_ids: list[str] | None = None,
        answer_text: str | None = None,
        async_mode: bool | None = None,
        session_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "user_id": user_id,
            "answer_id": answer_id,
            "feedback_type": feedback_type,
            "related_memory_ids": related_memory_ids or [],
            "answer_text": answer_text,
            "correction_text": correction_text,
            "session_id": session_id,
        }
        if tenant_id is not None:
            body["tenant_id"] = tenant_id
        if async_mode is not None:
            body["async_mode"] = async_mode
        return self._client.post("/v1/feedback", json=body).raise_for_status().json()

    def get_feedback(self, feedback_id: str) -> dict[str, Any]:
        return self._client.get(f"/v1/feedback/{feedback_id}").raise_for_status().json()

    def wait_feedback(
        self,
        feedback_id: str,
        *,
        timeout_s: float = 30.0,
        interval_s: float = 0.2,
    ) -> dict[str, Any]:
        """Poll async feedback until reflection is present or timeout."""
        import time

        deadline = time.monotonic() + timeout_s
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.get_feedback(feedback_id)
            if last.get("reflection") is not None and not last.get("async_pending"):
                return last
            if last.get("reflection") is not None and last["reflection"].get("status") in {
                "accepted",
                "rejected",
                "pending",
            }:
                # pending reflection object may exist while async_pending true
                if not last.get("async_pending"):
                    return last
            time.sleep(interval_s)
        return last

    def consolidate(
        self,
        *,
        admin_token: str,
        user_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if user_id is not None:
            body["user_id"] = user_id
        if tenant_id is not None:
            body["tenant_id"] = tenant_id
        return (
            self._client.post(
                "/v1/admin/consolidate",
                json=body,
                headers={"X-Admin-Token": admin_token},
            )
            .raise_for_status()
            .json()
        )
