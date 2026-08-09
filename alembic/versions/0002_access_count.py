# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""0002 access_count for consolidation

Revision ID: 0002_access_count
Revises: 0001_initial
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0002_access_count"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("memories")}
    if "access_count" in cols:
        # 0001 create_all on newer models may already have the column
        return
    with op.batch_alter_table("memories") as batch:
        batch.add_column(
            sa.Column("access_count", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("memories")}
    if "access_count" not in cols:
        return
    with op.batch_alter_table("memories") as batch:
        batch.drop_column("access_count")
