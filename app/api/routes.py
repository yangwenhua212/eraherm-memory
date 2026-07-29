# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app import __version__
from app.api.schemas import (
    CloseSessionResponse,
    ConsolidateRequest,
    ConsolidateResponse,
    ConsolidateUserReport,
    CreateSessionRequest,
    EntitiesResponse,
    EntityResponse,
    ErrorBody,
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    GraphExtractRequest,
    GraphExtractResponse,
    HealthResponse,
    ImpactEdgeResponse,
    ImpactPathResponse,
    ImpactRequest,
    ImpactResponse,
    L3ArchiveItem,
    L3ArchiveListResponse,
    L3DumpRequest,
    L3DumpResponse,
    MemoryAlertResponse,
    MetricsResponse,
    PinRequest,
    RecallItemResponse,
    RecallRequest,
    RecallResponse,
    RecommendationResponse,
    ReflectionResponse,
    ReembedRequest,
    ReembedResponse,
    RememberRequest,
    RememberResponse,
    SessionResponse,
)
from app.archive.service import L3ArchiveService
from app.consolidate.service import ConsolidationService
from app.feedback.service import FeedbackService
from app.graph.service import GraphService
from app.memory.service import MemoryService
from app.observability.metrics import METRICS

router = APIRouter(prefix="/v1")


def _svc(request: Request) -> MemoryService:
    return request.app.state.memory_service


def _graph(request: Request) -> GraphService:
    return request.app.state.graph_service


def _feedback(request: Request) -> FeedbackService:
    return request.app.state.feedback_service


def _l3(request: Request) -> L3ArchiveService:
    return request.app.state.l3_service


def _consolidate(request: Request) -> ConsolidationService | None:
    return getattr(request.app.state, "consolidation_service", None)


def _require_admin(request: Request, token: str | None) -> JSONResponse | None:
    expected = getattr(request.app.state, "settings", None)
    admin = expected.admin_token if expected is not None else "dev-admin-token"
    if not token or token != admin:
        return _err(401, "unauthorized", "invalid admin token")
    return None


def _err(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or {}))
    return JSONResponse(status_code=status, content=body.model_dump())


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={200: {"content": {"text/html": {"schema": {"type": "string"}}}}},
)
def health(request: Request) -> HealthResponse | HTMLResponse:
    payload = HealthResponse(status="ok", version=__version__)
    accept = (request.headers.get("accept") or "").lower()
    # Browsers often render bare JSON as a blank-looking tab; give a tiny HTML page.
    if "text/html" in accept and not accept.strip().startswith("application/json"):
        return HTMLResponse(
            f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/><title>EraHerm health</title>
<style>body{{font-family:system-ui,sans-serif;background:#0f1419;color:#e7eef7;padding:2rem}}
code{{color:#9fd0ff}}</style></head>
<body>
<h1>EraHerm-Memory</h1>
<p>status: <code>{payload.status}</code></p>
<p>version: <code>{payload.version}</code></p>
<p><a href="/demo/" style="color:#3d9cf0">打开 Demo</a>
 · <a href="/docs" style="color:#3d9cf0">API 文档</a></p>
</body></html>"""
        )
    return payload


@router.get("/metrics", response_model=MetricsResponse)
def metrics() -> MetricsResponse:
    return MetricsResponse(counters=METRICS.snapshot())


@router.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session(
    body: CreateSessionRequest,
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> SessionResponse:
    user_id = body.user_id or x_user_id
    tenant_id = body.tenant_id or x_tenant_id
    row = _svc(request).create_session(user_id=user_id, tenant_id=tenant_id, meta=body.meta)
    return SessionResponse(id=row.id, status=row.status, created_at=row.created_at)


@router.post("/sessions/{session_id}/close", response_model=CloseSessionResponse)
def close_session(session_id: str, request: Request) -> CloseSessionResponse | JSONResponse:
    try:
        result = _svc(request).close_session(session_id)
    except KeyError as exc:
        return _err(404, "not_found", str(exc))
    except ValueError as exc:
        return _err(409, "conflict", str(exc))
    return CloseSessionResponse(
        id=result.id,
        status=result.status,
        promoted_count=result.promoted_count,
        dropped_count=result.dropped_count,
    )


@router.post("/memories", response_model=RememberResponse, status_code=201)
def remember(
    body: RememberRequest,
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> RememberResponse:
    user_id = body.user_id or x_user_id
    tenant_id = body.tenant_id or x_tenant_id
    result = _svc(request).remember(
        content=body.content,
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=body.session_id,
        memory_type=body.memory_type,
        importance=body.importance,
        pinned=body.pinned,
        extract_graph=body.extract_graph,
        meta=body.meta,
    )
    METRICS.incr("remember_total")
    return RememberResponse(
        id=result.id,
        layer=result.layer,
        pinned=result.pinned,
        entities_extracted=result.entities_extracted,
        relations_extracted=result.relations_extracted,
        alerts=[
            MemoryAlertResponse(
                type=a.type,
                severity=a.severity,
                message=a.message,
                related_memory_ids=a.related_memory_ids,
            )
            for a in result.alerts
        ],
    )


@router.post("/memories/pin", response_model=RememberResponse)
def pin_memory(
    body: PinRequest,
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> RememberResponse | JSONResponse:
    svc = _svc(request)
    try:
        if body.memory_id:
            row = svc.pin_existing(body.memory_id, pinned=body.pinned)
            return RememberResponse(id=row.id, layer="L2", pinned=row.pinned)
        user_id = body.user_id or x_user_id
        if not user_id or not body.content:
            return _err(400, "validation_error", "user_id and content required when memory_id omitted")
        result = svc.pin_new(
            content=body.content,
            user_id=user_id,
            memory_type=body.memory_type,
            tenant_id=body.tenant_id or x_tenant_id,
            session_id=body.session_id,
            importance=body.importance,
            meta=body.meta,
        )
        return RememberResponse(
            id=result.id,
            layer=result.layer,
            pinned=result.pinned,
            entities_extracted=result.entities_extracted,
            relations_extracted=result.relations_extracted,
        )
    except KeyError as exc:
        return _err(404, "not_found", str(exc))
    except ValueError as exc:
        return _err(400, "validation_error", str(exc))


@router.post("/recall", response_model=RecallResponse)
def recall(body: RecallRequest, request: Request) -> RecallResponse:
    svc = _svc(request)
    items = svc.recall(
        user_id=body.user_id,
        query=body.query,
        session_id=body.session_id,
        tenant_id=body.tenant_id,
        top_k=body.top_k,
        include_pinned=body.include_pinned,
        min_score=body.min_score,
    )
    recs = svc.recommend_sidecar(
        user_id=body.user_id,
        query=body.query,
        exclude_memory_ids=[i.id for i in items],
        reason="similar_topic",
        tenant_id=body.tenant_id,
    )
    METRICS.incr("recall_total")
    return RecallResponse(
        items=[
            RecallItemResponse(
                id=i.id,
                content=i.content,
                memory_type=i.memory_type,
                score=i.score,
                pinned=i.pinned,
                layer=i.layer,
            )
            for i in items
        ],
        recommendations=[
            RecommendationResponse(
                memory_id=r.memory_id,
                content=r.content,
                score=r.score,
                reason=r.reason,
            )
            for r in recs
        ],
    )


@router.post("/graph/extract", response_model=GraphExtractResponse)
def graph_extract(body: GraphExtractRequest, request: Request) -> GraphExtractResponse | JSONResponse:
    try:
        result = _graph(request).extract(
            user_id=body.user_id,
            text=body.text,
            memory_id=body.memory_id,
            tenant_id=body.tenant_id,
        )
    except KeyError as exc:
        return _err(404, "not_found", str(exc))
    except ValueError as exc:
        return _err(400, "validation_error", str(exc))

    summaries = [
        f"{r.from_name} -[{r.relation_type}]-> {r.to_name}" for r in result.extraction.relations
    ]
    METRICS.incr("graph_extract_total")
    return GraphExtractResponse(
        entities=result.entities,
        relations=result.relations,
        entity_names=[e.name for e in result.extraction.entities],
        relation_summaries=summaries,
    )


@router.get("/graph/entities", response_model=EntitiesResponse)
def graph_entities(
    request: Request,
    user_id: str = Query(...),
    q: str | None = Query(default=None),
    type: str | None = Query(default=None, alias="type"),
    tenant_id: str | None = Query(default=None),
) -> EntitiesResponse:
    rows = _graph(request).list_entities(
        user_id=user_id, q=q, entity_type=type, tenant_id=tenant_id
    )
    return EntitiesResponse(
        items=[EntityResponse(id=r.id, name=r.name, entity_type=r.entity_type) for r in rows]
    )


@router.post("/graph/impact", response_model=ImpactResponse)
def graph_impact(body: ImpactRequest, request: Request) -> ImpactResponse | JSONResponse:
    try:
        result = _graph(request).impact(
            user_id=body.user_id,
            entity_name=body.entity_name,
            direction=body.direction,
            max_hops=body.max_hops,
            tenant_id=body.tenant_id,
        )
    except KeyError as exc:
        return _err(404, "not_found", str(exc))
    except ValueError as exc:
        return _err(400, "validation_error", str(exc))

    id_to_name = {result.seed.id: result.seed.name}
    for path in result.paths:
        for node in path.nodes:
            id_to_name[node.id] = node.name

    METRICS.incr("graph_impact_total")
    recs = _svc(request).recommend_sidecar(
        user_id=body.user_id,
        query=f"改动 {body.entity_name} 相关经验 影响 依赖",
        reason="similar_change_experience",
        tenant_id=body.tenant_id,
    )
    return ImpactResponse(
        seed=EntityResponse(
            id=result.seed.id, name=result.seed.name, entity_type=result.seed.entity_type
        ),
        paths=[
            ImpactPathResponse(
                hops=p.hops,
                nodes=[
                    EntityResponse(id=n.id, name=n.name, entity_type=n.entity_type) for n in p.nodes
                ],
                edges=[
                    ImpactEdgeResponse(
                        relation_type=e.relation_type,
                        weight=e.weight,
                        from_name=id_to_name.get(e.from_entity_id),
                        to_name=id_to_name.get(e.to_entity_id),
                    )
                    for e in p.edges
                ],
            )
            for p in result.paths
        ],
        direction=result.direction,
        max_hops=result.max_hops,
        recommendations=[
            RecommendationResponse(
                memory_id=r.memory_id,
                content=r.content,
                score=r.score,
                reason=r.reason,
            )
            for r in recs
        ],
    )


@router.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(body: FeedbackRequest, request: Request) -> FeedbackResponse | JSONResponse:
    try:
        result = _feedback(request).submit(
            user_id=body.user_id,
            answer_id=body.answer_id,
            feedback_type=body.feedback_type,
            session_id=body.session_id,
            tenant_id=body.tenant_id,
            correction_text=body.correction_text,
            related_memory_ids=body.related_memory_ids,
            answer_text=body.answer_text,
            async_mode=body.async_mode,
        )
    except ValueError as exc:
        return _err(400, "validation_error", str(exc))
    except Exception as exc:  # noqa: BLE001
        return _err(502, "llm_failed", f"reflection failed: {exc}")

    METRICS.incr("feedback_total")
    METRICS.incr(f"feedback_{body.feedback_type}")

    reflection = None
    if result.reflection is not None:
        reflection = ReflectionResponse(
            id=result.reflection.id,
            status=result.reflection.status,
            confidence=result.reflection.confidence,
            summary=result.reflection.summary,
            analysis=result.reflection.analysis,
            derived_memory_id=result.reflection.derived_memory_id,
        )
    return FeedbackResponse(
        feedback_id=result.feedback_id,
        reflection=reflection,
        async_pending=result.async_pending,
    )


@router.get("/feedback/{feedback_id}", response_model=FeedbackResponse)
def get_feedback(feedback_id: str, request: Request) -> FeedbackResponse | JSONResponse:
    try:
        result = _feedback(request).get(feedback_id)
    except KeyError as exc:
        return _err(404, "not_found", str(exc))
    reflection = None
    if result.reflection is not None:
        reflection = ReflectionResponse(
            id=result.reflection.id,
            status=result.reflection.status,
            confidence=result.reflection.confidence,
            summary=result.reflection.summary,
            analysis=result.reflection.analysis,
            derived_memory_id=result.reflection.derived_memory_id,
        )
    return FeedbackResponse(
        feedback_id=result.feedback_id,
        reflection=reflection,
        async_pending=result.async_pending,
    )


@router.post("/admin/consolidate", response_model=ConsolidateResponse)
def admin_consolidate(
    body: ConsolidateRequest,
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> ConsolidateResponse | JSONResponse:
    denied = _require_admin(request, x_admin_token)
    if denied is not None:
        return denied
    svc = _consolidate(request)
    if svc is None:
        return _err(503, "unavailable", "consolidation service not configured")
    if body.user_id:
        reports = [svc.run_for_user(body.user_id, tenant_id=body.tenant_id)]
    else:
        reports = svc.run_all(tenant_id=body.tenant_id)
    METRICS.incr("consolidate_total")
    return ConsolidateResponse(
        reports=[
            ConsolidateUserReport(
                user_id=r.user_id,
                reweighted=r.reweighted,
                forgotten=r.forgotten,
                compressed_clusters=r.compressed_clusters,
                compressed_deleted=r.compressed_deleted,
                conflicts_resolved=r.conflicts_resolved,
                summary_memory_ids=r.summary_memory_ids,
                details=r.details,
            )
            for r in reports
        ]
    )


@router.post("/admin/reembed", response_model=ReembedResponse)
def admin_reembed(
    body: ReembedRequest,
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> ReembedResponse | JSONResponse:
    denied = _require_admin(request, x_admin_token)
    if denied is not None:
        return denied
    mem = _svc(request)
    from app.migrate.service import ReembedService

    report = ReembedService(
        repo=mem.repo,
        embedding=mem.embedding,
        vectors=mem.vectors,
        settings=request.app.state.settings,
    ).run(
        user_id=body.user_id,
        orphan_policy=body.orphan_policy,  # type: ignore[arg-type]
        orphan_user_id=body.orphan_user_id,
        batch_size=body.batch_size,
        force=body.force,
        dry_run=body.dry_run,
        cleanup_dangling=body.cleanup_dangling,
        recreate_collection=body.recreate_collection,
    )
    METRICS.incr("reembed_total")
    if report.errors and report.reembedded == 0:
        return _err(400, "reembed_failed", report.errors[0], details=report.to_dict())
    return ReembedResponse(**report.to_dict())


@router.post("/admin/l3/dump", response_model=L3DumpResponse)
def admin_l3_dump(
    body: L3DumpRequest,
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> L3DumpResponse | JSONResponse:
    denied = _require_admin(request, x_admin_token)
    if denied is not None:
        return denied
    result = _l3(request).dump(user_id=body.user_id)
    METRICS.incr("l3_dump_total")
    return L3DumpResponse(
        archive_id=result.archive_id,
        uri=result.uri,
        checksum=result.checksum,
        memory_count=result.memory_count,
        entity_count=result.entity_count,
        relation_count=result.relation_count,
    )


@router.get("/admin/l3/archives", response_model=L3ArchiveListResponse)
def admin_l3_list(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    limit: int = Query(default=20, ge=1, le=100),
) -> L3ArchiveListResponse | JSONResponse:
    denied = _require_admin(request, x_admin_token)
    if denied is not None:
        return denied
    rows = _l3(request).list_archives(limit=limit)
    return L3ArchiveListResponse(
        items=[
            L3ArchiveItem(
                id=r.id,
                uri=r.uri,
                checksum=r.checksum,
                memory_count=r.memory_count,
                entity_count=r.entity_count,
                relation_count=r.relation_count,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )
