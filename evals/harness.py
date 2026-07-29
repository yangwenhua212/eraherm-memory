# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

"""In-process eval harness for EraHerm-Memory core capabilities."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
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


@dataclass
class CaseResult:
    id: str
    suite: str
    passed: bool
    detail: str = ""


@dataclass
class EvalReport:
    results: list[CaseResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": len(self.results),
            "passed": self.passed,
            "failed": self.failed,
            "results": [
                {"id": r.id, "suite": r.suite, "passed": r.passed, "detail": r.detail}
                for r in self.results
            ],
        }


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
                for needle in step.get("expect_any_contains", []):
                    if not any(needle in c for c in contents):
                        raise AssertionError(
                            f"recall missing {needle!r}; got={contents!r}"
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
        return CaseResult(id=cid, suite=suite, passed=True, detail="ok")
    except Exception as exc:  # noqa: BLE001
        return CaseResult(id=cid, suite=suite, passed=False, detail=str(exc))


def run_evals(cases_path: Path) -> EvalReport:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    report = EvalReport()
    tmp_dir = tempfile.TemporaryDirectory(prefix="eraherm-eval-", ignore_cleanup_errors=True)
    try:
        memory, graph, feedback, engine = _build_services(Path(tmp_dir.name))
        for case in cases:
            report.results.append(_run_case(case, memory, graph, feedback))
        engine.dispose()
    finally:
        tmp_dir.cleanup()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run EraHerm-Memory eval suite")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).with_name("cases.json"),
        help="Path to cases.json",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args(argv)

    report = run_evals(args.cases)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        for r in report.results:
            mark = "PASS" if r.passed else "FAIL"
            print(f"[{mark}] {r.suite}/{r.id}: {r.detail}")
        print(f"\nSummary: {report.passed}/{len(report.results)} passed")
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
