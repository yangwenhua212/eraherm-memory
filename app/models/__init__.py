# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import Column, Index, Text
from sqlmodel import Field, SQLModel


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class SessionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class MemoryType(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    IDENTITY = "identity"
    EPISODE = "episode"
    NEGATIVE = "negative"
    REFLECTION = "reflection"


class MemorySource(StrEnum):
    INGEST = "ingest"
    PROMOTION = "promotion"
    REFLECTION = "reflection"
    MANUAL = "manual"
    CONSOLIDATION = "consolidation"


class SessionRow(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(default_factory=lambda: new_id("sess"), primary_key=True)
    tenant_id: Optional[str] = Field(default=None, index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    status: str = Field(default=SessionStatus.OPEN.value, index=True)
    meta_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: str = Field(default_factory=utc_now_iso)
    closed_at: Optional[str] = None


class MemoryRow(SQLModel, table=True):
    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_user_pinned_deleted", "user_id", "pinned", "deleted_at"),
        Index("ix_memories_session_id", "session_id"),
    )

    id: str = Field(default_factory=lambda: new_id("mem"), primary_key=True)
    tenant_id: Optional[str] = Field(default=None, index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    session_id: Optional[str] = Field(default=None)
    content: str = Field(sa_column=Column(Text, nullable=False))
    memory_type: str = Field(default=MemoryType.FACT.value, index=True)
    importance: float = Field(default=0.5)
    weight: float = Field(default=1.0)
    pinned: bool = Field(default=False, index=True)
    decay_lambda: Optional[float] = None
    source: str = Field(default=MemorySource.INGEST.value)
    meta_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    last_accessed_at: Optional[str] = None
    access_count: int = Field(default=0)
    deleted_at: Optional[str] = Field(default=None, index=True)


class EntityRow(SQLModel, table=True):
    __tablename__ = "entities"
    __table_args__ = (Index("ix_entities_user_name", "user_id", "name"),)

    id: str = Field(default_factory=lambda: new_id("ent"), primary_key=True)
    tenant_id: Optional[str] = Field(default=None, index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    name: str = Field(index=True)
    entity_type: str = Field(default="other", index=True)
    aliases_json: str = Field(default="[]", sa_column=Column(Text))
    meta_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class RelationRow(SQLModel, table=True):
    __tablename__ = "relations"
    __table_args__ = (
        Index("ix_relations_from", "from_entity_id"),
        Index("ix_relations_to", "to_entity_id"),
    )

    id: str = Field(default_factory=lambda: new_id("rel"), primary_key=True)
    tenant_id: Optional[str] = Field(default=None, index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    from_entity_id: str = Field(index=True)
    to_entity_id: str = Field(index=True)
    relation_type: str = Field(default="related_to", index=True)
    weight: float = Field(default=1.0)
    confidence: float = Field(default=1.0)
    source_memory_id: Optional[str] = Field(default=None)
    created_at: str = Field(default_factory=utc_now_iso)
    deleted_at: Optional[str] = Field(default=None, index=True)


class FeedbackType(StrEnum):
    UPVOTE = "upvote"
    DOWNVOTE = "downvote"
    CORRECT = "correct"


class ReflectionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED_LOW_CONFIDENCE = "rejected_low_confidence"
    FAILED = "failed"


class FeedbackEventRow(SQLModel, table=True):
    __tablename__ = "feedback_events"

    id: str = Field(default_factory=lambda: new_id("fb"), primary_key=True)
    tenant_id: Optional[str] = Field(default=None, index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    session_id: Optional[str] = Field(default=None)
    answer_id: str = Field(index=True)
    feedback_type: str = Field(index=True)
    correction_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    related_memory_ids_json: str = Field(default="[]", sa_column=Column(Text))
    answer_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: str = Field(default_factory=utc_now_iso)


class ReflectionRecordRow(SQLModel, table=True):
    __tablename__ = "reflection_records"

    id: str = Field(default_factory=lambda: new_id("ref"), primary_key=True)
    feedback_id: str = Field(index=True)
    analysis: str = Field(default="", sa_column=Column(Text))
    summary: str = Field(default="", sa_column=Column(Text))
    confidence: float = Field(default=0.0)
    derived_memory_id: Optional[str] = Field(default=None)
    status: str = Field(default=ReflectionStatus.PENDING.value, index=True)
    created_at: str = Field(default_factory=utc_now_iso)


class L3ArchiveRow(SQLModel, table=True):
    __tablename__ = "l3_archives"

    id: str = Field(default_factory=lambda: new_id("l3"), primary_key=True)
    uri: str = Field(sa_column=Column(Text, nullable=False))
    checksum: str = Field(default="")
    memory_count: int = Field(default=0)
    entity_count: int = Field(default=0)
    relation_count: int = Field(default=0)
    created_at: str = Field(default_factory=utc_now_iso)


# Domain DTOs (not tables)


class L1Item:
    __slots__ = (
        "id",
        "content",
        "memory_type",
        "importance",
        "weight",
        "pinned",
        "user_id",
        "tenant_id",
        "session_id",
        "meta",
        "created_at",
    )

    def __init__(
        self,
        *,
        content: str,
        memory_type: str = MemoryType.FACT.value,
        importance: float = 0.5,
        weight: float = 1.0,
        pinned: bool = False,
        user_id: str | None = None,
        tenant_id: str | None = None,
        session_id: str | None = None,
        meta: dict[str, Any] | None = None,
        id: str | None = None,
        created_at: str | None = None,
    ) -> None:
        self.id = id or new_id("mem")
        self.content = content
        self.memory_type = memory_type
        self.importance = importance
        self.weight = weight
        self.pinned = pinned
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.meta = meta or {}
        self.created_at = created_at or utc_now_iso()
