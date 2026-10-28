# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""敏感内容 × 远端 embedding 的 fail-closed 策略（纯函数，不需要 sqlmodel）。

背景：`.env.example` 与 DEPLOYMENT.md 都推荐 `ERAHERM_EMBEDDING_BACKEND=openai`，
而 embedding 路径**完全不经过** app/sensitive.py 的词表 —— 也就是说
「敏感内容绝不出网」在 0.10.2 之前是**假的**：只要正文是记忆内容，它就会被发给
远端 embedding 服务。本文件锁住修复后的语义：宁可拒绝入库，也不外发。
"""

from __future__ import annotations

import pytest

from app.sensitive import (
    assert_remote_embedding_allowed,
    contains_sensitive,
    remote_embedding_block_reason,
)

SENSITIVE = "这是秘密，不要告诉任何人"
SAFE = "项目使用 FastAPI"


def test_detects_chinese_sensitive_keywords() -> None:
    assert contains_sensitive(SENSITIVE) is True
    assert contains_sensitive(SAFE) is False
    assert contains_sensitive(None) is False
    assert contains_sensitive("") is False


def test_local_embedding_is_never_blocked() -> None:
    # 本地（hashing / fastembed）不出网，敏感内容照常入库
    assert remote_embedding_block_reason(SENSITIVE, is_remote=False) is None
    assert_remote_embedding_allowed([SENSITIVE], is_remote=False)


def test_remote_embedding_blocks_sensitive_content() -> None:
    reason = remote_embedding_block_reason(SENSITIVE, is_remote=True)
    assert reason is not None
    assert "ERAHERM_SENSITIVE_REQUIRES_LOCAL_EMBEDDING" in reason
    with pytest.raises(ValueError, match="敏感"):
        assert_remote_embedding_allowed([SAFE, SENSITIVE], is_remote=True)


def test_remote_embedding_allows_non_sensitive_content() -> None:
    assert remote_embedding_block_reason(SAFE, is_remote=True) is None
    assert_remote_embedding_allowed([SAFE, "另一条普通记忆"], is_remote=True)


def test_explicit_opt_out_disables_the_guard() -> None:
    """显式接受风险时必须放行 —— 否则等于没有开关。"""
    assert (
        remote_embedding_block_reason(SENSITIVE, is_remote=True, enforced=False) is None
    )
    assert_remote_embedding_allowed([SENSITIVE], is_remote=True, enforced=False)


def test_guard_is_documented_as_a_wordlist_not_a_boundary() -> None:
    """词表的局限必须在测试里留痕：它拦不住「hunter2」这类没有中文关键词的秘密。

    这条断言的作用不是「验证功能」，而是防止有人把词表当成 DLP 依据：一旦有人
    扩表到能拦住下面这句，这个测试会失败，提醒他去看 ADR 0014 的边界说明。
    """
    assert contains_sensitive("我的密码是 hunter2") is False
    assert contains_sensitive("the secret is hunter2") is False
