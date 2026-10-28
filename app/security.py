# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""安全原语：API token 校验、暴露面守卫、文件名/路径收敛。

设计约束：**本模块只依赖标准库**。

理由有两个：
1. 这些判断是纯函数，不碰数据库和网络，放在这里可以被单测直接覆盖（不需要 sqlmodel）；
2. FastAPI 依赖注入层（``app/api/auth.py``）和归档适配器都复用同一份判断，
   避免"三处各写一遍校验"然后漂移。

背景：0.10.x 之前整个 HTTP 面除了 ``/v1/admin/*`` 之外没有任何认证，``user_id``
完全由调用方自报（见 SECURITY.md 与 ADR 0012）。本模块提供可测试的原语，
装配在 ``app/api/auth.py`` / ``app/main.py`` / ``app/adapters/filesystem_archive.py``。
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path

#: 与 .env.example / 文档一起发布的占位值。**视为「未配置」**，绝不接受。
#: 这是一个 fail-closed 白名单：默认值不可能成为有效凭据。
PLACEHOLDER_TOKENS: frozenset[str] = frozenset(
    {
        "",
        "dev-admin-token",
        "dev-api-token",
        "changeme",
        "change-me",
        "CHANGE_ME",
        "your-admin-token",
        "your-api-token",
        "test",
    }
)

#: 视为「只在本机可达」的绑定地址。其余地址都需要 API token。
_LOOPBACK_HOSTS: frozenset[str] = frozenset(
    {"127.0.0.1", "127.0.0.2", "::1", "localhost", "localhost.localdomain"}
)

_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._:@-]+")


def is_loopback_host(host: str | None) -> bool:
    """绑定地址是否只在本机可达（大小写与空白不敏感）。"""
    return (host or "").strip().lower() in _LOOPBACK_HOSTS


def token_is_configured(token: str | None) -> bool:
    """token 是否是一个真正被配置过的值（非空、非占位符）。"""
    value = (token or "").strip()
    if not value:
        return False
    return value not in PLACEHOLDER_TOKENS


def tokens_equal(provided: str | None, expected: str | None) -> bool:
    """恒定时间比较；任一侧未配置/为空一律 False（fail-closed）。"""
    if not token_is_configured(expected) or not token_is_configured(provided):
        return False
    return secrets.compare_digest((provided or "").strip(), (expected or "").strip())


def extract_token(
    *,
    x_api_token: str | None = None,
    authorization: str | None = None,
) -> str | None:
    """从请求头里取出 token。优先 ``X-API-Token``，兼容 ``Authorization: Bearer``。

    只支持 Bearer：其它 scheme（Basic 等）一律忽略，避免把 base64 凭据当 token。
    """
    if x_api_token and x_api_token.strip():
        return x_api_token.strip()
    raw = (authorization or "").strip()
    if not raw:
        return None
    scheme, _, value = raw.partition(" ")
    if scheme.lower() != "bearer":
        return None
    value = value.strip()
    return value or None


def exposure_problem(
    *,
    host: str | None,
    api_token: str | None,
    admin_token: str | None = None,
    allow_insecure_public: bool = False,
) -> str | None:
    """返回「当前配置会把无认证的记忆库暴露到网络」的原因；安全则返回 None。

    ``admin_token`` 未配置不构成阻断（admin 路由本身已 fail-closed 返回 503），
    只有 ``api_token`` 缺失才会拒绝启动。
    """
    if allow_insecure_public or is_loopback_host(host):
        return None
    if token_is_configured(api_token):
        return None

    hint = (
        f"拒绝启动：ERAHERM_HOST={host!r} 可被其它机器访问，但 ERAHERM_API_TOKEN "
        "未设置（或仍是占位值），任何能访问该端口的人都能读写全部记忆。\n"
        "三选一：\n"
        "  1) 设置一个真实密钥：ERAHERM_API_TOKEN=<强随机串>\n"
        "  2) 只在本机使用：ERAHERM_HOST=127.0.0.1\n"
        "  3) 确实要无认证公网暴露（不推荐）：ERAHERM_ALLOW_INSECURE_PUBLIC=true"
    )
    if not token_is_configured(admin_token):
        hint += (
            "\n（另外 ERAHERM_ADMIN_TOKEN 也未配置，/v1/admin/* 将一律返回 503。）"
        )
    return hint


def safe_filename(name: str | None, *, fallback: str = "unnamed", max_length: int = 64) -> str:
    """把任意字符串收敛成一个安全的**单层**文件名片段。

    - 路径分隔符（``/`` ``\\``）、控制字符、``..`` 全部被中和
    - 前导/尾随的点与下划线被剥掉，所以 ``.`` / ``..`` / ``...`` 都不会漏出去
    - 空结果回落到 ``fallback``
    """
    cleaned = _UNSAFE_NAME_CHARS.sub("_", (name or "").strip())
    cleaned = cleaned.strip("._")
    cleaned = cleaned[:max_length].strip("._")
    if not cleaned:
        return fallback
    return cleaned


def resolve_within(root: Path, *parts: str) -> Path:
    """在 ``root`` 之下解析 ``parts``，越界即抛 ``ValueError``。

    安全底线（不是可选项）：绝对路径、带盘符的路径（``C:foo``）、UNC 路径、
    以及解析后逃出 ``root`` 的 ``..`` 组合，全部拒绝。
    """
    root_resolved = Path(root).resolve()
    for part in parts:
        candidate = Path(part)
        if candidate.is_absolute() or candidate.drive or candidate.root:
            raise ValueError(f"unsafe path component (absolute or drive-qualified): {part!r}")
    if not any(p for p in parts):
        raise ValueError("empty relative path")
    target = root_resolved.joinpath(*parts).resolve()
    if target != root_resolved and not target.is_relative_to(root_resolved):
        raise ValueError(f"path escapes archive root: {target} is not under {root_resolved}")
    return target
