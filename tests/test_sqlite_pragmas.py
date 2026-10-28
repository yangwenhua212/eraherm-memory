# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""SQLite 引擎必须带上 WAL / busy_timeout 等 pragma。

以前 `create_engine` 只设了 `check_same_thread`，默认 rollback journal 模式下
写事务会锁住整个库文件（连读都阻塞），并发下直接 `database is locked`。
本测试只依赖 SQLAlchemy，不需要 sqlmodel。

注意：这里不用 pytest 的 ``tmp_path``（它依赖 pytest 自身的 tmp 目录机制），
而是显式挑一个可写目录，便于在受限环境里也能跑。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from app.db import BUSY_TIMEOUT_MS, create_sqlite_engine


def _db_file() -> Path:
    base = Path(os.environ.get("ERAHERM_TEST_TMP") or tempfile.gettempdir())
    return base / f"eraherm-pragma-{uuid4().hex}.db"


def _pragma(engine, name: str):
    with engine.connect() as conn:
        return conn.execute(text(f"PRAGMA {name}")).scalar()


def test_sqlite_engine_enables_wal_and_busy_timeout() -> None:
    db = _db_file()
    engine = create_sqlite_engine(f"sqlite:///{db.as_posix()}")
    try:
        assert str(_pragma(engine, "journal_mode")).lower() == "wal"
        assert int(_pragma(engine, "busy_timeout")) == BUSY_TIMEOUT_MS
        assert int(_pragma(engine, "foreign_keys")) == 1
    finally:
        engine.dispose()
        db.unlink(missing_ok=True)


def test_pragmas_apply_to_every_pooled_connection() -> None:
    """pragma 要挂在 connect 事件上，不能只对新连接设一次。"""
    db = _db_file()
    engine = create_sqlite_engine(f"sqlite:///{db.as_posix()}")
    try:
        with engine.connect() as c1:
            c1.execute(text("SELECT 1"))
        with engine.connect() as c2:
            assert str(c2.execute(text("PRAGMA journal_mode")).scalar()).lower() == "wal"
            assert int(c2.execute(text("PRAGMA busy_timeout")).scalar()) == BUSY_TIMEOUT_MS
    finally:
        engine.dispose()
        db.unlink(missing_ok=True)


def test_in_memory_sqlite_still_gets_busy_timeout() -> None:
    """内存库不支持 WAL，但其它 pragma 仍应生效。"""
    engine = create_sqlite_engine("sqlite://")
    try:
        assert engine.dialect.name == "sqlite"
        assert int(_pragma(engine, "busy_timeout")) == BUSY_TIMEOUT_MS
        assert int(_pragma(engine, "foreign_keys")) == 1
    finally:
        engine.dispose()
