# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from app.models import MemoryType

#: memory_type 的合法取值，直接从枚举派生，避免"文档写了枚举、代码却不校验"的漂移。
#: 以前任意字符串都能通过，而未知类型会落到 importance 的兜底基线 0.5
#: （< 提升阈值 0.6），于是「看起来写入成功、其实什么也没存」。
_MEMORY_TYPE_PATTERN = "^(" + "|".join(m.value for m in MemoryType) + ")$"


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
    # 上限是防「一个请求塞进几 MB 正文再触发一次 embedding」的最低成本护栏。
    # 10000 字远大于正常记忆（线上最长的一条约 2920 字）。
    content: str = Field(min_length=1, max_length=10_000)
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    memory_type: str = Field(default=MemoryType.FACT.value, pattern=_MEMORY_TYPE_PATTERN)
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
    #: 这条记忆是否真的落库了。``layer="L1"`` 且没有 session_id 时不会落盘：
    #: 以前 API 依然返回 201 + id，调用方无从判断。现在显式告知。
    persisted: bool = True
    drop_reason: Optional[str] = Field(
        default=None,
        description="persisted=false 时说明为什么没落库（以及怎么改）",
    )


class PinRequest(BaseModel):
    memory_id: Optional[str] = None
    pinned: bool = True
    user_id: Optional[str] = None
    content: Optional[str] = None
    memory_type: str = Field(
        default=MemoryType.IDENTITY.value, pattern=_MEMORY_TYPE_PATTERN
    )
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
    query: str = Field(min_length=1, max_length=4_000)
    session_id: Optional[str] = None
    tenant_id: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=100)
    include_pinned: bool = True
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
    # 诊断用中间量（2026-10-08 加）：排查「为什么这条召回不到」时不必在客户端重算
    relevance: float = 0.0
    lexical: float = 0.0
    vector_sim: float = 0.0
    base: float = 0.0
    # 命中增稳（2026-10-08 加，ADR 0011）：hit_boost 是被召回次数带来的稳定性倍数，
    # decay_lambda_eff 是应用增稳与半衰期护栏后的实际衰减系数（pinned 恒为 0）。
    hit_boost: float = 1.0
    decay_lambda_eff: float = 0.0


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
    #: 只统计、不落库。整理是破坏性的（软删冲突/低权重、压缩后删原文），
    #: 上线前/调参时先用 dry_run 看一眼会动什么。
    dry_run: bool = False


class ConsolidateUserReport(BaseModel):
    user_id: str
    reweighted: int
    forgotten: int
    compressed_clusters: int
    compressed_deleted: int
    conflicts_resolved: int
    summary_memory_ids: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)
    dry_run: bool = False
    skipped_reason: Optional[str] = None
    archive_id: Optional[str] = None


class ConsolidateResponse(BaseModel):
    reports: list[ConsolidateUserReport]


class RestoreMemoriesRequest(BaseModel):
    """恢复被软删的记忆（整理误删的兜底出口）。二选一：显式 id，或按 user_id 恢复最近若干条。"""

    memory_ids: list[str] = Field(default_factory=list)
    user_id: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=1000)


class RestoreMemoriesResponse(BaseModel):
    restored: int
    memory_ids: list[str] = Field(default_factory=list)


class RestoreArchiveRequest(BaseModel):
    """从 L3 归档 JSON 恢复记忆（只补缺失的，不覆盖已存在的）。"""

    archive_id: str


class RestoreArchiveResponse(BaseModel):
    archive_id: str
    restored_memories: int
    skipped_existing: int
    reembedded: int
    errors: list[str] = Field(default_factory=list)


class WatchdogItemOut(BaseModel):
    kind: str
    title: str
    detail: str
    severity: str = "info"
    related: list[str] = Field(default_factory=list)


class WatchdogRequest(BaseModel):
    user_id: str = Field(default="", description="要巡检的用户；省略则全量巡检所有活跃用户")
    today: Optional[str] = Field(
        default=None, description="YYYY-MM-DD，测试/调试用；默认今天"
    )


class WatchdogResponse(BaseModel):
    items: list[WatchdogItemOut]
    users: list[str] = Field(default_factory=list)


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
