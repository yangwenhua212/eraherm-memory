# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.models import EntityRow, MemoryRow
from app.ports.graph_store import (
    ExtractionResult,
    GraphExtractor,
    GraphPath,
    GraphStore,
)
from app.ports.memory_repo import MemoryRepository


@dataclass
class IngestGraphResult:
    entities: int
    relations: int
    extraction: ExtractionResult


@dataclass
class ImpactResult:
    seed: EntityRow
    paths: list[GraphPath]
    direction: str
    max_hops: int


class GraphService:
    def __init__(
        self,
        *,
        store: GraphStore,
        extractor: GraphExtractor,
        settings: Settings,
        memory_repo: MemoryRepository | None = None,
    ) -> None:
        self.store = store
        self.extractor = extractor
        self.settings = settings
        self.memory_repo = memory_repo

    def extract_and_ingest(
        self,
        *,
        user_id: str,
        text: str,
        tenant_id: str | None = None,
        source_memory_id: str | None = None,
    ) -> IngestGraphResult:
        extraction = self.extractor.extract(text)
        entity_ids: dict[str, str] = {}
        for ent in extraction.entities:
            row = self.store.upsert_entity(
                user_id=user_id,
                name=ent.name,
                entity_type=ent.entity_type,
                tenant_id=tenant_id,
                aliases=ent.aliases,
            )
            entity_ids[ent.name.lower()] = row.id

        rel_count = 0
        for rel in extraction.relations:
            if rel.confidence < self.settings.graph_min_extract_confidence:
                continue
            # Ensure endpoints exist even if entity list missed them
            if rel.from_name.lower() not in entity_ids:
                row = self.store.upsert_entity(
                    user_id=user_id,
                    name=rel.from_name,
                    entity_type=rel.from_type,
                    tenant_id=tenant_id,
                )
                entity_ids[rel.from_name.lower()] = row.id
            if rel.to_name.lower() not in entity_ids:
                row = self.store.upsert_entity(
                    user_id=user_id,
                    name=rel.to_name,
                    entity_type=rel.to_type,
                    tenant_id=tenant_id,
                )
                entity_ids[rel.to_name.lower()] = row.id

            self.store.upsert_relation(
                user_id=user_id,
                from_entity_id=entity_ids[rel.from_name.lower()],
                to_entity_id=entity_ids[rel.to_name.lower()],
                relation_type=rel.relation_type,
                confidence=rel.confidence,
                source_memory_id=source_memory_id,
                tenant_id=tenant_id,
            )
            rel_count += 1

        return IngestGraphResult(
            entities=len(entity_ids),
            relations=rel_count,
            extraction=extraction,
        )

    def extract_from_memory(self, memory: MemoryRow) -> IngestGraphResult:
        if not memory.user_id:
            raise ValueError("memory.user_id required for graph extract")
        return self.extract_and_ingest(
            user_id=memory.user_id,
            text=memory.content,
            tenant_id=memory.tenant_id,
            source_memory_id=memory.id,
        )

    def extract(
        self,
        *,
        user_id: str,
        text: str | None = None,
        memory_id: str | None = None,
        tenant_id: str | None = None,
    ) -> IngestGraphResult:
        if memory_id:
            if self.memory_repo is None:
                raise RuntimeError("memory_repo not configured")
            mem = self.memory_repo.get_memory(memory_id)
            if mem is None or mem.deleted_at is not None:
                raise KeyError(f"memory not found: {memory_id}")
            return self.extract_from_memory(mem)
        if not text:
            raise ValueError("text or memory_id required")
        return self.extract_and_ingest(user_id=user_id, text=text, tenant_id=tenant_id)

    def list_entities(
        self,
        *,
        user_id: str,
        q: str | None = None,
        entity_type: str | None = None,
        tenant_id: str | None = None,
        limit: int = 50,
    ) -> list[EntityRow]:
        return self.store.list_entities(
            user_id=user_id,
            q=q,
            entity_type=entity_type,
            tenant_id=tenant_id,
            limit=limit,
        )

    def impact(
        self,
        *,
        user_id: str,
        entity_name: str,
        direction: str = "inbound",
        max_hops: int | None = None,
        tenant_id: str | None = None,
    ) -> ImpactResult:
        max_hops = max_hops or self.settings.graph_max_hops_default
        seed = self.store.find_entity(user_id=user_id, name=entity_name, tenant_id=tenant_id)
        if seed is None:
            raise KeyError(f"entity not found: {entity_name}")
        paths = self.store.impact_paths(
            user_id=user_id,
            seed_entity_id=seed.id,
            max_hops=max_hops,
            direction=direction,
            tenant_id=tenant_id,
        )
        return ImpactResult(seed=seed, paths=paths, direction=direction, max_hops=max_hops)
