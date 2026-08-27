# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""敏感内容检测（公共模块）。

铁律：记忆含敏感内容（秘密/红线/私事），**绝不外发**——
LLM 抽取/LLM 反射会把内容发给外部 API（=出网），必须在入口拦截。
watchdog 的「敏感记忆绝不推送」也复用本模块，保证词表只有一份。
"""

from __future__ import annotations

import re

# 敏感提示词：命中即视为不可外发/不可推送的内容
_SENSITIVE_HINTS = re.compile(
    r"(秘密|红线|绝不让|绝对不提|不要告诉|别让.*知道|保密|只告诉|私下|不能提|禁止提及)",
)


def contains_sensitive(text: str | None) -> bool:
    """内容是否含敏感提示词。None/空串 → False（无内容自然不算敏感）。"""
    return bool(_SENSITIVE_HINTS.search(text or ""))
