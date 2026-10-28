# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-29

**本文件在 0.10.2 被改写为显式 DDL**（原来是 ``SQLModel.metadata.create_all()``）。

为什么必须改：用**当前**模型建**历史**表，等于迁移路径永远不会失败 ——
``alembic upgrade head`` 在任何模型改动下都"成功"，因为没有迁移是必需的。
后果是 0002 只能靠 ``inspect()`` 猜列在不在，任何新列都可能悄悄缺失，
而 CI 里也没有任何东西能发现（见 docs/KNOWN_ISSUES.md「迁移路径不可信」）。

改写后的语义：0001 建「当时的」结构 → 0002 加 ``access_count`` →
0003 加取代链 / 关系有效期 / 向量租户列。三步合起来必须等于当前模型，
由 ``tests/test_migration_schema.py`` 强制校验。

改写已应用过的迁移通常是坏做法；这里可以，因为旧 0001 的内容本就是
「create_all(当前模型)」，对任何已部署实例而言它都不是可复现的历史记录，
且已部署实例的 ``alembic_version`` 停在 0003，不会重跑 0001。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("meta_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("closed_at", sa.String(), nullable=True),
    )
    op.create_index("ix_sessions_tenant_id", "sessions", ["tenant_id"])
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_status", "sessions", ["status"])

    op.create_table(
        "memories",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("memory_type", sa.String(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("decay_lambda", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("meta_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("last_accessed_at", sa.String(), nullable=True),
        sa.Column("deleted_at", sa.String(), nullable=True),
    )
    op.create_index("ix_memories_tenant_id", "memories", ["tenant_id"])
    op.create_index("ix_memories_user_id", "memories", ["user_id"])
    op.create_index("ix_memories_memory_type", "memories", ["memory_type"])
    op.create_index("ix_memories_pinned", "memories", ["pinned"])
    op.create_index("ix_memories_deleted_at", "memories", ["deleted_at"])
    op.create_index(
        "ix_memories_user_pinned_deleted", "memories", ["user_id", "pinned", "deleted_at"]
    )
    op.create_index("ix_memories_session_id", "memories", ["session_id"])

    op.create_table(
        "entities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("aliases_json", sa.Text(), nullable=False),
        sa.Column("meta_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_entities_tenant_id", "entities", ["tenant_id"])
    op.create_index("ix_entities_user_id", "entities", ["user_id"])
    op.create_index("ix_entities_name", "entities", ["name"])
    op.create_index("ix_entities_entity_type", "entities", ["entity_type"])
    op.create_index("ix_entities_user_name", "entities", ["user_id", "name"])

    op.create_table(
        "relations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("from_entity_id", sa.String(), nullable=False),
        sa.Column("to_entity_id", sa.String(), nullable=False),
        sa.Column("relation_type", sa.String(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_memory_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
    )
    op.create_index("ix_relations_tenant_id", "relations", ["tenant_id"])
    op.create_index("ix_relations_user_id", "relations", ["user_id"])
    op.create_index("ix_relations_from_entity_id", "relations", ["from_entity_id"])
    op.create_index("ix_relations_to_entity_id", "relations", ["to_entity_id"])
    op.create_index("ix_relations_relation_type", "relations", ["relation_type"])
    op.create_index("ix_relations_deleted_at", "relations", ["deleted_at"])
    op.create_index("ix_relations_from", "relations", ["from_entity_id"])
    op.create_index("ix_relations_to", "relations", ["to_entity_id"])

    op.create_table(
        "embeddings",
        sa.Column("memory_id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_embeddings_user_id", "embeddings", ["user_id"])

    op.create_table(
        "feedback_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("answer_id", sa.String(), nullable=False),
        sa.Column("feedback_type", sa.String(), nullable=False),
        sa.Column("correction_text", sa.Text(), nullable=True),
        sa.Column("related_memory_ids_json", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_feedback_events_tenant_id", "feedback_events", ["tenant_id"])
    op.create_index("ix_feedback_events_user_id", "feedback_events", ["user_id"])
    op.create_index("ix_feedback_events_answer_id", "feedback_events", ["answer_id"])
    op.create_index(
        "ix_feedback_events_feedback_type", "feedback_events", ["feedback_type"]
    )

    op.create_table(
        "reflection_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("feedback_id", sa.String(), nullable=False),
        sa.Column("analysis", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("derived_memory_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_reflection_records_feedback_id", "reflection_records", ["feedback_id"])
    op.create_index("ix_reflection_records_status", "reflection_records", ["status"])

    op.create_table(
        "l3_archives",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=False),
        sa.Column("memory_count", sa.Integer(), nullable=False),
        sa.Column("entity_count", sa.Integer(), nullable=False),
        sa.Column("relation_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("l3_archives")
    op.drop_table("reflection_records")
    op.drop_table("feedback_events")
    op.drop_table("embeddings")
    op.drop_table("relations")
    op.drop_table("entities")
    op.drop_table("memories")
    op.drop_table("sessions")
