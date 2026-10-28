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


def remote_embedding_block_reason(
    text: str | None,
    *,
    is_remote: bool,
    enforced: bool = True,
) -> str | None:
    """判断「把这段文本交给远端 embedding API」是否必须被拒绝。

    返回拒绝原因（可直接作为错误信息）；允许外发时返回 ``None``。

    为什么要 fail-closed：``ERAHERM_EMBEDDING_BACKEND=openai`` 是文档推荐的生产
    选项之一，而 embedding 路径**完全不经过**这里的词表 —— 也就是说
    「敏感内容绝不出网」以前是假的：只要正文是记忆内容，它就会被发给 embedding 服务。
    与其保证不了就别说，不如在入口拒绝，把承诺变成真的。

    - ``enforced=False``（``ERAHERM_SENSITIVE_REQUIRES_LOCAL_EMBEDDING=false``）：
      调用方明确接受风险，直接放行。
    - ``is_remote=False``（hashing / fastembed）：本地计算，放行。
    - 词表只覆盖中文关键词，**不是**可靠的 DLP；它拦得住「这是秘密」，
      拦不住「hunter2」。真正的边界只能是本地 embedding。
    """
    if not enforced or not is_remote:
        return None
    if not contains_sensitive(text):
        return None
    return (
        "内容命中敏感词表，而当前 embedding 后端是远端 API —— 拒绝把正文外发。"
        "请改用本地 embedding（ERAHERM_EMBEDDING_BACKEND=fastembed 或 hashing），"
        "或显式接受风险：ERAHERM_SENSITIVE_REQUIRES_LOCAL_EMBEDDING=false。"
    )


def assert_remote_embedding_allowed(
    texts,
    *,
    is_remote: bool,
    enforced: bool = True,
) -> None:
    """对一批待 embedding 的文本做 fail-closed 检查，命中即抛 ``ValueError``。"""
    for text in texts:
        reason = remote_embedding_block_reason(text, is_remote=is_remote, enforced=enforced)
        if reason:
            raise ValueError(reason)
