"""EraHerm-Memory provider — Hermes 长期记忆层（官方 MemoryProvider 实现）。

Implements the full Hermes MemoryProvider ABC:

  prefetch()         每轮自动召回相关记忆注入上下文（后台预热 + 前台取缓存）
  sync_turn()        每轮后台把对话沉淀为 episode 记忆（启发式防噪声）
  on_session_end()   会话结束时触发 consolidate 整理压缩（需 admin token）
  on_memory_write()  内置 MEMORY.md / user profile 写入时镜像到 EraHerm
  on_pre_compress()  压缩前把即将丢弃的消息提炼为记忆
  get_tool_schemas() eraherm_remember / eraherm_recall 原生工具
  get_config_schema()/save_config()  支持 `hermes memory setup`

No pip dependencies. Only requires the EraHerm service to be up.

配置（.env）:
  ERAHERM_URL              服务地址，默认 http://127.0.0.1:8000
  ERAHERM_MEMORY_USER      记忆归属 user_id，默认 hermes-user（部署时按需配置）
  ERAHERM_MEMORY_TOP_K     预取条数，默认 6
  ERAHERM_MEMORY_MIN_SCORE 召回门禁，默认 0.25
  ERAHERM_ADMIN_TOKEN      整理压缩用 admin token（on_session_end 可选）
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

# 默认配置 — .env 可覆盖
_ERAHERM_URL = os.getenv("ERAHERM_URL", "http://127.0.0.1:8000")
_ERAHERM_USER = os.getenv("ERAHERM_MEMORY_USER", "hermes-user")
_ERAHERM_TOP_K = int(os.getenv("ERAHERM_MEMORY_TOP_K", "6"))
_ERAHERM_MIN_SCORE = float(os.getenv("ERAHERM_MEMORY_MIN_SCORE", "0.25"))
_ERAHERM_ADMIN_TOKEN = os.getenv("ERAHERM_ADMIN_TOKEN", "")

# 断路器：连续失败 N 次后暂停一段时间，避免服务挂掉时疯狂重试
_BREAKER_THRESHOLD = 5
_BREAKER_COOLDOWN_SECS = 120

# 启发式：什么值得从对话里沉淀（对齐 bridge 的 _maybe_extract_memory）
_FACT_HINTS = re.compile(
    r"(我(们)?(用|是|叫|偏好|喜欢|在|做)|项目|技术栈|数据库|依赖|"
    r"不要|禁止|记住|以后都|请记住|目标是|计划|打算|决定|改为|换成)",
    re.I,
)
_IDENTITY_HINTS = re.compile(r"(我叫|用户名|我的名字|称呼我|是.{0,6}(开发|工程师|学生))", re.I)


class EraHermMemoryProvider(MemoryProvider):
    """Full-lifecycle EraHerm provider: prefetch + sync + session-end consolidate."""

    def __init__(self) -> None:
        self._session_id: str = ""
        self._prefetch_result: str = ""
        self._prefetch_lock = threading.Lock()
        self._prefetch_thread: Optional[threading.Thread] = None
        self._sync_thread: Optional[threading.Thread] = None
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0

    # -- Identity --------------------------------------------------------

    @property
    def name(self) -> str:
        return "eraherm"

    # -- Availability ----------------------------------------------------

    def is_available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{_ERAHERM_URL}/v1/health", timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    # -- Lifecycle -------------------------------------------------------

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id or ""
        # user_id 必须稳定（HERMES_INTEGRATION.md §3）：EraHerm 记忆挂在
        # 固定 user_id 下（默认 hermes-user），绝不随平台用户 id 变化——
        # 换 user_id 永远召不回历史记忆。多用户隔离走身份层/多实例。
        self._user_id = _ERAHERM_USER
        logger.info(
            "eraherm provider initialized (session=%s, user=%s)",
            session_id, self._user_id,
        )

    def shutdown(self) -> None:
        for t in (self._prefetch_thread, self._sync_thread):
            if t and t.is_alive():
                t.join(timeout=5.0)
        self._prefetch_thread = None
        self._sync_thread = None

    # -- System prompt ---------------------------------------------------

    def system_prompt_block(self) -> str:
        return (
            "# EraHerm Memory\n"
            "Active (auto-inject). Relevant memories from your long-term "
            "kernel are injected before each turn — you don't need to call "
            "recall for them. If you need deeper recall, use the "
            "mcp_eraherm_memory_recall tool."
        )

    # -- Circuit breaker --------------------------------------------------

    def _is_breaker_open(self) -> bool:
        if self._consecutive_failures < _BREAKER_THRESHOLD:
            return False
        if time.monotonic() >= self._breaker_open_until:
            self._consecutive_failures = 0
            return False
        return True

    def _record_success(self) -> None:
        self._consecutive_failures = 0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= _BREAKER_THRESHOLD:
            self._breaker_open_until = time.monotonic() + _BREAKER_COOLDOWN_SECS
            logger.warning(
                "EraHerm circuit breaker tripped after %d consecutive failures. "
                "Pausing for %ds.", _BREAKER_THRESHOLD, _BREAKER_COOLDOWN_SECS,
            )

    # -- Prefetch（每轮自动注入）-----------------------------------------

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """取上一轮 queue 的缓存；没有缓存才同步查一次（首轮兜底）。"""
        with self._prefetch_lock:
            result = self._prefetch_result
            self._prefetch_result = ""
        if result:
            return result
        if not query or not query.strip() or len(query.strip()) <= 2:
            return ""
        if self._is_breaker_open():
            return ""
        items = self._recall(query)
        if not items:
            return ""
        lines = [f"- {m}" for m in items]
        block = "## EraHerm 相关记忆（自动注入）\n" + "\n".join(lines)
        logger.info(
            "eraherm prefetch: injected %d memory items (query=%r)",
            len(items), query[:50],
        )
        return block

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """后台预热下一轮的召回结果，不阻塞 turn。"""
        if not query or not query.strip() or len(query.strip()) <= 2:
            return
        if self._is_breaker_open():
            return

        def _run() -> None:
            try:
                items = self._recall(query)
                if items:
                    block = "## EraHerm 相关记忆（自动注入）\n" + "\n".join(
                        f"- {m}" for m in items
                    )
                    with self._prefetch_lock:
                        self._prefetch_result = block
                    logger.info(
                        "eraherm queue_prefetch: warmed %d items (query=%r)",
                        len(items), query[:50],
                    )
                self._record_success()
            except Exception as e:
                self._record_failure()
                logger.debug("eraherm queue_prefetch failed (non-fatal): %s", e)

        self._prefetch_thread = threading.Thread(
            target=_run, daemon=True, name="eraherm-prefetch"
        )
        self._prefetch_thread.start()

    # -- Sync（每轮后台沉淀）---------------------------------------------

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """每轮把「值得记住」的用户表述沉淀为 episode 记忆（启发式防噪声）。

        纯闲聊 / 短消息 / 无事实信号 → 不写入，避免记忆库膨胀。
        """
        if self._is_breaker_open():
            return
        text = (user_content or "").strip()
        if len(text) < 6 or not (_FACT_HINTS.search(text) or _IDENTITY_HINTS.search(text)):
            return

        def _run() -> None:
            try:
                pinned = bool(_IDENTITY_HINTS.search(text))
                payload = json.dumps({
                    "user_id": self._user_id,
                    "content": text,
                    "memory_type": "identity" if pinned else "episode",
                    "importance": 0.95 if pinned else 0.6,
                    "pinned": pinned,
                    "extract_graph": True,
                    "session_id": session_id or self._session_id,
                    "meta": {"host": "hermes", "via": "memory_provider.sync_turn"},
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{_ERAHERM_URL}/v1/memories",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                logger.info(
                    "eraherm sync_turn: stored %s (id=%s)",
                    "pinned" if pinned else "episode", data.get("id", "?"),
                )
                self._record_success()
            except Exception as e:
                self._record_failure()
                logger.debug("eraherm sync_turn failed (non-fatal): %s", e)

        self._sync_thread = threading.Thread(
            target=_run, daemon=True, name="eraherm-sync"
        )
        self._sync_thread.start()

    # -- Session end（整理压缩）--------------------------------------------

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """会话结束时触发 EraHerm consolidate（需 ERAHERM_ADMIN_TOKEN）。

        无 token 时跳过（只记日志），不阻塞会话关闭。
        """
        if not _ERAHERM_ADMIN_TOKEN:
            logger.info("eraherm on_session_end: no admin token, skip consolidate")
            return
        if self._is_breaker_open():
            return

        def _run() -> None:
            try:
                payload = json.dumps({"user_id": self._user_id}).encode("utf-8")
                req = urllib.request.Request(
                    f"{_ERAHERM_URL}/v1/admin/consolidate",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Admin-Token": _ERAHERM_ADMIN_TOKEN,
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                reports = len(data.get("reports", []))
                logger.info("eraherm on_session_end: consolidate done (%d reports)", reports)
                self._record_success()
            except Exception as e:
                self._record_failure()
                logger.debug("eraherm on_session_end consolidate failed: %s", e)

        threading.Thread(target=_run, daemon=True, name="eraherm-consolidate").start()

    # -- Pre-compress（压缩前提炼）-----------------------------------------

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """把即将被压缩丢弃的用户消息中值得记的事实提炼为记忆。"""
        if self._is_breaker_open():
            return ""
        candidates = []
        for m in (messages or []):
            if not isinstance(m, dict):
                continue
            if m.get("role") != "user":
                continue
            text = str(m.get("content", "") or "").strip()
            if len(text) >= 6 and (_FACT_HINTS.search(text) or _IDENTITY_HINTS.search(text)):
                candidates.append(text)
        if not candidates:
            return ""
        # 去重后返回给压缩器，并后台写入 EraHerm
        seen: set[str] = set()
        uniq: list[str] = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                uniq.append(c)
        self.sync_turn(uniq[0], "", messages=messages)
        return "EraHerm memory notes: " + " | ".join(uniq[:5])

    # -- Tools ------------------------------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "eraherm_remember",
                "description": "Store a durable fact into EraHerm-Memory (long-term kernel).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Fact to store"},
                        "importance": {
                            "type": "number",
                            "description": "0..1 importance",
                            "default": 0.8,
                        },
                        "pinned": {
                            "type": "boolean",
                            "description": "Pin so it always ranks first",
                            "default": False,
                        },
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "eraherm_recall",
                "description": "Semantic recall from EraHerm-Memory (long-term kernel).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "default": 5},
                        "min_score": {"type": "number", "default": 0.25},
                    },
                    "required": ["query"],
                },
            },
        ]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if self._is_breaker_open():
            return json.dumps({
                "ok": False,
                "error": "EraHerm temporarily unavailable (multiple consecutive failures). Will retry automatically.",
            }, ensure_ascii=False)
        if tool_name == "eraherm_remember":
            content = str(args.get("content", "")).strip()
            if not content:
                return json.dumps({"ok": False, "error": "content required"}, ensure_ascii=False)
            importance = float(args.get("importance", 0.8))
            pinned = bool(args.get("pinned", False))
            ok, msg = self._remember(content, importance, pinned)
            return json.dumps({"ok": ok, "message": msg}, ensure_ascii=False)
        if tool_name == "eraherm_recall":
            q = str(args.get("query", "")).strip()
            top_k = int(args.get("top_k", 5))
            min_score = float(args.get("min_score", _ERAHERM_MIN_SCORE))
            items = self._recall(q, top_k=top_k, min_score=min_score)
            return json.dumps({"ok": True, "count": len(items), "items": items}, ensure_ascii=False)
        return json.dumps({"ok": False, "error": f"unknown tool {tool_name}"}, ensure_ascii=False)

    # -- Built-in memory mirror（内置 MEMORY.md 变更镜像）-------------------

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """内置 memory/user profile 写入时镜像到 EraHerm。

        add/replace → 写入一条带来源标记的记忆；remove 在 EraHerm 侧
        没有对应删除语义，仅记日志（EraHerm 以 pinned/consolidate 处理淘汰）。
        """
        if action == "remove":
            logger.info("eraherm on_memory_write: remove ignored (target=%s)", target)
            return
        if not content or not content.strip():
            return
        if self._is_breaker_open():
            return
        text = content.strip()
        # 镜像记忆内容 = 内置条目 + 来源元数据（避免混淆为独立事实）
        meta = dict(metadata or {})
        origin = meta.get("write_origin") or meta.get("tool_name") or "builtin"
        mirror = f"[mirrored from Hermes {target} via {origin}] {text}"

        def _run() -> None:
            try:
                payload = json.dumps({
                    "user_id": self._user_id,
                    "content": mirror,
                    "memory_type": "fact",
                    "importance": 0.7,
                    "pinned": False,
                    "extract_graph": False,
                    "session_id": meta.get("session_id") or self._session_id,
                    "meta": {"host": "hermes", "via": "memory_provider.on_memory_write", "action": action, "target": target},
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{_ERAHERM_URL}/v1/memories",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                logger.info(
                    "eraherm on_memory_write: mirrored %s/%s (id=%s)",
                    action, target, data.get("id", "?"),
                )
                self._record_success()
            except Exception as e:
                self._record_failure()
                logger.debug("eraherm on_memory_write failed (non-fatal): %s", e)

        threading.Thread(target=_run, daemon=True, name="eraherm-mirror").start()

    # -- Config schema（`hermes memory setup` 支持）-------------------------

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {"key": "base_url", "description": "EraHerm-Memory service URL", "default": "http://127.0.0.1:8000", "env_var": "ERAHERM_URL"},
            {"key": "user_id", "description": "Memory owner user_id", "default": "hermes-user", "env_var": "ERAHERM_MEMORY_USER"},
            {"key": "top_k", "description": "Prefetch item count", "default": "6", "env_var": "ERAHERM_MEMORY_TOP_K"},
            {"key": "min_score", "description": "Recall minimum score", "default": "0.25", "env_var": "ERAHERM_MEMORY_MIN_SCORE"},
            {"key": "admin_token", "description": "Admin token for session-end consolidate (optional)", "secret": True, "env_var": "ERAHERM_ADMIN_TOKEN"},
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        # 全部走 env vars（get_config_schema 已标 env_var），无独立配置文件
        pass

    # -- Internals --------------------------------------------------------

    def _recall(self, query: str, top_k: int = 0, min_score: float = 0.0) -> List[str]:
        top_k = top_k or _ERAHERM_TOP_K
        # min_score 显式传 0 表示关闭门禁；None/0.0 未传时用默认值
        if min_score is None:
            min_score = _ERAHERM_MIN_SCORE
        payload = json.dumps({
            "user_id": self._user_id,
            "query": query,
            "top_k": top_k,
            "min_score": min_score,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{_ERAHERM_URL}/v1/recall",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self._record_success()
        except Exception as e:
            self._record_failure()
            logger.debug("eraherm recall failed: %s", e)
            return []
        items = data.get("items", []) or []
        return [f"[{i.get('score', 0):.2f}] {i.get('content', '')}" for i in items]

    def _remember(self, content: str, importance: float, pinned: bool) -> tuple:
        payload = json.dumps({
            "user_id": self._user_id,
            "content": content,
            "importance": importance,
            "pinned": pinned,
            "extract_graph": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{_ERAHERM_URL}/v1/memories",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self._record_success()
            return True, str(data.get("id", "stored"))
        except Exception as e:
            self._record_failure()
            logger.debug("eraherm remember failed: %s", e)
            return False, str(e)


def register(ctx) -> None:
    """Plugin entry point — called by the loader with a collector ctx."""
    try:
        ctx.register_memory_provider(EraHermMemoryProvider())
    except Exception as e:
        logger.warning("eraherm provider register failed: %s", e)
