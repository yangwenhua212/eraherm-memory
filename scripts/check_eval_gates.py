# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""离线校验 evals/cases.json 的门禁数学（**不需要 sqlmodel / 数据库**）。

  python scripts/check_eval_gates.py
  python scripts/check_eval_gates.py --all     # 连 requires_semantic_embedding 的用例一起看

存在的理由：``evals/harness.py`` 需要 sqlmodel，因此在缺依赖的环境（或 CI 之外）
跑不了；而「某个 case 会不会被门禁挡掉」纯粹是
``hashing embedding + app/memory/gate.py`` 的数学。这个脚本复刻 harness 的打分路径
（同样的 dim=128 hashing、同样的 relevance 公式、同样的门禁折算），
逐条断言每个 recall step 的期望，用它来回答"为什么这条 case 会失败"。

⚠️ 这是**近似复刻**，不是 harness 本身：它不建 L1/L2、不算 base/衰减、不跑 sidecar。
它的价值在于把"门禁是否放行"和"排序第一名"这两件事从完整链路里单独拎出来验证。
用例调整后请同时跑它和真正的 harness。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIM = 128
DEFAULT_MIN_SCORE = 0.25
DEFAULT_MIN_SCORE_NO_LEXICAL = 0.38
REL_MIN = 0.18
REL_MIN_NO_LEXICAL = 0.55
VECTOR_WEIGHT = 0.7
LEX_LEN_NORM = 300


def _load_gate():
    """直接按路径加载 gate.py —— 它只依赖标准库，导包不会拉起 sqlmodel。"""
    spec = importlib.util.spec_from_file_location("_gate_probe", ROOT / "app" / "memory" / "gate.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_gate_probe"] = module
    spec.loader.exec_module(module)
    return module


def _tokens(text: str) -> list[str]:
    # 与 HashingEmbeddingClient._tokenize 保持一致
    return [
        t
        for t in re.split(r"[\s,.;:!?，。；：！？、/\-_()（）\[\]{}]+", text.lower())
        if t
    ]


def _vector(text: str) -> list[float]:
    vec = [0.0] * DIM
    for token, tf in Counter(_tokens(text) or ["__empty__"]).items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign * (1.0 + math.log(1.0 + tf))
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate eval cases against the recall gate")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include cases marked requires_semantic_embedding (they are expected to fail here)",
    )
    parser.add_argument("--cases", type=Path, default=ROOT / "evals" / "cases.json")
    args = parser.parse_args(argv)

    gate = _load_gate()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))

    rel_min = gate.legacy_relevance_floor(
        0.0, score_default=DEFAULT_MIN_SCORE, relevance_default=REL_MIN
    )
    rel_min_nol = gate.legacy_relevance_floor(
        DEFAULT_MIN_SCORE_NO_LEXICAL,
        score_default=DEFAULT_MIN_SCORE_NO_LEXICAL,
        relevance_default=REL_MIN_NO_LEXICAL,
    )
    print(f"gate floors (harness settings): rel_min={rel_min} rel_min_no_lexical={rel_min_nol}")

    def relevance(query: str, content: str) -> tuple[float, float, float]:
        tokens = gate.tokenize(query)
        lex = gate.length_adjusted_lexical(
            gate.lexical_similarity(content, tokens), len(content), LEX_LEN_NORM
        )
        sim = gate.clamp01(_cosine(_vector(query), _vector(content)))
        return VECTOR_WEIGHT * sim + (1 - VECTOR_WEIGHT) * lex, sim, lex

    problems: list[str] = []
    checked = 0
    skipped = 0
    skipped_feedback = 0
    for case in cases:
        if case.get("requires_semantic_embedding") and not args.all:
            skipped += 1
            continue
        stored: dict[str, list[str]] = {}
        for step in case["steps"]:
            if step["op"] == "remember":
                stored.setdefault(step["user_id"], []).append(step["content"])
        # 纠正（feedback correct）会派生一条**新的**记忆（由反思管线生成，
        # 内容取决于 LLM/启发式，不在这里复刻）。因此纠正之后的 recall 期望
        # 本脚本无法判定 —— 明确跳过并计数，而不是报成"失败"。
        needs_feedback = any(
            s.get("op") == "feedback" and s.get("feedback_type") == "correct"
            for s in case["steps"]
        )
        for step in case["steps"]:
            if step["op"] != "recall":
                continue
            if needs_feedback:
                skipped_feedback += 1
                print(f"-- {case['id']}: skipped（依赖 feedback 派生的记忆，本脚本不复刻反思管线）")
                continue
            checked += 1
            query = step["query"]
            candidates = stored.get(step["user_id"], [])
            scored = []
            for content in candidates:
                rel, sim, lex = relevance(query, content)
                floor = rel_min if lex >= gate.LEX_EVIDENCE_MIN else rel_min_nol
                scored.append((rel >= floor, rel, sim, lex, content))
            live = sorted((x for x in scored if x[0]), key=lambda x: -x[1])
            contents = [x[4] for x in live]

            if step.get("expect_empty") and contents:
                problems.append(f"{case['id']}: expect_empty 但会召回 {contents}")
            top1 = step.get("expect_top1_contains")
            if top1 and (not contents or top1 not in contents[0]):
                problems.append(f"{case['id']}: top1 不含 {top1!r}（实际 {contents}）")
            for needle in step.get("expect_any_contains", []):
                if not any(needle in c for c in contents):
                    problems.append(f"{case['id']}: any_contains 缺 {needle!r}（实际 {contents}）")
            if "expect_min_items" in step and len(contents) < step["expect_min_items"]:
                problems.append(f"{case['id']}: min_items={step['expect_min_items']} 不满足（{len(contents)}）")
            if "expect_max_items" in step and len(contents) > step["expect_max_items"]:
                problems.append(f"{case['id']}: max_items={step['expect_max_items']} 超了（{len(contents)}）")
            if step.get("expect_absent_contains"):
                other = step.get("as_user_id")
                if not other or not stored.get(other):
                    problems.append(f"{case['id']}: as_user_id={other!r} 没有对照记忆，用例没有区分力")
            flag = "OK " if not any(p.startswith(case["id"]) for p in problems) else "!! "
            print(f"{flag}{case['id']}: ranked={[c[:28] for c in contents]}")

    print(
        f"\nchecked recall steps: {checked}  "
        f"skipped(needs real embedding): {skipped}  "
        f"skipped(needs feedback pipeline): {skipped_feedback}  "
        f"problems: {len(problems)}"
    )
    for problem in problems:
        print(f"  !! {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
