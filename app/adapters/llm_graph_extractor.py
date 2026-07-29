# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from app.adapters.openai_llm import OpenAICompatibleLLM
from app.graph.extractor import RuleGraphExtractor
from app.ports.graph_store import ExtractedEntity, ExtractedRelation, ExtractionResult


_SYSTEM = """你是知识图谱抽取器。从文本中抽取实体与关系，只输出 JSON：
{
  "entities": [{"name": "...", "entity_type": "person|project|service|tech|other"}],
  "relations": [{"from_name": "...", "to_name": "...", "relation_type": "depends_on|uses|owned_by|related_to", "confidence": 0.0-1.0}]
}
不要编造文本中不存在的实体。"""


class LLMGraphExtractor:
    def __init__(self, llm: OpenAICompatibleLLM, *, min_confidence: float = 0.5) -> None:
        self.llm = llm
        self.min_confidence = min_confidence

    def extract(self, text: str) -> ExtractionResult:
        data = self.llm.complete_json(system=_SYSTEM, user=text)
        entities = [
            ExtractedEntity(
                name=str(e.get("name", "")).strip(),
                entity_type=str(e.get("entity_type", "other")),
            )
            for e in data.get("entities", [])
            if str(e.get("name", "")).strip()
        ]
        relations: list[ExtractedRelation] = []
        for r in data.get("relations", []):
            conf = float(r.get("confidence", 0.8))
            if conf < self.min_confidence:
                continue
            fr = str(r.get("from_name", "")).strip()
            to = str(r.get("to_name", "")).strip()
            if not fr or not to:
                continue
            relations.append(
                ExtractedRelation(
                    from_name=fr,
                    to_name=to,
                    relation_type=str(r.get("relation_type", "related_to")),
                    confidence=conf,
                )
            )
        return ExtractionResult(entities=entities, relations=relations)


class FallbackGraphExtractor:
    """Try primary extractor; on failure/empty relations, fall back to rules."""

    def __init__(self, primary, fallback: RuleGraphExtractor | None = None) -> None:
        self.primary = primary
        self.fallback = fallback or RuleGraphExtractor()

    def extract(self, text: str) -> ExtractionResult:
        try:
            result = self.primary.extract(text)
            if result.relations or result.entities:
                return result
        except Exception:  # noqa: BLE001
            pass
        return self.fallback.extract(text)
