# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""数据库引擎构造（单点）。

以前 ``SqliteMemoryRepository`` / ``SqliteVectorStore`` 各自 ``create_engine``，
且都只设了 ``check_same_thread``。默认 rollback journal 模式下，**写提交期间会
对整个数据库文件加排他锁，连读都被阻塞**，再加上 FastAPI 线程池并发调用，
``database is locked`` 会随并发线性上升。

这里统一打开：
- ``journal_mode=WAL``  —— 读写不再互相阻塞（单写多读并发）
- ``synchronous=NORMAL`` —— WAL 下的常规取舍，明显快于 FULL 且仍抗崩溃
- ``busy_timeout=30000`` —— 撞锁时排队等待而不是立刻报错
- ``foreign_keys=ON``   —— SQLite 默认关闭，显式打开更不容易踩坑
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

#: 撞锁等待时长（毫秒）
BUSY_TIMEOUT_MS = 30_000


def create_sqlite_engine(
    database_url: str,
    *,
    echo: bool = False,
    connect_args: dict | None = None,
) -> Engine:
    """按 URL 建引擎；SQLite 自动挂上 WAL 等 pragma，其它后端原样透传。"""
    args = dict(connect_args or {})
    if database_url.startswith("sqlite"):
        args.setdefault("check_same_thread", False)
        args.setdefault("timeout", BUSY_TIMEOUT_MS / 1000.0)
        engine = create_engine(database_url, echo=echo, connect_args=args)
        install_sqlite_pragmas(engine)
        return engine
    return create_engine(database_url, echo=echo, connect_args=args)


def install_sqlite_pragmas(engine: Engine) -> None:
    """在每次新建连接时设置 pragma（连接池会复用连接，所以必须挂在 connect 事件上）。"""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            # 内存库不支持 WAL，但执行该 pragma 不会报错（返回 "memory"）。
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
