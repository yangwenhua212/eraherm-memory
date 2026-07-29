# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

import re

from app.ports.graph_store import ExtractedEntity, ExtractedRelation, ExtractionResult

_TECH = {
    "redis",
    "sqlite",
    "postgres",
    "postgresql",
    "mysql",
    "mongodb",
    "neo4j",
    "fastapi",
    "django",
    "flask",
    "kafka",
    "nginx",
    "docker",
    "kubernetes",
    "k8s",
    "qdrant",
    "chroma",
}

# Capture: Subject 依赖/使用 Object（可含顿号/和 连接的多个宾语）
_REL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"(?P<sub>[^\s，。；、]+?)\s*(?:依赖|依赖于|depends\s+on|depend\s+on)\s*(?P<obj>.+?)(?=。|$|；|;)",
            re.I,
        ),
        "depends_on",
    ),
    (
        re.compile(
            r"(?P<sub>[^\s，。；、]+?)\s*(?:使用|采用|uses|based\s+on)\s*(?P<obj>.+?)(?=。|$|；|;)",
            re.I,
        ),
        "uses",
    ),
    (
        re.compile(
            r"(?P<sub>[^\s，。；、]+?)\s*(?:拥有|属于|owned\s+by)\s*(?P<obj>.+?)(?=。|$|；|;)",
            re.I,
        ),
        "owned_by",
    ),
]


def infer_entity_type(name: str) -> str:
    n = name.strip()
    low = n.lower()
    if low in _TECH or any(t in low for t in _TECH):
        return "tech"
    if n.endswith("服务") or low.endswith("service") or low.endswith("-svc"):
        return "service"
    if n.endswith("项目") or "project" in low:
        return "project"
    if n.endswith("人") or n in {"用户", "老板"}:
        return "person"
    return "other"


def _split_objects(obj_blob: str) -> list[str]:
    parts = re.split(r"[、,，/]|和|与|及|以及|and", obj_blob)
    cleaned: list[str] = []
    for p in parts:
        p = p.strip().strip("的").strip()
        p = re.sub(r"^(了|到|着)", "", p)
        if len(p) >= 1:
            cleaned.append(p)
    return cleaned


class RuleGraphExtractor:
    """Offline regex/heuristic extractor (LLM extractor can replace via Port)."""

    def __init__(self, min_confidence: float = 0.5) -> None:
        self.min_confidence = min_confidence

    def extract(self, text: str) -> ExtractionResult:
        entities: dict[str, ExtractedEntity] = {}
        relations: list[ExtractedRelation] = []

        for pattern, rel_type in _REL_PATTERNS:
            for match in pattern.finditer(text):
                sub = match.group("sub").strip()
                objs = _split_objects(match.group("obj"))
                if not sub or not objs:
                    continue
                sub_type = infer_entity_type(sub)
                entities[sub.lower()] = ExtractedEntity(name=sub, entity_type=sub_type)
                for obj in objs:
                    obj_type = infer_entity_type(obj)
                    entities[obj.lower()] = ExtractedEntity(name=obj, entity_type=obj_type)
                    conf = 0.85 if rel_type == "depends_on" else 0.75
                    if conf < self.min_confidence:
                        continue
                    relations.append(
                        ExtractedRelation(
                            from_name=sub,
                            to_name=obj,
                            relation_type=rel_type,
                            confidence=conf,
                            from_type=sub_type,
                            to_type=obj_type,
                        )
                    )

        return ExtractionResult(entities=list(entities.values()), relations=relations)
