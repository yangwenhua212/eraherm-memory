# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from typing import Sequence

import networkx as nx
from sqlmodel import Session, col, select

from app.models import EntityRow, RelationRow, new_id, utc_now_iso
from app.ports.graph_store import GraphEdge, GraphNode, GraphPath


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", "", name.strip().lower())


class NetworkXSqliteGraphStore:
    """Persist entities/relations in SQLite; query paths via NetworkX."""

    def __init__(self, engine) -> None:
        self.engine = engine
        # Ensure tables exist (EntityRow/RelationRow must already be imported).
        from sqlmodel import SQLModel

        SQLModel.metadata.create_all(self.engine)

    def upsert_entity(
        self,
        *,
        user_id: str,
        name: str,
        entity_type: str = "other",
        tenant_id: str | None = None,
        aliases: Sequence[str] | None = None,
    ) -> EntityRow:
        existing = self.find_entity(user_id=user_id, name=name, tenant_id=tenant_id)
        now = utc_now_iso()
        aliases = list(aliases or [])
        if existing is not None:
            with Session(self.engine) as db:
                row = db.get(EntityRow, existing.id)
                assert row is not None
                row.entity_type = entity_type or row.entity_type
                row.updated_at = now
                if aliases:
                    current = json.loads(row.aliases_json or "[]")
                    merged = sorted(set(current) | set(aliases))
                    row.aliases_json = json.dumps(merged, ensure_ascii=False)
                db.commit()
                db.refresh(row)
                db.expunge(row)
                return row

        row = EntityRow(
            id=new_id("ent"),
            user_id=user_id,
            tenant_id=tenant_id,
            name=name.strip(),
            entity_type=entity_type,
            aliases_json=json.dumps(aliases, ensure_ascii=False),
            created_at=now,
            updated_at=now,
        )
        with Session(self.engine) as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            db.expunge(row)
            return row

    def find_entity(
        self,
        *,
        user_id: str,
        name: str,
        tenant_id: str | None = None,
    ) -> EntityRow | None:
        target = _norm_name(name)
        with Session(self.engine) as db:
            stmt = select(EntityRow).where(EntityRow.user_id == user_id)
            if tenant_id is not None:
                stmt = stmt.where(EntityRow.tenant_id == tenant_id)
            rows = list(db.exec(stmt).all())
            for row in rows:
                if _norm_name(row.name) == target:
                    db.expunge(row)
                    return row
                aliases = json.loads(row.aliases_json or "[]")
                if any(_norm_name(a) == target for a in aliases):
                    db.expunge(row)
                    return row
            return None

    def list_entities(
        self,
        *,
        user_id: str,
        q: str | None = None,
        entity_type: str | None = None,
        tenant_id: str | None = None,
        limit: int = 50,
    ) -> list[EntityRow]:
        with Session(self.engine) as db:
            stmt = select(EntityRow).where(EntityRow.user_id == user_id)
            if tenant_id is not None:
                stmt = stmt.where(EntityRow.tenant_id == tenant_id)
            if entity_type:
                stmt = stmt.where(EntityRow.entity_type == entity_type)
            rows = list(db.exec(stmt).all())
            if q:
                qn = _norm_name(q)
                rows = [r for r in rows if qn in _norm_name(r.name)]
            rows = rows[:limit]
            for row in rows:
                db.expunge(row)
            return rows

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
    ) -> RelationRow:
        with Session(self.engine) as db:
            stmt = select(RelationRow).where(
                RelationRow.user_id == user_id,
                RelationRow.from_entity_id == from_entity_id,
                RelationRow.to_entity_id == to_entity_id,
                RelationRow.relation_type == relation_type,
                col(RelationRow.deleted_at).is_(None),
            )
            existing = db.exec(stmt).first()
            if existing is not None:
                existing.weight = weight
                existing.confidence = max(existing.confidence, confidence)
                if source_memory_id:
                    existing.source_memory_id = source_memory_id
                db.commit()
                db.refresh(existing)
                db.expunge(existing)
                return existing

            row = RelationRow(
                id=new_id("rel"),
                user_id=user_id,
                tenant_id=tenant_id,
                from_entity_id=from_entity_id,
                to_entity_id=to_entity_id,
                relation_type=relation_type,
                weight=weight,
                confidence=confidence,
                source_memory_id=source_memory_id,
                created_at=utc_now_iso(),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            db.expunge(row)
            return row

    def impact_paths(
        self,
        *,
        user_id: str,
        seed_entity_id: str,
        max_hops: int = 2,
        direction: str = "inbound",
        tenant_id: str | None = None,
    ) -> list[GraphPath]:
        entities, relations = self._load_graph(user_id=user_id, tenant_id=tenant_id)
        if seed_entity_id not in entities:
            return []

        graph = nx.DiGraph()
        for eid, ent in entities.items():
            graph.add_node(eid, name=ent.name, entity_type=ent.entity_type)
        for rel in relations:
            graph.add_edge(
                rel.from_entity_id,
                rel.to_entity_id,
                id=rel.id,
                relation_type=rel.relation_type,
                weight=rel.weight,
                confidence=rel.confidence,
            )

        if direction == "inbound":
            walk = graph.reverse(copy=False)
        elif direction == "outbound":
            walk = graph
        elif direction == "both":
            walk = graph.to_undirected(as_view=False)
        else:
            raise ValueError(f"unsupported direction: {direction}")

        paths: list[GraphPath] = []
        # BFS enumerate simple paths up to max_hops
        queue: deque[list[str]] = deque([[seed_entity_id]])
        while queue:
            path_nodes = queue.popleft()
            if len(path_nodes) - 1 >= 1:
                paths.append(self._build_path(path_nodes, entities, relations, direction))
            if len(path_nodes) - 1 >= max_hops:
                continue
            last = path_nodes[-1]
            for nxt in walk.neighbors(last):
                if nxt in path_nodes:
                    continue
                queue.append(path_nodes + [nxt])

        paths.sort(key=lambda p: (p.hops, p.nodes[-1].name if p.nodes else ""))
        return paths

    def _load_graph(
        self, *, user_id: str, tenant_id: str | None
    ) -> tuple[dict[str, EntityRow], list[RelationRow]]:
        with Session(self.engine) as db:
            estmt = select(EntityRow).where(EntityRow.user_id == user_id)
            rstmt = select(RelationRow).where(
                RelationRow.user_id == user_id,
                col(RelationRow.deleted_at).is_(None),
            )
            if tenant_id is not None:
                estmt = estmt.where(EntityRow.tenant_id == tenant_id)
                rstmt = rstmt.where(RelationRow.tenant_id == tenant_id)
            entities = {e.id: e for e in db.exec(estmt).all()}
            relations = list(db.exec(rstmt).all())
            for e in entities.values():
                db.expunge(e)
            for r in relations:
                db.expunge(r)
            return entities, relations

    def _build_path(
        self,
        node_ids: list[str],
        entities: dict[str, EntityRow],
        relations: list[RelationRow],
        direction: str,
    ) -> GraphPath:
        rel_index: dict[tuple[str, str], list[RelationRow]] = defaultdict(list)
        for rel in relations:
            rel_index[(rel.from_entity_id, rel.to_entity_id)].append(rel)

        nodes = [
            GraphNode(id=eid, name=entities[eid].name, entity_type=entities[eid].entity_type)
            for eid in node_ids
            if eid in entities
        ]
        edges: list[GraphEdge] = []
        for a, b in zip(node_ids, node_ids[1:]):
            candidates = rel_index.get((a, b), [])
            if not candidates and direction in {"inbound", "both"}:
                candidates = rel_index.get((b, a), [])
            if not candidates:
                continue
            rel = candidates[0]
            edges.append(
                GraphEdge(
                    id=rel.id,
                    from_entity_id=rel.from_entity_id,
                    to_entity_id=rel.to_entity_id,
                    relation_type=rel.relation_type,
                    weight=rel.weight,
                    confidence=rel.confidence,
                )
            )
        return GraphPath(hops=len(node_ids) - 1, nodes=nodes, edges=edges)
