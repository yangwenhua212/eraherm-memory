# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import re

from app.models import MemoryType

# Keywords that usually signal durable facts / project context.
_FACT_PATTERNS = (
    r"项目",
    r"依赖",
    r"使用",
    r"技术栈",
    r"数据库",
    r"api",
    r"服务",
    r"用户名",
    r"偏好",
    r"喜欢",
    r"不喜欢",
    r"叫",
    r"名为",
    r"fastapi",
    r"sqlite",
    r"postgres",
    r"redis",
    r"eraherm",
)

_CHITCHAT_PATTERNS = (
    r"天气",
    r"哈哈",
    r"你好",
    r"在吗",
    r"早上好",
    r"晚安",
    r"谢谢",
)


def score_importance(
    *,
    content: str,
    memory_type: str,
    pinned: bool = False,
) -> float:
    """Rule-based importance heuristic (0–1)."""
    if pinned:
        return 1.0

    base = {
        MemoryType.IDENTITY.value: 0.95,
        MemoryType.PREFERENCE.value: 0.85,
        MemoryType.FACT.value: 0.7,
        MemoryType.REFLECTION.value: 0.75,
        MemoryType.NEGATIVE.value: 0.7,
        MemoryType.EPISODE.value: 0.35,
    }.get(memory_type, 0.5)

    text = content.strip()
    length_bonus = 0.0
    if len(text) >= 40:
        length_bonus += 0.05
    if len(text) >= 80:
        length_bonus += 0.05

    lowered = text.lower()
    fact_hits = sum(1 for p in _FACT_PATTERNS if re.search(p, lowered, re.I))
    chat_hits = sum(1 for p in _CHITCHAT_PATTERNS if re.search(p, lowered, re.I))

    score = base + length_bonus + min(fact_hits, 3) * 0.05 - min(chat_hits, 2) * 0.15
    return max(0.0, min(1.0, score))


def resolve_importance(
    *,
    content: str,
    memory_type: str,
    pinned: bool,
    provided: float,
    auto: bool,
) -> float:
    if pinned:
        return max(provided, 0.9)
    if not auto:
        return provided
    return max(provided, score_importance(content=content, memory_type=memory_type, pinned=False))
