# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class CreateSessionRequest(BaseModel):
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    id: str
    status: str
    created_at: str


class CloseSessionResponse(BaseModel):
    id: str
    status: str
    promoted_count: int
    dropped_count: int


class RememberRequest(BaseModel):
    content: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    memory_type: str = "fact"
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    pinned: bool = False
    extract_graph: Optional[bool] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class MemoryAlertResponse(BaseModel):
    type: str
    severity: float
    message: str
    related_memory_ids: list[str] = Field(default_factory=list)


class RecommendationResponse(BaseModel):
    memory_id: str
    content: str
    score: float
    reason: str


class RememberResponse(BaseModel):
    id: str
    layer: str
    pinned: bool
    entities_extracted: int = 0
    relations_extracted: int = 0
    alerts: list[MemoryAlertResponse] = Field(default_factory=list)


class PinRequest(BaseModel):
    memory_id: Optional[str] = None
    pinned: bool = True
    user_id: Optional[str] = None
    content: Optional[str] = None
    memory_type: str = "identity"
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    importance: float = Field(default=1.0, ge=0.0, le=1.0)
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_mode(self) -> PinRequest:
        if self.memory_id:
            return self
        if self.user_id and self.content:
            return self
        raise ValueError("provide memory_id, or user_id + content")


class RecallRequest(BaseModel):
    user_id: str
    query: str
    session_id: Optional[str] = None
    tenant_id: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=100)
    include_pinned: bool = True
    expand_graph: bool = False
    min_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override ERAHERM_RECALL_MIN_SCORE; drop items below this score",
    )


class RecallItemResponse(BaseModel):
    id: str
    content: str
    memory_type: str
    score: float
    pinned: bool
    layer: str


class RecallResponse(BaseModel):
    items: list[RecallItemResponse]
    recommendations: list[RecommendationResponse] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    version: str


class GraphExtractRequest(BaseModel):
    user_id: str
    text: Optional[str] = None
    memory_id: Optional[str] = None
    tenant_id: Optional[str] = None


class GraphExtractResponse(BaseModel):
    entities: int
    relations: int
    entity_names: list[str] = Field(default_factory=list)
    relation_summaries: list[str] = Field(default_factory=list)


class EntityResponse(BaseModel):
    id: str
    name: str
    entity_type: str


class EntitiesResponse(BaseModel):
    items: list[EntityResponse]


class ImpactRequest(BaseModel):
    user_id: str
    entity_name: str
    direction: str = "inbound"  # inbound = 改X会影响谁; outbound = X依赖谁
    max_hops: Optional[int] = Field(default=None, ge=1, le=5)
    tenant_id: Optional[str] = None


class ImpactEdgeResponse(BaseModel):
    relation_type: str
    weight: float
    from_name: Optional[str] = None
    to_name: Optional[str] = None


class ImpactPathResponse(BaseModel):
    hops: int
    nodes: list[EntityResponse]
    edges: list[ImpactEdgeResponse]


class ImpactResponse(BaseModel):
    seed: EntityResponse
    paths: list[ImpactPathResponse]
    direction: str
    max_hops: int
    recommendations: list[RecommendationResponse] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    user_id: str
    answer_id: str
    feedback_type: str  # upvote | downvote | correct
    session_id: Optional[str] = None
    tenant_id: Optional[str] = None
    correction_text: Optional[str] = None
    related_memory_ids: list[str] = Field(default_factory=list)
    answer_text: Optional[str] = None
    async_mode: Optional[bool] = None


class ReflectionResponse(BaseModel):
    id: str
    status: str
    confidence: float
    summary: str
    analysis: str = ""
    derived_memory_id: Optional[str] = None


class FeedbackResponse(BaseModel):
    feedback_id: str
    reflection: Optional[ReflectionResponse] = None
    async_pending: bool = False


class L3DumpRequest(BaseModel):
    user_id: Optional[str] = None


class L3DumpResponse(BaseModel):
    archive_id: str
    uri: str
    checksum: str
    memory_count: int
    entity_count: int
    relation_count: int


class L3ArchiveItem(BaseModel):
    id: str
    uri: str
    checksum: str
    memory_count: int
    entity_count: int
    relation_count: int
    created_at: str


class L3ArchiveListResponse(BaseModel):
    items: list[L3ArchiveItem]


class ConsolidateRequest(BaseModel):
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None


class ConsolidateUserReport(BaseModel):
    user_id: str
    reweighted: int
    forgotten: int
    compressed_clusters: int
    compressed_deleted: int
    conflicts_resolved: int
    summary_memory_ids: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)


class ConsolidateResponse(BaseModel):
    reports: list[ConsolidateUserReport]


class ReembedRequest(BaseModel):
    user_id: Optional[str] = None
    orphan_policy: str = Field(default="assign", pattern="^(assign|skip|fail)$")
    orphan_user_id: Optional[str] = None
    batch_size: int = Field(default=32, ge=1, le=512)
    force: bool = False
    dry_run: bool = False
    cleanup_dangling: bool = True
    recreate_collection: bool = False


class ReembedResponse(BaseModel):
    scanned: int
    reembedded: int
    skipped_current: int
    orphans_assigned: int
    orphans_skipped: int
    dangling_vectors_removed: int
    errors: list[str] = Field(default_factory=list)
    target_model: str
    target_dim: int
    dry_run: bool


class MetricsResponse(BaseModel):
    counters: dict[str, int]
