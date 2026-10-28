# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""0003 supersede chain, relation validity, embedding tenant

Revision ID: 0003_supersede_validity_tenant
Revises: 0002_access_count
Create Date: 2026-10-09

加了三组列（见 ADR 0013 与 KNOWN_ISSUES）：

- ``memories.version / superseded_by / superseded_at``：把「纠正即进化」从
  「新增一条 + 旧条 weight-0.1」升级为**显式的取代链**。
- ``relations.valid_from / valid_to``：关系的时间有效性，让图谱能表达
  「以前 A 依赖 B，现在不依赖了」。
- ``embeddings.tenant_id``：向量行上带租户，检索时**前置**过滤租户，
  而不是取回 top-k 之后再过滤（后者会让某租户的候选被其它租户挤空）。

**为什么全部写成幂等的**：``0001_initial_schema.upgrade()`` 调用了
``SQLModel.metadata.create_all()``，也就是用**当前**模型建**历史**表 ——
所以在全新库上跑 ``alembic upgrade head`` 时，这些列很可能已经被 0001 建出来了。
0002 已经用 introspection 兜底处理同一个问题，这里沿用同一套写法。
（根治办法是把 0001 改成显式 DDL 并移除运行时的 ``create_all``，属未完成的遗留项，
见 docs/KNOWN_ISSUES.md。）
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0003_supersede_validity_tenant"
down_revision = "0002_access_count"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    return {c["name"] for c in inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    return {i["name"] for i in inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()

    mem_cols = _columns(bind, "memories")
    with op.batch_alter_table("memories") as batch:
        if "version" not in mem_cols:
            batch.add_column(
                sa.Column("version", sa.Integer(), nullable=False, server_default="1")
            )
        if "superseded_by" not in mem_cols:
            batch.add_column(sa.Column("superseded_by", sa.String(), nullable=True))
        if "superseded_at" not in mem_cols:
            batch.add_column(sa.Column("superseded_at", sa.String(), nullable=True))
    mem_idx = _indexes(bind, "memories")
    if "ix_memories_superseded_by" not in mem_idx:
        op.create_index("ix_memories_superseded_by", "memories", ["superseded_by"])
    if "ix_memories_user_superseded" not in mem_idx:
        op.create_index(
            "ix_memories_user_superseded", "memories", ["user_id", "superseded_by"]
        )

    rel_cols = _columns(bind, "relations")
    with op.batch_alter_table("relations") as batch:
        if "valid_from" not in rel_cols:
            batch.add_column(sa.Column("valid_from", sa.String(), nullable=True))
        if "valid_to" not in rel_cols:
            batch.add_column(sa.Column("valid_to", sa.String(), nullable=True))
    rel_idx = _indexes(bind, "relations")
    if "ix_relations_valid_to" not in rel_idx:
        op.create_index("ix_relations_valid_to", "relations", ["valid_to"])

    emb_cols = _columns(bind, "embeddings")
    with op.batch_alter_table("embeddings") as batch:
        if "tenant_id" not in emb_cols:
            batch.add_column(sa.Column("tenant_id", sa.String(), nullable=True))
    emb_idx = _indexes(bind, "embeddings")
    if "ix_embeddings_tenant_id" not in emb_idx:
        op.create_index("ix_embeddings_tenant_id", "embeddings", ["tenant_id"])


def downgrade() -> None:
    bind = op.get_bind()

    emb_idx = _indexes(bind, "embeddings")
    if "ix_embeddings_tenant_id" in emb_idx:
        op.drop_index("ix_embeddings_tenant_id", table_name="embeddings")
    if "tenant_id" in _columns(bind, "embeddings"):
        with op.batch_alter_table("embeddings") as batch:
            batch.drop_column("tenant_id")

    rel_idx = _indexes(bind, "relations")
    if "ix_relations_valid_to" in rel_idx:
        op.drop_index("ix_relations_valid_to", table_name="relations")
    rel_cols = _columns(bind, "relations")
    with op.batch_alter_table("relations") as batch:
        if "valid_to" in rel_cols:
            batch.drop_column("valid_to")
        if "valid_from" in rel_cols:
            batch.drop_column("valid_from")

    mem_idx = _indexes(bind, "memories")
    for name in ("ix_memories_user_superseded", "ix_memories_superseded_by"):
        if name in mem_idx:
            op.drop_index(name, table_name="memories")
    mem_cols = _columns(bind, "memories")
    with op.batch_alter_table("memories") as batch:
        if "superseded_at" in mem_cols:
            batch.drop_column("superseded_at")
        if "superseded_by" in mem_cols:
            batch.drop_column("superseded_by")
        if "version" in mem_cols:
            batch.drop_column("version")
