# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""跨进程建议锁（cross-process advisory lock）：用独占创建的锁文件实现互斥。

存在原因
--------
``ERAHERM_CONSOLIDATION_ENABLED=true`` 时，**每个 uvicorn worker 都会各自启动** APScheduler
任务；2 个 worker 下夜间整理（consolidation）会并发跑两遍，破坏性步骤（冲突软删除、
压缩时删除原文）于是重复执行 / 竞态。这里给出一个极廉价的跨进程互斥，让同一台机器上
的多个 worker 只有一个能进入临界区。

依赖：**仅标准库**（``os`` / ``json`` / ``socket`` / ``time`` / ``uuid`` / ``datetime`` /
``pathlib``）。日志复用 ``app.observability.logging``，该模块只用到 ``logging`` + ``json``，
因此 import 本模块**不会**牵出 sqlmodel / 数据库，可在无数据库环境下单独使用与测试。

保证（guarantees）
------------------
* ``try_acquire()`` 用 ``os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)`` 原子创建锁
  文件，同一时刻只有一个调用者能创建成功并拿到 ``True``。
* 锁文件里写入少量 JSON（``pid`` / ``acquired_at`` / ``host`` / ``token``），flush + fsync
  后才算持有，方便运维排查“谁占着锁”。
* 陈旧锁（mtime 早于 ``stale_after_seconds``，或内容不可解析 / 不是 JSON 对象）会被接管
  （unlink + 重试一次独占创建），因此进程崩溃残留的锁文件不会永久堵死整理任务。
* ``release()`` 永不抛异常；且只会删除**仍然属于本实例**的锁文件（token 比对），别人
  接管后的锁不会被误删。

非保证（non-guarantees，必须一起写进使用文档）
---------------------------------------------
* **建议性（advisory）**：它只协调“调用它”的代码。任何不调用本类的进程照样能改同一份数据。
* **不适合 NFS / 网络文件系统 / 跨主机共享卷**：那里的 ``O_EXCL`` 与 mtime 语义不保证原子，
  可能出现双持有或错误抢占。本类只面向本机本地文件系统。
* **不是硬实时，极端情况下可能短暂双持有**：进程 A 卡在临界区超过 ``stale_after_seconds``
  时，B 会认领（接管）这把锁，而 A 仍会继续跑完。所以 ``stale_after_seconds`` 必须**显著
  大于**临界区的最长耗时。
* **崩溃后残留**：持有者被 kill -9 不会执行 ``release()``，只能靠陈旧超时回收。
* ``O_EXCL`` 在 Windows 上对**本地文件系统**是原子的（实测同一进程内二次打开同一路径也会
  得到 ``FileExistsError``）；跨网络路径不作保证。
* **不做可重入计数**：同一实例重复 ``try_acquire()`` 幂等返回 ``True``；但同一进程内两个
  实例互不识别为“自己人”，第二个实例会失败（这是刻意的，便于测试与模拟多 worker）。
* 锁文件路径所在目录必须已存在（本类不创建目录）。

用法（整理任务里）
------------------
    lock = ProcessLock(data_dir / "consolidation.lock", stale_after_seconds=21600)
    if not lock.try_acquire():
        logger.info("另一个 worker 正在整理，本次跳过")
        return
    try:
        run_consolidation()
    finally:
        lock.release()
"""

from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.observability.logging import logger

__all__ = ["ProcessLock"]

# acquire() 未显式给 poll_seconds 时的轮询间隔（秒）
_DEFAULT_POLL_SECONDS = 0.1


def _unlink_quietly(path: Path, *, context: str) -> None:
    """删除锁文件且永不抛异常（文件不存在是正常情况）。"""
    try:
        path.unlink()
    except FileNotFoundError:
        # 已经不是我们的文件了，无需处理
        pass
    except OSError as exc:
        # JSON formatter 只输出 extra 白名单里的键，所以关键信息必须写进消息文本
        logger.debug("ProcessLock 删除锁文件失败（%s, path=%s）：%s", context, path, exc)


class ProcessLock:
    """基于独占创建文件的跨进程建议锁（详见模块 docstring）。"""

    def __init__(
        self,
        path: str | Path,
        *,
        stale_after_seconds: float = 21600,
        poll_seconds: float = 0.0,
    ) -> None:
        """创建一个锁对象（**不**获取锁；获取请调用 try_acquire / acquire / with）。

        参数：
        * ``path``：锁文件路径，所在目录必须已存在。
        * ``stale_after_seconds``：mtime 比“现在”早于该秒数即视为陈旧、可被接管。应显著大于
          临界区最长耗时（默认 21600 = 6 小时）。注意 ``0`` 或负数会让任何已存在的锁都被判为
          陈旧（本类不做额外校验），不要那样用。
        * ``poll_seconds``：``acquire(timeout)`` 的轮询间隔；``0`` 表示用默认 0.1 秒。
        """
        self._path = Path(path)
        self._stale_after_seconds = float(stale_after_seconds)
        self._poll_seconds = float(poll_seconds)
        # 每次实例化生成唯一 token：用于 release 时确认锁文件仍是“自己写的那一份”，
        # 避免把别的进程接管后的锁删掉。
        self._token = uuid4().hex
        self._held = False

    # ------------------------------------------------------------------ 属性

    @property
    def path(self) -> Path:
        """锁文件路径。"""
        return self._path

    @property
    def acquired(self) -> bool:
        """本实例当前是否持有这把锁（仅表示本实例的状态，不代表 OS 层面的独占）。"""
        return self._held

    def __repr__(self) -> str:  # pragma: no cover - 仅供调试输出
        return f"ProcessLock(path={str(self._path)!r}, held={self._held})"

    # ------------------------------------------------------------ 获取 / 释放

    def try_acquire(self) -> bool:
        """尝试非阻塞地获取锁；成功返回 ``True``，被别人持有返回 ``False``。

        若锁文件已存在但属于**陈旧**（mtime 超过 ``stale_after_seconds``，或内容不可解析 /
        不是 JSON 对象），则接管：删除后重试一次独占创建。
        """
        if self._held:
            # 幂等：已经持有就直接成功
            return True

        if self._create_exclusive():
            self._held = True
            return True

        if not self._is_stale():
            logger.debug("ProcessLock 锁已被其他进程持有，放弃获取（path=%s）", self._path)
            return False

        # 陈旧或损坏：接管。warning 级别，因为这是异常路径，值得在日志里留痕。
        logger.warning(
            "ProcessLock 发现陈旧或损坏的锁文件并接管（path=%s, stale_after_seconds=%s）",
            self._path,
            self._stale_after_seconds,
        )
        _unlink_quietly(self._path, context="stale-takeover")

        # 只重试一次：unlink 之后仍可能被别的进程抢先创建。
        if self._create_exclusive():
            self._held = True
            return True

        logger.warning("ProcessLock 接管锁文件失败，可能已被其他进程抢先（path=%s）", self._path)
        return False

    def acquire(self, timeout: float = 0.0) -> bool:
        """在 ``timeout`` 秒内轮询尝试获取锁；拿到返回 ``True``，超时返回 ``False``。

        ``timeout=0`` 等价于只尝试一次（即 ``try_acquire()``）。轮询间隔取
        ``poll_seconds``，为 0 时用 0.1 秒。
        """
        interval = self._poll_seconds or _DEFAULT_POLL_SECONDS
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            if self.try_acquire():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(interval, remaining))

    def release(self) -> None:
        """释放锁；**永不抛异常**。

        只释放“本实例确实获取过”的锁（``self._held``）：从未获取就调用是 no-op，因此不会
        误删别人的锁文件。此外还会比对锁文件里的 ``token``——若文件已被其他进程接管
        （内容不是我们写的那一份），则同样不删除，交由陈旧超时回收。
        """
        if not self._held:
            # 从未持有：绝不能删除锁文件（可能是别人的锁）
            return

        # 逻辑上已经不再持有（无论下面是否删除文件）
        self._held = False

        payload = self._read_payload()
        if payload is not None and payload.get("token") != self._token:
            logger.debug("ProcessLock 锁已被其他进程接管，release 不删除该文件（path=%s）", self._path)
            return

        _unlink_quietly(self._path, context="release")

    # -------------------------------------------------------------- 上下文管理

    def __enter__(self) -> "ProcessLock":
        """获取锁；拿不到则抛 ``TimeoutError``（不支持的调用方请直接用 ``try_acquire``）。"""
        if not self.try_acquire():
            raise TimeoutError(f"ProcessLock 无法获取锁，已被其他进程持有：{self._path}")
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        """退出时释放锁（包括发生异常时）；不吞掉异常。"""
        self.release()
        return False

    # ---------------------------------------------------------------- 内部实现

    def _create_exclusive(self) -> bool:
        """用 O_CREAT|O_EXCL 原子创建锁文件并写入 payload；成功返回 True。"""
        payload = {
            "pid": os.getpid(),
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "host": socket.gethostname(),
            "token": self._token,
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # Windows 上 os.open 默认是文本模式，显式加 O_BINARY（其它平台没有该标志）
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)

        try:
            fd = os.open(self._path, flags, 0o644)
        except FileExistsError:
            # 已被别人独占创建 —— 正常的竞争失败
            return False
        except OSError as exc:
            logger.warning("ProcessLock 创建锁文件失败（path=%s）：%s", self._path, exc)
            return False

        try:
            try:
                written = os.write(fd, raw)
                if written != len(raw):
                    raise OSError(f"short write: {written}/{len(raw)}")
                os.fsync(fd)
            finally:
                # 先关闭 fd 再考虑删除：Windows 上删除仍打开的文件会被拒绝
                os.close(fd)
        except OSError as exc:
            logger.warning("ProcessLock 写入锁文件失败，回滚（path=%s）：%s", self._path, exc)
            _unlink_quietly(self._path, context="write-failed")
            return False

        return True

    def _read_payload(self) -> dict | None:
        """读取锁文件里的 JSON 对象；文件不存在 / 不可读 / 不是 JSON 对象时返回 None。"""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def _is_stale(self) -> bool:
        """判断已存在的锁文件是否陈旧（mtime 过老，或内容损坏）。"""
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            # 文件刚被别的进程删掉了：当作“可以做一次独占创建试试”
            return True

        if time.time() - mtime > self._stale_after_seconds:
            return True

        # 内容读不出来 / 不是 JSON 对象 —— 视为垃圾内容，按陈旧处理
        return self._read_payload() is None
