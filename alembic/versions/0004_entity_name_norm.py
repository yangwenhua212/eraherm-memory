# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""0004 entity name_norm (indexed lookup) + backfill

Revision ID: 0004_entity_name_norm
Revises: 0003_supersede_validity_tenant
Create Date: 2026-10-09

`NetworkXSqliteGraphStore.find_entity` 以前没有任何可用索引：它把该用户的
**全部实体**取回来，在 Python 里逐个做 `_norm_name()` 比对。而
`GraphService.extract_and_ingest` 对每个抽取值都调一次 →
每次 remember 的成本是 O(抽取值 × 该用户实体总数) 的整行读取。

加 `name_norm` 列 + 索引后，常见路径变成等值查询 O(1)；
别名匹配（`aliases_json` 没有索引）仍回退全扫描，语义不变。

幂等：``0001`` 现在是显式 DDL（不含该列），但 0003 之前的库里可能已经被
旧的 ``create_all`` 建出来了，所以照旧先 inspect。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0004_entity_name_norm"
down_revision = "0003_supersede_validity_tenant"
branch_labels = None
depends_on = None

#: 与 app/adapters/networkx_graph_store.py::_norm_name 保持一致：
#: 去空白 + 小写。SQLite 的 lower() 只处理 ASCII，但 CJK 没有大小写，够用。
_BACKFILL = "UPDATE entities SET name_norm = lower(replace(replace(name, ' ', ''), char(9), '')) WHERE name_norm IS NULL"


def _columns(bind, table: str) -> set[str]:
    return {c["name"] for c in inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    return {i["name"] for i in inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _columns(bind, "entities")
    if "name_norm" not in cols:
        with op.batch_alter_table("entities") as batch:
            batch.add_column(sa.Column("name_norm", sa.String(), nullable=True))
    # 背填历史行：否则快路径对老数据永远打不中（功能不错，但性能红利拿不到）
    op.execute(_BACKFILL)
    idx = _indexes(bind, "entities")
    if "ix_entities_name_norm" not in idx:
        op.create_index("ix_entities_name_norm", "entities", ["name_norm"])
    if "ix_entities_user_name_norm" not in idx:
        op.create_index(
            "ix_entities_user_name_norm", "entities", ["user_id", "name_norm"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    idx = _indexes(bind, "entities")
    for name in ("ix_entities_user_name_norm", "ix_entities_name_norm"):
        if name in idx:
            op.drop_index(name, table_name="entities")
    if "name_norm" in _columns(bind, "entities"):
        with op.batch_alter_table("entities") as batch:
            batch.drop_column("name_norm")
