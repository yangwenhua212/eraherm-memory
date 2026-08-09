# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

from app.models import EntityRow, RelationRow


@dataclass
class GraphNode:
    id: str
    name: str
    entity_type: str


@dataclass
class GraphEdge:
    id: str
    from_entity_id: str
    to_entity_id: str
    relation_type: str
    weight: float = 1.0
    confidence: float = 1.0


@dataclass
class GraphPath:
    hops: int
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)


@dataclass
class ExtractedEntity:
    name: str
    entity_type: str = "other"
    aliases: list[str] = field(default_factory=list)


@dataclass
class ExtractedRelation:
    from_name: str
    to_name: str
    relation_type: str
    confidence: float = 0.8
    from_type: str = "other"
    to_type: str = "other"


@dataclass
class ExtractionResult:
    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)


@runtime_checkable
class GraphExtractor(Protocol):
    def extract(self, text: str) -> ExtractionResult: ...


@runtime_checkable
class GraphStore(Protocol):
    def upsert_entity(
        self,
        *,
        user_id: str,
        name: str,
        entity_type: str = "other",
        tenant_id: str | None = None,
        aliases: Sequence[str] | None = None,
    ) -> EntityRow: ...

    def find_entity(
        self,
        *,
        user_id: str,
        name: str,
        tenant_id: str | None = None,
    ) -> EntityRow | None: ...

    def list_entities(
        self,
        *,
        user_id: str,
        q: str | None = None,
        entity_type: str | None = None,
        tenant_id: str | None = None,
        limit: int = 50,
    ) -> list[EntityRow]: ...

    def upsert_relation(
        self,
        *,
        user_id: str,
        from_entity_id: str,
        to_entity_id: str,
        relation_type: str,
        weight: float = 1.0,
        confidence: float = 1.0,
        source_memory_id: str | None = None,
        tenant_id: str | None = None,
    ) -> RelationRow: ...

    def impact_paths(
        self,
        *,
        user_id: str,
        seed_entity_id: str,
        max_hops: int = 2,
        direction: str = "inbound",
        tenant_id: str | None = None,
    ) -> list[GraphPath]: ...
