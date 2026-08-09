# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from typing import Sequence

from app.models import EntityRow, RelationRow, new_id, utc_now_iso
from app.ports.graph_store import GraphEdge, GraphNode, GraphPath


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", "", name.strip().lower())


class Neo4jGraphStore:
    """GraphStore on Neo4j. Requires neo4j driver extra."""

    def __init__(self, *, uri: str, user: str = "neo4j", password: str = "password") -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover
            raise ImportError("Install neo4j extra: pip install 'eraherm-memory[neo4j]'") from exc
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

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
            with self._driver.session() as session:
                session.run(
                    """
                    MATCH (e:Entity {id: $id})
                    SET e.entity_type = $entity_type,
                        e.updated_at = $updated_at,
                        e.aliases_json = $aliases_json
                    """,
                    id=existing.id,
                    entity_type=entity_type or existing.entity_type,
                    updated_at=now,
                    aliases_json=json.dumps(
                        sorted(set(json.loads(existing.aliases_json or "[]")) | set(aliases)),
                        ensure_ascii=False,
                    ),
                )
            existing.entity_type = entity_type or existing.entity_type
            existing.updated_at = now
            return existing

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
        with self._driver.session() as session:
            session.run(
                """
                CREATE (e:Entity {
                  id: $id, user_id: $user_id, tenant_id: $tenant_id,
                  name: $name, name_norm: $name_norm, entity_type: $entity_type,
                  aliases_json: $aliases_json, created_at: $created_at, updated_at: $updated_at
                })
                """,
                id=row.id,
                user_id=row.user_id,
                tenant_id=row.tenant_id,
                name=row.name,
                name_norm=_norm_name(row.name),
                entity_type=row.entity_type,
                aliases_json=row.aliases_json,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        return row

    def find_entity(
        self,
        *,
        user_id: str,
        name: str,
        tenant_id: str | None = None,
    ) -> EntityRow | None:
        target = _norm_name(name)
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity {user_id: $user_id})
                WHERE ($tenant_id IS NULL OR e.tenant_id = $tenant_id)
                RETURN e
                """,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            for rec in result:
                e = rec["e"]
                aliases = json.loads(e.get("aliases_json") or "[]")
                if e.get("name_norm") == target or any(_norm_name(a) == target for a in aliases):
                    return _entity_from_node(e)
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
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity {user_id: $user_id})
                WHERE ($tenant_id IS NULL OR e.tenant_id = $tenant_id)
                  AND ($entity_type IS NULL OR e.entity_type = $entity_type)
                RETURN e
                LIMIT $limit
                """,
                user_id=user_id,
                tenant_id=tenant_id,
                entity_type=entity_type,
                limit=limit * 3,
            )
            rows = [_entity_from_node(rec["e"]) for rec in result]
        if q:
            qn = _norm_name(q)
            rows = [r for r in rows if qn in _norm_name(r.name)]
        return rows[:limit]

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
        rel_id = new_id("rel")
        now = utc_now_iso()
        with self._driver.session() as session:
            existing = session.run(
                """
                MATCH (a:Entity {id: $from_id})-[r:REL {user_id: $user_id, relation_type: $relation_type}]->(b:Entity {id: $to_id})
                WHERE r.deleted_at IS NULL
                RETURN r
                LIMIT 1
                """,
                from_id=from_entity_id,
                to_id=to_entity_id,
                user_id=user_id,
                relation_type=relation_type,
            ).single()
            if existing:
                r = existing["r"]
                session.run(
                    """
                    MATCH ()-[r:REL {id: $id}]->()
                    SET r.weight = $weight,
                        r.confidence = CASE WHEN r.confidence > $confidence THEN r.confidence ELSE $confidence END,
                        r.source_memory_id = coalesce($source_memory_id, r.source_memory_id)
                    """,
                    id=r["id"],
                    weight=weight,
                    confidence=confidence,
                    source_memory_id=source_memory_id,
                )
                return _relation_from_node(r, from_entity_id, to_entity_id)

            session.run(
                """
                MATCH (a:Entity {id: $from_id}), (b:Entity {id: $to_id})
                CREATE (a)-[r:REL {
                  id: $id, user_id: $user_id, tenant_id: $tenant_id,
                  relation_type: $relation_type, weight: $weight, confidence: $confidence,
                  source_memory_id: $source_memory_id, created_at: $created_at, deleted_at: null
                }]->(b)
                """,
                from_id=from_entity_id,
                to_id=to_entity_id,
                id=rel_id,
                user_id=user_id,
                tenant_id=tenant_id,
                relation_type=relation_type,
                weight=weight,
                confidence=confidence,
                source_memory_id=source_memory_id,
                created_at=now,
            )
        return RelationRow(
            id=rel_id,
            user_id=user_id,
            tenant_id=tenant_id,
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            relation_type=relation_type,
            weight=weight,
            confidence=confidence,
            source_memory_id=source_memory_id,
            created_at=now,
        )

    def impact_paths(
        self,
        *,
        user_id: str,
        seed_entity_id: str,
        max_hops: int = 2,
        direction: str = "inbound",
        tenant_id: str | None = None,
    ) -> list[GraphPath]:
        # Load subgraph into memory BFS (keeps semantics aligned with NetworkX adapter)
        entities: dict[str, EntityRow] = {}
        relations: list[RelationRow] = []
        with self._driver.session() as session:
            ent_res = session.run(
                """
                MATCH (e:Entity {user_id: $user_id})
                WHERE ($tenant_id IS NULL OR e.tenant_id = $tenant_id)
                RETURN e
                """,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            for rec in ent_res:
                row = _entity_from_node(rec["e"])
                entities[row.id] = row
            rel_res = session.run(
                """
                MATCH (a:Entity {user_id: $user_id})-[r:REL {user_id: $user_id}]->(b:Entity)
                WHERE r.deleted_at IS NULL
                  AND ($tenant_id IS NULL OR r.tenant_id = $tenant_id)
                RETURN a.id AS from_id, b.id AS to_id, r
                """,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            for rec in rel_res:
                relations.append(_relation_from_node(rec["r"], rec["from_id"], rec["to_id"]))

        if seed_entity_id not in entities:
            return []

        outbound: dict[str, list[str]] = defaultdict(list)
        inbound: dict[str, list[str]] = defaultdict(list)
        for rel in relations:
            outbound[rel.from_entity_id].append(rel.to_entity_id)
            inbound[rel.to_entity_id].append(rel.from_entity_id)

        if direction == "inbound":
            neighbors = inbound
        elif direction == "outbound":
            neighbors = outbound
        elif direction == "both":
            neighbors = defaultdict(list)
            for k, vs in outbound.items():
                neighbors[k].extend(vs)
            for k, vs in inbound.items():
                neighbors[k].extend(vs)
        else:
            raise ValueError(f"unsupported direction: {direction}")

        rel_index: dict[tuple[str, str], list[RelationRow]] = defaultdict(list)
        for rel in relations:
            rel_index[(rel.from_entity_id, rel.to_entity_id)].append(rel)

        paths: list[GraphPath] = []
        queue: deque[list[str]] = deque([[seed_entity_id]])
        while queue:
            nodes = queue.popleft()
            if len(nodes) - 1 >= 1:
                paths.append(_build_path(nodes, entities, rel_index, direction))
            if len(nodes) - 1 >= max_hops:
                continue
            for nxt in neighbors.get(nodes[-1], []):
                if nxt in nodes:
                    continue
                queue.append(nodes + [nxt])
        paths.sort(key=lambda p: (p.hops, p.nodes[-1].name if p.nodes else ""))
        return paths


def _entity_from_node(e) -> EntityRow:
    return EntityRow(
        id=e["id"],
        user_id=e.get("user_id"),
        tenant_id=e.get("tenant_id"),
        name=e["name"],
        entity_type=e.get("entity_type") or "other",
        aliases_json=e.get("aliases_json") or "[]",
        created_at=e.get("created_at") or utc_now_iso(),
        updated_at=e.get("updated_at") or utc_now_iso(),
    )


def _relation_from_node(r, from_id: str, to_id: str) -> RelationRow:
    return RelationRow(
        id=r["id"],
        user_id=r.get("user_id"),
        tenant_id=r.get("tenant_id"),
        from_entity_id=from_id,
        to_entity_id=to_id,
        relation_type=r.get("relation_type") or "related_to",
        weight=float(r.get("weight") or 1.0),
        confidence=float(r.get("confidence") or 1.0),
        source_memory_id=r.get("source_memory_id"),
        created_at=r.get("created_at") or utc_now_iso(),
        deleted_at=r.get("deleted_at"),
    )


def _build_path(
    node_ids: list[str],
    entities: dict[str, EntityRow],
    rel_index: dict[tuple[str, str], list[RelationRow]],
    direction: str,
) -> GraphPath:
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
