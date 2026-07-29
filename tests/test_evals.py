# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md

from __future__ import annotations

from pathlib import Path

from evals.harness import run_evals


def test_eval_suite_all_pass():
    cases = Path(__file__).resolve().parents[1] / "evals" / "cases.json"
    report = run_evals(cases)
    failed = [r for r in report.results if not r.passed]
    assert not failed, {r.id: r.detail for r in failed}
    assert report.passed >= 6


def test_fallback_extractor_uses_rules_when_primary_empty():
    from app.adapters.llm_graph_extractor import FallbackGraphExtractor
    from app.graph.extractor import RuleGraphExtractor
    from app.ports.graph_store import ExtractionResult

    class Empty:
        def extract(self, text: str) -> ExtractionResult:
            return ExtractionResult()

    ext = FallbackGraphExtractor(Empty(), fallback=RuleGraphExtractor())
    result = ext.extract("A服务依赖B服务")
    assert any(r.relation_type == "depends_on" for r in result.relations)
