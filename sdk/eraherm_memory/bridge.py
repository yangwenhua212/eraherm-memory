# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Hermes turn-loop bridge (Host policy over MemoryClient)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from eraherm_memory.client import MemoryClient

_FACT_HINTS = re.compile(
    r"(我(们)?(用|是|叫|偏好|喜欢)|项目|技术栈|数据库|依赖|不要|禁止|记住|以后都|请记住)",
    re.I,
)
_IDENTITY_HINTS = re.compile(r"(我叫|用户名|我的名字|称呼我)", re.I)
_IMPACT_HINTS = re.compile(r"(改|影响|依赖|谁会|blast|impact)", re.I)
_CORRECTION_HINTS = re.compile(r"(不对|错了|应该是|不是.+是|纠正)", re.I)


@dataclass
class TurnContext:
    """Memory payload Hermes should inject before calling the LLM."""

    recall_block: str
    recommendations_block: str = ""
    impact_block: str = ""
    raw_recall: dict[str, Any] = field(default_factory=dict)
    raw_impact: dict[str, Any] | None = None


@dataclass
class TurnResult:
    """Optional post-turn writes Hermes can apply after the LLM answers."""

    remembered: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    feedback: dict[str, Any] | None = None


class HermesMemoryBridge:
    """Thin Host policy over MemoryClient.

    Recommended Hermes turn order:
      1. bridge.before_turn(user_text)  → inject into system/tool context
      2. Hermes LLM / tools produce answer
      3. bridge.after_turn(user_text, answer, ...)  → remember / feedback
      4. on conversation end: bridge.end_session()

    For LLM-callable tools (no curl), prefer ``HermesMemoryTools``.
    """

    def __init__(
        self,
        client: MemoryClient,
        *,
        user_id: str,
        tenant_id: str | None = None,
        session_id: str | None = None,
        recall_top_k: int = 6,
        auto_open_session: bool = True,
        on_alerts: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> None:
        self.client = client
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.recall_top_k = recall_top_k
        self.on_alerts = on_alerts
        self._last_memory_ids: list[str] = []
        if auto_open_session and not self.session_id:
            sess = self.client.create_session(user_id=user_id, meta={"host": "hermes"})
            self.session_id = sess["id"]

    def before_turn(self, user_text: str) -> TurnContext:
        recall = self.client.recall(
            user_id=self.user_id,
            query=user_text,
            session_id=self.session_id,
            top_k=self.recall_top_k,
            tenant_id=self.tenant_id,
        )
        self._last_memory_ids = [i["id"] for i in recall.get("items", [])]

        impact_raw = None
        impact_block = ""
        entity = _extract_impact_entity(user_text)
        if entity:
            try:
                impact_raw = self.client.impact(
                    user_id=self.user_id,
                    entity_name=entity,
                    direction="inbound",
                    tenant_id=self.tenant_id,
                )
                impact_block = format_impact(impact_raw)
            except Exception:  # noqa: BLE001 — Host must not crash the turn
                impact_block = ""

        return TurnContext(
            recall_block=format_recall(recall),
            recommendations_block=format_recommendations(recall),
            impact_block=impact_block,
            raw_recall=recall,
            raw_impact=impact_raw,
        )

    def after_turn(
        self,
        user_text: str,
        answer_text: str,
        *,
        answer_id: str,
        user_feedback: str | None = None,
        correction_text: str | None = None,
        force_remember: str | None = None,
    ) -> TurnResult:
        result = TurnResult()

        if user_feedback in {"upvote", "downvote", "correct"}:
            fb = self.client.feedback(
                user_id=self.user_id,
                answer_id=answer_id,
                feedback_type=user_feedback,
                correction_text=correction_text,
                related_memory_ids=list(self._last_memory_ids),
                answer_text=answer_text,
                session_id=self.session_id,
                tenant_id=self.tenant_id,
                async_mode=False,
            )
            result.feedback = fb
            return result

        if _CORRECTION_HINTS.search(user_text) and correction_text is None:
            fb = self.client.feedback(
                user_id=self.user_id,
                answer_id=answer_id,
                feedback_type="correct",
                correction_text=user_text,
                related_memory_ids=list(self._last_memory_ids),
                answer_text=answer_text,
                session_id=self.session_id,
                tenant_id=self.tenant_id,
                async_mode=False,
            )
            result.feedback = fb
            return result

        to_store = force_remember or _maybe_extract_memory(user_text)
        if to_store:
            pinned = bool(_IDENTITY_HINTS.search(to_store))
            mem = self.client.remember(
                content=to_store,
                user_id=self.user_id,
                session_id=self.session_id,
                memory_type="identity" if pinned else "fact",
                importance=0.95 if pinned else 0.75,
                pinned=pinned,
                extract_graph=True,
                tenant_id=self.tenant_id,
                meta={"host": "hermes", "source_turn": answer_id},
            )
            result.remembered.append(mem)
            alerts = mem.get("alerts") or []
            result.alerts.extend(alerts)
            if alerts and self.on_alerts:
                self.on_alerts(alerts)

        return result

    def end_session(self) -> dict[str, Any] | None:
        if not self.session_id:
            return None
        out = self.client.close_session(self.session_id)
        self.session_id = None
        return out

    def build_system_suffix(self, ctx: TurnContext) -> str:
        parts = ["## EraHerm Memory Context", ctx.recall_block]
        if ctx.recommendations_block:
            parts.append(ctx.recommendations_block)
        if ctx.impact_block:
            parts.append(ctx.impact_block)
        parts.append(
            "优先采信钉死(pinned)与高分记忆；若与用户当轮表述冲突，以用户为准并准备纠正。"
        )
        return "\n\n".join(p for p in parts if p.strip())


def format_recall(recall: dict[str, Any]) -> str:
    items = recall.get("items") or []
    if not items:
        return "### Recalled memories\n(none)"
    lines = ["### Recalled memories"]
    for it in items:
        pin = " [pinned]" if it.get("pinned") else ""
        lines.append(
            f"- ({it.get('layer')}, score={it.get('score', 0):.2f}){pin} {it.get('content')}"
        )
    return "\n".join(lines)


def format_recommendations(recall: dict[str, Any]) -> str:
    recs = recall.get("recommendations") or []
    if not recs:
        return ""
    lines = ["### Related recommendations"]
    for r in recs:
        lines.append(
            f"- ({r.get('reason')}, score={r.get('score', 0):.2f}) {r.get('content')}"
        )
    return "\n".join(lines)


def format_impact(impact: dict[str, Any]) -> str:
    seed = (impact.get("seed") or {}).get("name", "?")
    lines = [f"### Impact: changing `{seed}` may affect"]
    paths = impact.get("paths") or []
    if not paths:
        lines.append("(no inbound dependents found)")
        return "\n".join(lines)
    for p in paths:
        names = [n.get("name") for n in p.get("nodes") or []]
        lines.append("- " + " → ".join(names))
    for r in impact.get("recommendations") or []:
        lines.append(f"- experience: {r.get('content')}")
    return "\n".join(lines)


def _maybe_extract_memory(user_text: str) -> str | None:
    text = user_text.strip()
    if len(text) < 4:
        return None
    if _FACT_HINTS.search(text) or _IDENTITY_HINTS.search(text):
        return text
    return None


def _extract_impact_entity(user_text: str) -> str | None:
    if not _IMPACT_HINTS.search(user_text):
        return None
    m = re.search(r"(?:改|关于)?\s*([A-Za-z0-9_\-]+服务|[A-Za-z][\w\-]+)\s*", user_text)
    if m:
        return m.group(1)
    m2 = re.search(r"([一-龥A-Za-z0-9_\-]+服务)", user_text)
    return m2.group(1) if m2 else None
