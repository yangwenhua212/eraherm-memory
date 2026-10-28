# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Memory domain package.

刻意改为惰性导入（PEP 562）：``app.memory.gate`` 是纯函数模块（门禁/词法信号），
单测它不该因为「导入了同包的子模块」而顺带把 sqlmodel 和整个 service 拉起来。
以前的 ``__init__`` 是急切导入，唯一效果就是让纯逻辑无法被便宜地测到。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查器
    from app.memory.importance import score_importance
    from app.memory.service import MemoryService, effective_score

__all__ = ["MemoryService", "effective_score", "score_importance"]


def __getattr__(name: str) -> Any:
    if name in {"MemoryService", "effective_score"}:
        from app.memory.service import effective_score, MemoryService

        return {"MemoryService": MemoryService, "effective_score": effective_score}[name]
    if name == "score_importance":
        from app.memory.importance import score_importance

        return score_importance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
