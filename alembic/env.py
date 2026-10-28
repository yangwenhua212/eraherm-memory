# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Import all table models so metadata is complete.
from app.adapters.sqlite_vector_store import EmbeddingRow  # noqa: F401
from app.models import (  # noqa: F401
    EntityRow,
    FeedbackEventRow,
    L3ArchiveRow,
    MemoryRow,
    ReflectionRecordRow,
    RelationRow,
    SessionRow,
)

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False 是必须的，不是可选风格：
    # fileConfig 默认会**禁用进程里已存在的所有 logger**（不在 ini 里列出的那些）。
    # 本项目是「可嵌入内核」：宿主程序一旦以编程方式跑 `alembic upgrade`，
    # 就会在那一刻把宿主自己的日志（以及我们自己的 "eraherm" logger）全部静默关掉，
    # 表现是"之后再也打不出任何日志"。
    # 这条缺陷是跑全量测试时暴露的：test_migration_schema 跑在 test_proclock 之前，
    # 于是后者的 caplog 什么都收不到（单跑该文件却正常）。
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = SQLModel.metadata

db_url = os.getenv("ERAHERM_DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
