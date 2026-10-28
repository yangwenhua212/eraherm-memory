# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""``app.proclock.ProcessLock`` 单元测试。

沙箱限制说明：本环境**无法创建 / 枚举新目录**，pytest 的 ``tmp_path`` / ``tmpdir`` 会直接失败。
因此这里只在 ``ERAHERM_TEST_TMP``（或系统临时目录）下创建**单个文件**，并在 teardown 里
``unlink(missing_ok=True)``；不 list、不 rmtree 目录。

未覆盖：真正的多进程互斥（需要 subprocess/多进程，本沙箱内不予验证）。同进程内用第二个实例
模拟“另一个进程”，见 ``test_second_instance_cannot_acquire`` 里的说明。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import pytest

from app.proclock import ProcessLock

# 沙箱里不能建目录，只能往已存在的目录里放文件
_TMP_BASE = Path(os.environ.get("ERAHERM_TEST_TMP") or tempfile.gettempdir())

# 把 mtime 推到 10^6 秒（约 11.6 天）之前，远超测试用的 stale_after_seconds=60
_ANCIENT = 10**6


@pytest.fixture()
def lock_path() -> Path:
    """每条用例一个唯一的锁文件路径；teardown 只删文件，不动目录。"""
    path = _TMP_BASE / f"eraherm-lock-{uuid4().hex}.lock"
    yield path
    path.unlink(missing_ok=True)


def _age_file(path: Path, seconds: float = _ANCIENT) -> None:
    """把文件 mtime 设到 ``seconds`` 秒之前。"""
    t = time.time() - seconds
    os.utime(path, (t, t))


# --------------------------------------------------------------------- 基本获取


def test_try_acquire_creates_file_with_payload(lock_path: Path) -> None:
    lock = ProcessLock(lock_path)

    assert lock.acquired is False
    assert lock_path.exists() is False

    assert lock.try_acquire() is True
    assert lock.acquired is True
    assert lock_path.is_file() is True

    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    assert isinstance(payload["host"], str) and payload["host"]
    assert isinstance(payload["acquired_at"], str) and payload["acquired_at"]
    assert payload["token"]

    # 已经持有：重复调用幂等返回 True
    assert lock.try_acquire() is True

    lock.release()
    assert lock.acquired is False
    assert lock_path.exists() is False


def test_release_allows_reacquire(lock_path: Path) -> None:
    lock = ProcessLock(lock_path)
    assert lock.try_acquire() is True
    lock.release()

    again = ProcessLock(lock_path)
    assert again.acquired is False
    assert again.try_acquire() is True
    again.release()

    assert lock_path.exists() is False


def test_second_instance_cannot_acquire(lock_path: Path) -> None:
    """用第二个实例模拟“另一个 worker 进程”。

    说明：Windows 上 ``os.open(path, O_CREAT|O_EXCL|O_WRONLY)`` 对**同一进程内的二次打开**
    同样会失败并抛 ``FileExistsError``（已实测），所以这里不需要为“同进程”做任何特殊适配。
    但这只能证明文件级独占，**不能**替代真正的多进程验证。
    """
    first = ProcessLock(lock_path)
    second = ProcessLock(lock_path)

    assert first.try_acquire() is True
    assert second.try_acquire() is False
    assert second.acquired is False

    # 竞争失败者的 release 必须是 no-op：不能删掉别人的锁文件
    second.release()
    assert lock_path.exists() is True
    assert first.acquired is True

    first.release()
    assert lock_path.exists() is False


def test_fresh_lock_is_not_stolen(lock_path: Path) -> None:
    holder = ProcessLock(lock_path, stale_after_seconds=60)
    assert holder.try_acquire() is True

    other = ProcessLock(lock_path, stale_after_seconds=60)
    assert other.try_acquire() is False
    # 原文件未被改动
    assert json.loads(lock_path.read_text(encoding="utf-8"))["pid"] == os.getpid()


# --------------------------------------------------------------------- 陈旧接管


def test_stale_lock_is_taken_over_by_mtime(lock_path: Path) -> None:
    holder = ProcessLock(lock_path)
    assert holder.try_acquire() is True

    _age_file(lock_path)

    fresh = ProcessLock(lock_path, stale_after_seconds=60)
    assert fresh.try_acquire() is True
    assert fresh.acquired is True

    # 接管后锁文件属于新持有者：第三个实例拿不到
    third = ProcessLock(lock_path, stale_after_seconds=60)
    assert third.try_acquire() is False

    fresh.release()
    assert lock_path.exists() is False


def test_release_after_takeover_does_not_delete_new_owner(lock_path: Path) -> None:
    """老持有者失去锁之后再 release，不得删掉新持有者的锁文件。"""
    first = ProcessLock(lock_path, stale_after_seconds=60)
    assert first.try_acquire() is True

    _age_file(lock_path)

    second = ProcessLock(lock_path, stale_after_seconds=60)
    assert second.try_acquire() is True

    first.release()  # 危险动作：必须被 token 比对拦住
    assert lock_path.exists() is True

    third = ProcessLock(lock_path, stale_after_seconds=60)
    assert third.try_acquire() is False

    second.release()
    assert lock_path.exists() is False


@pytest.mark.parametrize("content", ["这不是 JSON {", "", "null", "[1, 2, 3]", "12345"])
def test_garbage_content_is_treated_as_stale(lock_path: Path, content: str) -> None:
    lock_path.write_text(content, encoding="utf-8")  # mtime 是“现在”，只能靠内容判定

    lock = ProcessLock(lock_path, stale_after_seconds=21600)
    assert lock.try_acquire() is True
    assert lock.acquired is True

    lock.release()
    assert lock_path.exists() is False


def test_stale_takeover_logs_warning(lock_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    holder = ProcessLock(lock_path)
    assert holder.try_acquire() is True
    _age_file(lock_path)

    with caplog.at_level(logging.WARNING, logger="eraherm"):
        fresh = ProcessLock(lock_path, stale_after_seconds=60)
        assert fresh.try_acquire() is True

    # 关键信息必须在消息文本里（JSON formatter 只输出 extra 白名单键）
    messages = [record.getMessage() for record in caplog.records]
    assert any("接管" in message and str(lock_path) in message for message in messages), messages


# ------------------------------------------------------------------ release 语义


def test_release_without_acquire_never_deletes_others_lock(lock_path: Path) -> None:
    owner = ProcessLock(lock_path)
    assert owner.try_acquire() is True

    intruder = ProcessLock(lock_path)
    assert intruder.acquired is False
    intruder.release()  # 从未获取：no-op

    assert lock_path.exists() is True
    assert owner.acquired is True

    owner.release()
    assert lock_path.exists() is False


def test_release_is_idempotent_and_never_raises(lock_path: Path) -> None:
    lock = ProcessLock(lock_path)
    assert lock.try_acquire() is True

    lock.release()
    lock.release()  # 第二次：文件已不存在，不能抛异常
    assert lock_path.exists() is False


# ------------------------------------------------------- acquire(timeout) / with


def test_acquire_with_timeout_polls_then_succeeds(lock_path: Path) -> None:
    holder = ProcessLock(lock_path)
    assert holder.try_acquire() is True

    waiter = ProcessLock(lock_path, poll_seconds=0.01)
    started = time.monotonic()
    assert waiter.acquire(timeout=0.2) is False
    assert time.monotonic() - started >= 0.1  # 确实等待过，而不是立刻返回

    holder.release()
    assert waiter.acquire(timeout=0.5) is True
    waiter.release()
    assert lock_path.exists() is False


def test_context_manager_raises_timeout_error_when_held(lock_path: Path) -> None:
    holder = ProcessLock(lock_path)
    assert holder.try_acquire() is True

    with pytest.raises(TimeoutError):
        with ProcessLock(lock_path):
            pytest.fail("不应进入上下文")  # pragma: no cover

    holder.release()


def test_context_manager_releases_on_exception(lock_path: Path) -> None:
    lock = ProcessLock(lock_path)
    with pytest.raises(ValueError):
        with lock:
            assert lock.acquired is True
            assert lock_path.exists() is True
            raise ValueError("boom")

    # __exit__ 在异常路径上仍然释放，并且不吞异常
    assert lock.acquired is False
    assert lock_path.exists() is False

    # 别人现在可以拿到
    other = ProcessLock(lock_path)
    assert other.try_acquire() is True
    other.release()
