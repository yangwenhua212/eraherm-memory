# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

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


# 口语虚词/连接词——主语或宾语命中即丢弃（不构成实体）
_STOPWORDS = {
    "不", "就", "也", "还", "又", "都", "才", "再", "只", "很", "太", "更",
    "然后", "接着", "所以", "因为", "但是", "不过", "而且", "其实", "就是",
    "以及", "或者", "这个", "那个", "这样", "那样", "怎么", "什么", "为什么",
    "是否", "可能", "应该", "可以", "需要", "没有", "不是", "还是", "方式",
    "方法", "时候", "地方", "东西", "事情", "问题", "感觉", "知道", "觉得",
}

# 宾语里的否定残留前缀（「不是 X」「不用 X」→ X 是正主语，丢弃残留）
_NEGATION_PREFIX = re.compile(r"^(?:不是|不用|不要|没有|非|并非|并非不是|不等于|而不是)", re.I)

# 单字实体仅允许白名单（技术栈/人名等强信号，宁可少抽不可抽错）
_SINGLE_CHAR_ALLOW = {"云", "网"}


def _is_valid_entity(name: str) -> bool:
    n = name.strip()
    if not n:
        return False
    # 长度门槛：1 字除非白名单
    if len(n) == 1 and n not in _SINGLE_CHAR_ALLOW:
        return False
    # 纯标点/符号
    if re.fullmatch(r"[\W_]+", n, flags=re.UNICODE):
        return False
    # 停用词（含否定残留词本身）
    if n.lower() in _STOPWORDS:
        return False
    # 含停用词的整句碎片（如「把两个完全不同的东西混在一起说了」）
    if any(w in n for w in ("的", "了", "把", "在", "混在一起", "来回跳")):
        return False
    return True


def _clean_object(obj: str) -> str | None:
    """清理宾语：去否定残留前缀与尾部虚词，不合格返回 None。"""
    o = obj.strip().strip("的").strip()
    o = re.sub(r"^(了|到|着)", "", o)
    o = _NEGATION_PREFIX.sub("", o).strip()
    if not _is_valid_entity(o):
        return None
    return o


def _split_objects(obj_blob: str) -> list[str]:
    parts = re.split(r"[、,，/]|和|与|及|以及|and", obj_blob)
    cleaned: list[str] = []
    for p in parts:
        c = _clean_object(p)
        if c:
            cleaned.append(c)
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
                if not _is_valid_entity(sub) or not objs:
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
