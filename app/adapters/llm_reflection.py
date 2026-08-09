# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Sequence

from app.adapters.heuristic_reflection import HeuristicReflectionPipeline
from app.adapters.openai_llm import OpenAICompatibleLLM
from app.models import MemoryType
from app.ports.reflection import ReflectionDraft

_SYSTEM = """你是 Agent 记忆反思器。根据用户反馈分析错误原因，输出 JSON：
{
  "analysis": "为什么错了",
  "summary": "应写入长期记忆的陈述句",
  "confidence": 0.0-1.0,
  "memory_type": "fact|identity|preference|negative|reflection",
  "pinned": false
}
summary 必须是可复用的正确事实或负例，不要空话。"""


class LLMReflectionPipeline:
    def __init__(self, llm: OpenAICompatibleLLM) -> None:
        self.llm = llm
        self._fallback = HeuristicReflectionPipeline()

    def reflect(
        self,
        *,
        feedback_type: str,
        correction_text: str | None,
        answer_text: str | None,
        related_contents: Sequence[str],
    ) -> ReflectionDraft:
        user = (
            f"feedback_type={feedback_type}\n"
            f"correction_text={correction_text or ''}\n"
            f"answer_text={answer_text or ''}\n"
            f"related_memories={list(related_contents)}\n"
        )
        try:
            data = self.llm.complete_json(system=_SYSTEM, user=user)
            summary = str(data.get("summary", "")).strip()
            conf = float(data.get("confidence", 0.0))
            if not summary:
                raise ValueError("empty summary")
            mem_type = str(data.get("memory_type", MemoryType.FACT.value))
            return ReflectionDraft(
                analysis=str(data.get("analysis", "")),
                summary=summary,
                confidence=max(0.0, min(1.0, conf)),
                memory_type=mem_type,
                pinned=bool(data.get("pinned", False)),
            )
        except Exception:  # noqa: BLE001
            return self._fallback.reflect(
                feedback_type=feedback_type,
                correction_text=correction_text,
                answer_text=answer_text,
                related_contents=related_contents,
            )
