# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Agent-facing memory API — the "memory." capability layer for Host agents.

Wraps ``MemoryClient`` into five Agent-like capabilities (see
docs/HERMES_INTEGRATION.md §0)::

    memory.learn()      # 从对话/反馈中沉淀
    memory.remember()   # 显式写入事实
    memory.reflect()    # 整理 / 压缩 / 冲突处理
    memory.recall()     # 语义召回
    memory.evolve()     # 纠正即进化（新事实压过旧版）

Usage::

    from eraherm_memory import AgentMemory, MemoryClient

    memory = AgentMemory(MemoryClient("http://127.0.0.1:8000"), user_id="hermes:boss")
    memory.remember("用户喜欢喝冰美式", pinned=True)
    items = memory.recall("下午喝什么")
    memory.learn("用户说：数据库用 PostgreSQL，以后都用它")
    memory.evolve("用户喜欢冰美式，不是热美式", wrong_answer="热美式")
    memory.reflect(admin_token="...")   # 夜间整理

Unlike ``HermesMemoryTools`` (LLM-callable function schemas), this layer is
for Host-side code that wants a Pythonic, capability-shaped API.
"""

from __future__ import annotations

from typing import Any

from eraherm_memory.bridge import _maybe_extract_memory
from eraherm_memory.client import MemoryClient


class AgentMemory:
    """Five-capability memory facade bound to one user (optionally one thread)."""

    def __init__(
        self,
        client: MemoryClient,
        *,
        user_id: str,
        tenant_id: str | None = None,
        session_id: str | None = None,
        recall_top_k: int = 6,
        min_score: float | None = None,
        auto_open_session: bool = True,
    ) -> None:
        self.client = client
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.recall_top_k = recall_top_k
        self.min_score = min_score
        self._last_memory_ids: list[str] = []
        if auto_open_session and not self.session_id:
            sess = self.client.create_session(
                user_id=user_id, meta={"host": "hermes", "via": "agent_memory"}
            )
            self.session_id = sess["id"]

    # --- capabilities ---------------------------------------------------------

    def remember(
        self,
        content: str,
        *,
        pinned: bool = False,
        importance: float = 0.8,
        memory_type: str = "fact",
        extract_graph: bool = True,
    ) -> dict[str, Any]:
        """Explicitly store a durable fact."""
        mem = self.client.remember(
            content=content,
            user_id=self.user_id,
            session_id=self.session_id,
            memory_type=memory_type,
            importance=importance,
            pinned=pinned,
            extract_graph=extract_graph,
            tenant_id=self.tenant_id,
            meta={"host": "hermes", "via": "agent_memory.remember"},
        )
        mem = dict(mem)
        mem.setdefault("content", content)
        return mem

    def recall(
        self,
        query: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> dict[str, Any]:
        """Semantic recall (paraphrase-tolerant). Returns raw recall payload."""
        recall = self.client.recall(
            user_id=self.user_id,
            query=query,
            session_id=self.session_id,
            top_k=top_k or self.recall_top_k,
            tenant_id=self.tenant_id,
            min_score=min_score if min_score is not None else self.min_score,
        )
        self._last_memory_ids = [i["id"] for i in recall.get("items") or []]
        return recall

    def learn(
        self,
        text: str,
        *,
        pinned: bool = False,
        importance: float = 0.75,
    ) -> dict[str, Any] | None:
        """Sink durable facts out of a conversation fragment.

        Heuristic: identity hints ("我叫…") are pinned; other fact hints
        (项目/技术栈/偏好/请记住…) are stored as facts. Returns None when
        nothing worth remembering was found (pure chit-chat).
        """
        to_store = _maybe_extract_memory(text)
        if not to_store:
            return None
        memory_type = "identity" if pinned else "fact"
        mem = self.client.remember(
            content=to_store,
            user_id=self.user_id,
            session_id=self.session_id,
            memory_type=memory_type,
            importance=0.95 if pinned else importance,
            pinned=pinned,
            extract_graph=True,
            tenant_id=self.tenant_id,
            meta={"host": "hermes", "via": "agent_memory.learn"},
        )
        mem = dict(mem)
        mem.setdefault("content", to_store)
        self._last_memory_ids = [mem["id"]]
        return mem

    def evolve(
        self,
        correction: str,
        *,
        wrong_answer: str | None = None,
        answer_id: str | None = None,
    ) -> dict[str, Any]:
        """Correct → feedback → reflection → new fact outranks the old one."""
        aid = answer_id or "hermes_evolve"
        fb = self.client.feedback(
            user_id=self.user_id,
            answer_id=aid,
            feedback_type="correct",
            correction_text=correction,
            related_memory_ids=list(self._last_memory_ids),
            answer_text=wrong_answer,
            session_id=self.session_id,
            tenant_id=self.tenant_id,
            async_mode=False,
        )
        return fb

    def reflect(
        self,
        *,
        admin_token: str,
        target_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Consolidate: reweight importance, compress, drop conflicts.

        Requires the server admin token (operations capability).
        """
        return self.client.consolidate(
            admin_token=admin_token,
            user_id=target_user_id or self.user_id,
            tenant_id=self.tenant_id,
        )

    def end_session(self) -> dict[str, Any] | None:
        if not self.session_id:
            return None
        out = self.client.close_session(self.session_id)
        self.session_id = None
        return out

    # --- convenience ----------------------------------------------------------

    def recall_text(self, query: str, **kwargs: Any) -> str:
        """Human-readable recall for debug / CLI / prompt injection."""
        recall = self.recall(query, **kwargs)
        items = recall.get("items") or []
        lines = []
        for it in items:
            pin = " [pinned]" if it.get("pinned") else ""
            lines.append(
                f"- ({it.get('layer')}, score={it.get('score', 0):.2f}){pin} {it.get('content')}"
            )
        return "\n".join(lines) if lines else "(none)"
