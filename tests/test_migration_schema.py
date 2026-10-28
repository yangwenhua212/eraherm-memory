# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""迁移 × 模型的 schema 漂移守卫。

背景：``alembic/versions/0001_initial_schema.py`` 的 ``upgrade()`` 直接调用了
``SQLModel.metadata.create_all()`` —— 也就是「用当前模型建历史表」。后果是
**迁移路径实际上没有被验证过**：改了模型不会产生迁移，而 ``alembic upgrade head``
永远"成功"。这个测试就是那条缺掉的验证：跑一次迁移，把得到的表结构与当前模型
逐列比对。

需要 alembic + sqlmodel，本机/CI 缺失时自动 skip（不伪装成通过）。
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("alembic", reason="alembic 未安装：迁移漂移检查需要它")
pytest.importorskip("sqlmodel", reason="sqlmodel 未安装")

from sqlalchemy import create_engine, inspect  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402


def _db_file() -> Path:
    base = Path(os.environ.get("ERAHERM_TEST_TMP") or tempfile.gettempdir())
    return base / f"eraherm-migrate-{uuid4().hex}.db"


def _alembic_available() -> bool:
    return importlib.util.find_spec("alembic") is not None


def test_migrations_produce_the_current_model_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic import command
    from alembic.config import Config

    # 确保所有表都注册进 metadata
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

    db = _db_file()
    url = f"sqlite:///{db.as_posix()}"
    # 必须同时设环境变量：alembic/env.py:31-33 里 ERAHERM_DATABASE_URL **优先于**
    # Config 的 sqlalchemy.url。只设 Config 的话，本机一旦存在该环境变量，迁移就会
    # 打到别的库上、这个测试的库始终是空的（第一版正是这么挂的）。
    # 既有测试 tests/test_phase5.py::test_alembic_upgrade 用的就是 monkeypatch.setenv。
    monkeypatch.setenv("ERAHERM_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    try:
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        try:
            inspector = inspect(engine)
            migrated_tables = set(inspector.get_table_names())
            model_tables = set(SQLModel.metadata.tables)
            missing = model_tables - migrated_tables
            assert not missing, (
                f"迁移后缺少这些表：{sorted(missing)} —— "
                "说明有新模型没有对应的 alembic revision"
            )
            for table in sorted(model_tables):
                migrated_cols = {c["name"] for c in inspector.get_columns(table)}
                model_cols = {c.name for c in SQLModel.metadata.tables[table].columns}
                assert model_cols <= migrated_cols, (
                    f"表 {table} 缺少列 {sorted(model_cols - migrated_cols)} —— "
                    "改了模型但没有写迁移（或 0001 的 create_all 掩盖了它）"
                )
        finally:
            engine.dispose()
    finally:
        db.unlink(missing_ok=True)
