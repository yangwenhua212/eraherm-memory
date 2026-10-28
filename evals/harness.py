# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""In-process eval harness for EraHerm-Memory core capabilities.

设计取舍（为什么长这样）：

- **一次构建、串行跑完所有用例**：库只建一次，省掉每条用例重新建库的开销；
  代价是用例之间共享同一份 SQLite，所以每条用例必须用独立 ``user_id``。
- **门禁是默认打开的**：``recall_min_score=0.0`` 只把「旧绝对分门禁」那一档折算成
  0.0，零词法档仍然停在 ``recall_rel_min_no_lexical``（默认 0.55）。这正是
  ADR 0010 说的那道门 —— 评测必须让它参与，所以负例都设计成「零词法重叠」，
  走的就是最严的那条路径。
- **不发明数字**：``recall_at_k`` / ``mrr`` 全部由真实召回列表算出；某一步没有写
  期望就完全不参与统计。延迟只作为 ``--strict`` 下的**冒烟预算**（进程内 hashing
  嵌入），不是 benchmark。

新断言（写在用例 ``steps`` 里）：

- ``recall``：``expect_empty`` / ``expect_top1_contains`` / ``expect_min_items`` /
  ``expect_max_items`` / ``expect_absent_contains``（配 ``as_user_id`` 做跨用户隔离）。
- ``remember``：``expect_persisted``。
- 用例级：``requires_semantic_embedding`` —— 只有真语义嵌入才有意义的用例，
  默认跳过（不失败），需 ``ERAHERM_EVAL_SEMANTIC=1`` 才执行。
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.adapters.hashing_embedding import HashingEmbeddingClient
from app.adapters.heuristic_reflection import HeuristicReflectionPipeline
from app.adapters.memory_session_cache import InMemorySessionCache
from app.adapters.networkx_graph_store import NetworkXSqliteGraphStore
from app.adapters.sqlite_feedback_store import SqliteFeedbackStore
from app.adapters.sqlite_memory_repo import SqliteMemoryRepository
from app.adapters.sqlite_vector_store import SqliteVectorStore
from app.config import Settings
from app.feedback.service import FeedbackService
from app.graph.extractor import RuleGraphExtractor
from app.graph.service import GraphService
from app.memory.service import MemoryService
from app.ports.clock import SystemClock
from app.proactive.service import ProactiveService

#: 真语义嵌入用例的开关：默认跳过，只有显式打开才执行
SEMANTIC_ENV = "ERAHERM_EVAL_SEMANTIC"

#: ``--strict`` 的默认冒烟延迟预算（毫秒/用例）
DEFAULT_MAX_MS = 500.0


@dataclass
class CaseResult:
    id: str
    suite: str
    passed: bool
    detail: str = ""
    #: 被跳过（而非失败）的原因，例如需要真语义嵌入
    skip_reason: str = ""
    #: 本用例墙钟耗时（毫秒）
    duration_ms: float = 0.0
    #: 参与 recall_at_k / mrr 的召回步骤数（即「有期望」的步骤数）
    retrieval_total: int = 0
    #: 其中被满足的步骤数
    retrieval_hits: int = 0
    #: 各步骤首个命中项的倒数排名之和（无命中记 0）
    rr_sum: float = 0.0

    @property
    def skipped(self) -> bool:
        return bool(self.skip_reason)


@dataclass
class EvalReport:
    results: list[CaseResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.skipped)

    @property
    def total_ms(self) -> float:
        return sum(r.duration_ms for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        durations = [r.duration_ms for r in self.results]
        hits = sum(r.retrieval_hits for r in self.results)
        total = sum(r.retrieval_total for r in self.results)
        return {
            "total": len(self.results),
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_ms": round(self.total_ms, 3),
            "p50_ms": round(_percentile(durations, 50.0), 3),
            "p95_ms": round(_percentile(durations, 95.0), 3),
            "total_ms": round(self.total_ms, 3),
            # 只在「有召回期望」的步骤上统计；没有期望的步骤不参与
            "recall_at_k": round(hits / total, 4) if total else None,
            "mrr": round(sum(r.rr_sum for r in self.results) / total, 4) if total else None,
            "retrieval_expectations": total,
            "results": [
                {
                    "id": r.id,
                    "suite": r.suite,
                    "passed": r.passed,
                    "skipped": r.skipped,
                    "skip_reason": r.skip_reason or None,
                    "detail": r.detail,
                    "duration_ms": round(r.duration_ms, 3),
                    "retrieval_total": r.retrieval_total,
                    "retrieval_hits": r.retrieval_hits,
                    "rr_sum": round(r.rr_sum, 4),
                }
                for r in self.results
            ],
        }


def _percentile(values: list[float], pct: float) -> float:
    """最近秩百分位（nearest-rank）；样本为空时返回 0.0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(pct / 100.0 * len(ordered) + 0.5))))
    return ordered[rank - 1]


def _as_list(value: Any) -> list[Any]:
    """允许用例把期望写成单个字符串或列表两种形式。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _runs_semantic(marked: bool) -> bool:
    """``requires_semantic_embedding: true`` 的用例只有显式打开才执行。"""
    if not marked:
        return True
    return (os.environ.get(SEMANTIC_ENV) or "").strip() == "1"


def _first_rank_for(haystack: list[str], needles: list[str]) -> int:
    """返回第一个命中任一 ``needle`` 的位置（1 基），没命中返回 0。"""
    for idx, candidate in enumerate(haystack, start=1):
        if any(needle in candidate for needle in needles):
            return idx
    return 0


def _build_services(tmp: Path):
    db = tmp / "eval.db"
    settings = Settings(
        data_dir=tmp,
        database_url=f"sqlite:///{db.as_posix()}",
        extract_on_remember=False,
        auto_importance=True,
        embedding_backend="hashing",
        embedding_dim=128,
        json_logs=False,
        log_level="WARNING",
        proactive_alerts_enabled=True,
        proactive_recommend_enabled=True,
        alert_similarity_threshold=0.2,
        recommend_min_score=0.05,
        recall_min_score=0.0,
    )
    settings.ensure_dirs()
    repo = SqliteMemoryRepository(settings.database_url)
    vectors = SqliteVectorStore(settings.database_url, engine=repo.engine)
    graph_store = NetworkXSqliteGraphStore(repo.engine)
    graph = GraphService(
        store=graph_store,
        extractor=RuleGraphExtractor(),
        settings=settings,
        memory_repo=repo,
    )
    embedding = HashingEmbeddingClient(dimensions=settings.embedding_dim)
    proactive = ProactiveService(
        repo=repo, embedding=embedding, vectors=vectors, settings=settings
    )
    memory = MemoryService(
        repo=repo,
        cache=InMemorySessionCache(),
        settings=settings,
        clock=SystemClock(),
        embedding=embedding,
        vectors=vectors,
        graph_service=graph,
        proactive=proactive,
    )
    feedback = FeedbackService(
        store=SqliteFeedbackStore(repo.engine),
        memory=memory,
        reflection=HeuristicReflectionPipeline(),
        settings=settings,
        clock=SystemClock(),
    )
    return memory, graph, feedback, repo.engine


def _run_case(
    case: dict[str, Any],
    memory: MemoryService,
    graph: GraphService,
    feedback: FeedbackService,
) -> CaseResult:
    cid = case["id"]
    suite = case.get("suite", "misc")
    vars: dict[str, Any] = {"session_id": None}
    #: 有召回期望的步骤：这些才参与 recall_at_k / mrr
    retrieval_total = 0
    retrieval_hits = 0
    rr_sum = 0.0
    try:
        for step in case["steps"]:
            op = step["op"]
            if op == "session_create":
                sess = memory.create_session(user_id=step["user_id"])
                vars["session_id"] = sess.id
            elif op == "session_close":
                if not vars["session_id"]:
                    raise AssertionError("no open session")
                memory.close_session(vars["session_id"])
                vars["session_id"] = None
            elif op == "remember":
                result = memory.remember(
                    content=step["content"],
                    user_id=step["user_id"],
                    session_id=vars.get("session_id"),
                    memory_type=step.get("memory_type", "fact"),
                    importance=float(step.get("importance", 0.5)),
                    pinned=bool(step.get("pinned", False)),
                    extract_graph=bool(step.get("extract_graph", False)),
                )
                if "save_as" in step:
                    vars[step["save_as"]] = result.id
                if "expect_persisted" in step:
                    want = bool(step["expect_persisted"])
                    got = getattr(result, "persisted", None)
                    if got is None:
                        raise AssertionError(
                            "kernel RememberResult lacks `persisted`; cannot assert "
                            "expect_persisted (harness stays compatible with older kernels)"
                        )
                    if bool(got) != want:
                        reason = getattr(result, "drop_reason", None)
                        raise AssertionError(
                            f"persisted={got!r} != expected {want!r}; "
                            f"layer={result.layer!r} importance={result.importance:.2f} "
                            f"drop_reason={reason!r}"
                        )
                expect_types = step.get("expect_alert_types")
                if expect_types:
                    got = {a.type for a in result.alerts}
                    for t in expect_types:
                        if t not in got:
                            raise AssertionError(
                                f"alert type {t!r} missing; got={sorted(got)!r} "
                                f"msgs={[a.message for a in result.alerts]!r}"
                            )
            elif op == "recall":
                hits = memory.recall(
                    user_id=step["user_id"],
                    query=step["query"],
                    session_id=None,
                    top_k=int(step.get("top_k", 8)),
                )
                contents = [h.content for h in hits]
                any_needles = _as_list(step.get("expect_any_contains"))
                top1 = step.get("expect_top1_contains")
                top1_needles = _as_list(top1)
                # 一个步骤的「召回期望」= 任意命中 + top1 命中（负例不计入）
                expected = any_needles + top1_needles
                if expected:
                    retrieval_total += 1
                    rank = _first_rank_for(contents, expected)
                    if rank == 1:
                        retrieval_hits += 1
                    rr_sum += (1.0 / rank) if rank else 0.0
                if step.get("expect_empty") and contents:
                    raise AssertionError(
                        f"expected no recall hits; got {len(contents)}: {contents!r}"
                    )
                for needle in any_needles:
                    if not any(needle in c for c in contents):
                        raise AssertionError(
                            f"recall missing {needle!r}; got={contents!r}"
                        )
                if top1_needles:
                    if not contents:
                        raise AssertionError(
                            f"recall returned nothing; want top1 containing {top1_needles!r}"
                        )
                    if not any(needle in contents[0] for needle in top1_needles):
                        raise AssertionError(
                            f"top1 {contents[0]!r} does not contain {top1_needles!r}; "
                            f"got={contents!r}"
                        )
                if "expect_min_items" in step and len(contents) < int(step["expect_min_items"]):
                    raise AssertionError(
                        f"got {len(contents)} items < expect_min_items "
                        f"{step['expect_min_items']}; got={contents!r}"
                    )
                if "expect_max_items" in step and len(contents) > int(step["expect_max_items"]):
                    raise AssertionError(
                        f"got {len(contents)} items > expect_max_items "
                        f"{step['expect_max_items']}; got={contents!r}"
                    )
                absent = _as_list(step.get("expect_absent_contains"))
                if absent:
                    other_user = step.get("as_user_id")
                    if not other_user:
                        raise AssertionError(
                            "expect_absent_contains requires as_user_id "
                            "(otherwise it is the same query as above)"
                        )
                    other_hits = memory.recall(
                        user_id=other_user,
                        query=step["query"],
                        session_id=None,
                        top_k=int(step.get("top_k", 8)),
                    )
                    other_contents = [h.content for h in other_hits]
                    leaked = [
                        c for c in other_contents
                        if any(needle in c for needle in absent)
                    ]
                    if leaked:
                        raise AssertionError(
                            f"cross-user leak: user {other_user!r} saw {leaked!r}"
                        )
                expect_rec = step.get("expect_recommend_contains")
                if expect_rec:
                    recs = memory.recommend_sidecar(
                        user_id=step["user_id"],
                        query=step["query"],
                    )
                    rec_contents = [r.content for r in recs]
                    for needle in expect_rec:
                        if not any(needle in c for c in rec_contents):
                            raise AssertionError(
                                f"recommend missing {needle!r}; got={rec_contents!r}"
                            )
            elif op == "extract":
                graph.extract_and_ingest(user_id=step["user_id"], text=step["text"])
            elif op == "impact":
                impact = graph.impact(
                    user_id=step["user_id"],
                    entity_name=step["entity_name"],
                    direction=step.get("direction", "inbound"),
                    max_hops=int(step.get("max_hops", 2)),
                )
                names = {n.name for p in impact.paths for n in p.nodes}
                for expect in step.get("expect_node_names", []):
                    if expect not in names:
                        raise AssertionError(
                            f"impact missing node {expect!r}; got={sorted(names)!r}"
                        )
            elif op == "feedback":
                related = []
                if "related_from" in step:
                    related = [vars[step["related_from"]]]
                result = feedback.submit(
                    user_id=step["user_id"],
                    answer_id=step["answer_id"],
                    feedback_type=step["feedback_type"],
                    correction_text=step.get("correction_text"),
                    related_memory_ids=related,
                    async_mode=False,
                )
                expect = step.get("expect_status")
                if expect:
                    status = result.reflection.status if result.reflection else None
                    if status != expect:
                        raise AssertionError(f"feedback status {status!r} != {expect!r}")
            else:
                raise AssertionError(f"unknown op: {op}")
        return CaseResult(
            id=cid,
            suite=suite,
            passed=True,
            detail="ok",
            retrieval_total=retrieval_total,
            retrieval_hits=retrieval_hits,
            rr_sum=rr_sum,
        )
    except Exception as exc:  # noqa: BLE001
        return CaseResult(
            id=cid,
            suite=suite,
            passed=False,
            detail=str(exc),
            retrieval_total=retrieval_total,
            retrieval_hits=retrieval_hits,
            rr_sum=rr_sum,
        )


def run_evals(cases_path: Path) -> EvalReport:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    report = EvalReport()
    tmp_dir = tempfile.TemporaryDirectory(prefix="eraherm-eval-", ignore_cleanup_errors=True)
    try:
        memory, graph, feedback, engine = _build_services(Path(tmp_dir.name))
        for case in cases:
            cid = case.get("id") or "<missing-id>"
            suite = case.get("suite", "misc")
            if not _runs_semantic(bool(case.get("requires_semantic_embedding", False))):
                report.results.append(
                    CaseResult(
                        id=cid,
                        suite=suite,
                        passed=True,
                        detail=f"skipped: {case.get('description', '')}",
                        skip_reason=(
                            "requires_semantic_embedding: hashing 嵌入下该断言无意义"
                            f"（设 {SEMANTIC_ENV}=1 可执行）"
                        ),
                    )
                )
                continue
            started = time.perf_counter()
            result = _run_case(case, memory, graph, feedback)
            result.duration_ms = (time.perf_counter() - started) * 1000.0
            report.results.append(result)
        engine.dispose()
    finally:
        tmp_dir.cleanup()
    return report


def _render_summary(report: EvalReport, slow: list[CaseResult], max_ms: float) -> str:
    data = report.to_dict()
    fmt = lambda v: "n/a" if v is None else v  # noqa: E731
    lines = [
        "",
        "Summary",
        f"  cases        : {data['total']} total, {data['passed']} passed, "
        f"{data['failed']} failed, {data['skipped']} skipped",
        f"  latency (ms) : p50={data['p50_ms']} p95={data['p95_ms']} total={data['total_ms']}",
        f"  retrieval    : recall_at_k={fmt(data['recall_at_k'])} mrr={fmt(data['mrr'])} "
        f"over {data['retrieval_expectations']} recall expectation(s)",
    ]
    if slow:
        lines.append(f"  strict budget: {len(slow)} case(s) exceeded {max_ms} ms")
        for r in slow:
            lines.append(f"    - {r.suite}/{r.id}: {r.duration_ms:.1f} ms")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run EraHerm-Memory eval suite")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).with_name("cases.json"),
        help="Path to cases.json",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "额外把超过 --max-ms 的用例判为失败。这只是**冒烟延迟预算**"
            "（进程内 hashing 嵌入，非 benchmark），用于抓住数量级退化。"
        ),
    )
    parser.add_argument(
        "--max-ms",
        type=float,
        default=DEFAULT_MAX_MS,
        help=f"--strict 下单条用例的耗时上限（毫秒，默认 {DEFAULT_MAX_MS:g}）",
    )
    args = parser.parse_args(argv)

    report = run_evals(args.cases)
    slow = [
        r for r in report.results
        if not r.skipped and r.duration_ms > args.max_ms
    ]
    if args.json:
        payload = report.to_dict()
        payload["strict"] = bool(args.strict)
        payload["max_ms"] = args.max_ms
        payload["over_budget"] = [r.id for r in slow]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for r in report.results:
            if r.skipped:
                print(f"[SKIP] {r.suite}/{r.id}: {r.skip_reason}")
                continue
            mark = "PASS" if r.passed else "FAIL"
            print(f"[{mark}] {r.suite}/{r.id}: {r.detail} ({r.duration_ms:.1f} ms)")
        print(_render_summary(report, slow if args.strict else [], args.max_ms))
        if args.strict and slow:
            print(
                f"STRICT: {len(slow)} case(s) exceeded the {args.max_ms:g} ms smoke budget"
            )
    if report.failed:
        return 1
    if args.strict and slow:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
