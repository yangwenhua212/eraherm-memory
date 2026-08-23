# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import re
from typing import Sequence

from app.models import MemoryType
from app.ports.reflection import ReflectionDraft


def _normalize_correction(text: str, related_contents: Sequence[str] | None = None) -> str:
    t = text.strip()
    related_contents = list(related_contents or [])
    # "应该是 X 不是 Y" / "是 X 不是 Y"
    m = re.search(r"(?:应该是|应为|改成|纠正为|是)\s*(.+?)\s*(?:不是|而非|而不是)\s*(.+)$", t)
    if m:
        correct = m.group(1).strip(" ，,。")
        wrong = m.group(2).strip(" ，,。")
        # 优先在关联记忆里做 wrong→correct 替换，生成干净完整的事实句
        # （避免「正确事实：X（此前误为 Y）」模板拉低嵌入语义分）
        if wrong and correct:
            for rc in related_contents:
                rc = rc.strip()
                if wrong in rc:
                    replaced = rc.replace(wrong, correct)
                    if replaced != rc:
                        return replaced
        return f"{correct}（此前误为 {wrong}）"
    if t and not t.endswith(("。", ".", "！", "!", "？", "?")):
        t = t + "。"
    return t


class HeuristicReflectionPipeline:
    """Offline reflection (no LLM). Swap to LLM pipeline via Port when API key available."""

    def reflect(
        self,
        *,
        feedback_type: str,
        correction_text: str | None,
        answer_text: str | None,
        related_contents: Sequence[str],
    ) -> ReflectionDraft:
        ft = feedback_type.lower()
        if ft == "correct":
            return self._correct(correction_text, answer_text, related_contents)
        if ft == "downvote":
            return self._downvote(correction_text, answer_text, related_contents)
        # upvote should not normally call reflect
        return ReflectionDraft(
            analysis="upvote does not require reflection",
            summary="",
            confidence=0.0,
            memory_type=MemoryType.REFLECTION.value,
        )

    def _correct(
        self,
        correction_text: str | None,
        answer_text: str | None,
        related_contents: Sequence[str],
    ) -> ReflectionDraft:
        text = (correction_text or "").strip()
        if len(text) < 2:
            return ReflectionDraft(
                analysis="纠正文本过短或为空，无法形成可靠修订事实。",
                summary="",
                confidence=0.2,
                memory_type=MemoryType.REFLECTION.value,
            )
        summary = _normalize_correction(text, related_contents)
        analysis_parts = [
            "用户提供了显式纠正。",
            f"纠正原文：{text}",
        ]
        if answer_text:
            analysis_parts.append(f"原回答片段：{answer_text[:200]}")
        if related_contents:
            analysis_parts.append(f"关联记忆条数：{len(related_contents)}")
        # identity-ish corrections get slightly higher confidence
        pinned = bool(re.search(r"用户名|我叫|我是|identity", text, re.I))
        confidence = 0.9 if len(text) >= 6 else 0.75
        if pinned:
            confidence = max(confidence, 0.92)
        return ReflectionDraft(
            analysis=" ".join(analysis_parts),
            summary=summary,
            confidence=confidence,
            memory_type=MemoryType.FACT.value if not pinned else MemoryType.IDENTITY.value,
            pinned=pinned,
        )

    def _downvote(
        self,
        correction_text: str | None,
        answer_text: str | None,
        related_contents: Sequence[str],
    ) -> ReflectionDraft:
        hint = (correction_text or "").strip()
        if hint:
            summary = f"禁忌/负例：{hint}"
            confidence = 0.8
        elif related_contents:
            joined = "；".join(c[:80] for c in related_contents[:3])
            summary = f"以下内容曾被点踩，回答时应避免重复：{joined}"
            confidence = 0.72
        elif answer_text:
            summary = f"以下回答曾被点踩，应避免重复：{answer_text[:160]}"
            confidence = 0.7
        else:
            summary = "用户对某次回答点踩，但缺少可沉淀的负例文本。"
            confidence = 0.45
        return ReflectionDraft(
            analysis="用户点踩，沉淀为 negative 记忆以防复发。",
            summary=summary,
            confidence=confidence,
            memory_type=MemoryType.NEGATIVE.value,
            pinned=False,
        )
