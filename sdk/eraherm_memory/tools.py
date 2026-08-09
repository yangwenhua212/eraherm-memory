# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Hermes built-in memory tools (OpenAI function-calling compatible).

Bind ``user_id`` / ``session_id`` once — the LLM calls ``memory_recall`` /
``memory_remember`` like native tools; no per-turn curl or user_id in args.

Register into Hermes::

    from eraherm_memory import MemoryClient, HermesMemoryTools

    tools = HermesMemoryTools(MemoryClient("http://127.0.0.1:8000"), user_id="hermes:boss")
    hermes.register_openai_tools(tools.openai_tools(), dispatcher=tools.dispatch)

    # or handle a tool call:
    # text = tools.dispatch("memory_recall", {"query": "用户喜欢喝什么"})
"""

from __future__ import annotations

import json
from typing import Any, Callable

from eraherm_memory.client import MemoryClient

TOOL_NAMES = (
    "memory_recall",
    "memory_remember",
    "memory_pin",
    "memory_correct",
    "memory_impact",
)


def _openai_fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


class HermesMemoryTools:
    """Bound memory tools for a single Hermes user / thread."""

    def __init__(
        self,
        client: MemoryClient,
        *,
        user_id: str,
        tenant_id: str | None = None,
        session_id: str | None = None,
        recall_top_k: int = 6,
        auto_open_session: bool = True,
        min_score: float | None = None,
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
                user_id=user_id, meta={"host": "hermes", "via": "builtin_tools"}
            )
            self.session_id = sess["id"]

    # --- schemas -----------------------------------------------------------------

    def openai_tools(self) -> list[dict[str, Any]]:
        """OpenAI / compatible ``tools=[...]`` schemas (user_id already bound)."""
        return [
            _openai_fn(
                "memory_recall",
                "从长期记忆中语义召回与用户问题相关的事实。回答偏好、身份、项目约定前先调用。",
                {
                    "query": {
                        "type": "string",
                        "description": "自然语言查询，不必与原文一致",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "最多返回条数，默认 6",
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                ["query"],
            ),
            _openai_fn(
                "memory_remember",
                "把值得长期保存的事实写入记忆（喜好、技术选型、身份等）。闲聊不要存。",
                {
                    "content": {"type": "string", "description": "要记住的完整事实语句"},
                    "pinned": {
                        "type": "boolean",
                        "description": "是否钉死（身份/硬性偏好建议 true）",
                    },
                    "importance": {
                        "type": "number",
                        "description": "0~1 重要性，默认 0.8",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["fact", "identity", "preference", "episode"],
                        "description": "记忆类型，默认 fact",
                    },
                },
                ["content"],
            ),
            _openai_fn(
                "memory_pin",
                "钉死一条身份/硬性偏好记忆，召回时优先。",
                {
                    "content": {"type": "string", "description": "要钉死的内容"},
                    "memory_id": {
                        "type": "string",
                        "description": "已有记忆 id；与 content 二选一",
                    },
                },
                [],
            ),
            _openai_fn(
                "memory_correct",
                "用户纠正了错误回答时调用：写入纠正事实并降低旧记忆优先级。",
                {
                    "correction": {"type": "string", "description": "正确说法"},
                    "wrong_answer": {
                        "type": "string",
                        "description": "刚才的错误回答（可选）",
                    },
                    "answer_id": {
                        "type": "string",
                        "description": "本轮回答 id，默认 auto",
                    },
                },
                ["correction"],
            ),
            _openai_fn(
                "memory_impact",
                "查询改某个实体/服务会影响谁（知识图谱影响面）。",
                {
                    "entity_name": {"type": "string", "description": "实体或服务名"},
                    "direction": {
                        "type": "string",
                        "enum": ["inbound", "outbound", "both"],
                        "description": "默认 inbound",
                    },
                    "max_hops": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 4,
                        "description": "跳数，默认 2",
                    },
                },
                ["entity_name"],
            ),
        ]

    def tool_names(self) -> list[str]:
        return list(TOOL_NAMES)

    def handlers(self) -> dict[str, Callable[..., str]]:
        """name → callable(**kwargs) returning JSON string."""
        return {
            "memory_recall": self.memory_recall,
            "memory_remember": self.memory_remember,
            "memory_pin": self.memory_pin,
            "memory_correct": self.memory_correct,
            "memory_impact": self.memory_impact,
        }

    # --- dispatch ----------------------------------------------------------------

    def dispatch(self, name: str, arguments: dict[str, Any] | str | None = None) -> str:
        """Execute a tool call; returns JSON text for the LLM tool message."""
        args: dict[str, Any]
        if arguments is None:
            args = {}
        elif isinstance(arguments, str):
            args = json.loads(arguments) if arguments.strip() else {}
        else:
            args = dict(arguments)

        handlers = self.handlers()
        if name not in handlers:
            return json.dumps(
                {"ok": False, "error": f"unknown tool: {name}", "known": list(handlers)},
                ensure_ascii=False,
            )
        try:
            return handlers[name](**args)
        except TypeError as exc:
            return json.dumps({"ok": False, "error": f"bad arguments: {exc}"}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 — surface to LLM, don't crash Hermes
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    def end_session(self) -> dict[str, Any] | None:
        if not self.session_id:
            return None
        out = self.client.close_session(self.session_id)
        self.session_id = None
        return out

    # --- tool bodies -------------------------------------------------------------

    def memory_recall(self, query: str, top_k: int | None = None) -> str:
        recall = self.client.recall(
            user_id=self.user_id,
            query=query,
            session_id=self.session_id,
            top_k=top_k or self.recall_top_k,
            tenant_id=self.tenant_id,
            min_score=self.min_score,
        )
        items = recall.get("items") or []
        self._last_memory_ids = [i["id"] for i in items]
        payload = {
            "ok": True,
            "count": len(items),
            "items": [
                {
                    "id": i.get("id"),
                    "content": i.get("content"),
                    "score": i.get("score"),
                    "pinned": i.get("pinned"),
                    "layer": i.get("layer"),
                }
                for i in items
            ],
            "recommendations": [
                {
                    "content": r.get("content"),
                    "score": r.get("score"),
                    "reason": r.get("reason"),
                }
                for r in (recall.get("recommendations") or [])
            ],
        }
        if not items:
            payload["hint"] = "没有足够相关的记忆；不要编造，可请用户确认或 memory_remember。"
        return json.dumps(payload, ensure_ascii=False)

    def memory_remember(
        self,
        content: str,
        pinned: bool = False,
        importance: float = 0.8,
        memory_type: str = "fact",
    ) -> str:
        mem = self.client.remember(
            content=content,
            user_id=self.user_id,
            session_id=self.session_id,
            pinned=pinned,
            importance=importance,
            memory_type=memory_type,
            extract_graph=True,
            tenant_id=self.tenant_id,
            meta={"host": "hermes", "via": "builtin_tools"},
        )
        return json.dumps(
            {
                "ok": True,
                "id": mem.get("id"),
                "layer": mem.get("layer"),
                "pinned": mem.get("pinned"),
                "alerts": mem.get("alerts") or [],
            },
            ensure_ascii=False,
        )

    def memory_pin(self, content: str | None = None, memory_id: str | None = None) -> str:
        if not content and not memory_id:
            return json.dumps(
                {"ok": False, "error": "provide content or memory_id"},
                ensure_ascii=False,
            )
        out = self.client.pin(
            memory_id=memory_id,
            content=content,
            user_id=self.user_id if content else None,
            pinned=True,
            memory_type="identity",
            session_id=self.session_id,
            tenant_id=self.tenant_id,
        )
        return json.dumps({"ok": True, "memory": out}, ensure_ascii=False)

    def memory_correct(
        self,
        correction: str,
        wrong_answer: str | None = None,
        answer_id: str | None = None,
    ) -> str:
        aid = answer_id or "hermes_correct"
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
        return json.dumps({"ok": True, "feedback": fb}, ensure_ascii=False)

    def memory_impact(
        self,
        entity_name: str,
        direction: str = "inbound",
        max_hops: int = 2,
    ) -> str:
        impact = self.client.impact(
            user_id=self.user_id,
            entity_name=entity_name,
            direction=direction,
            max_hops=max_hops,
            tenant_id=self.tenant_id,
        )
        return json.dumps({"ok": True, "impact": impact}, ensure_ascii=False)
