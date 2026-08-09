# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op
from sqlmodel import SQLModel

# Ensure metadata includes all tables
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

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.drop_all(bind=bind)
