# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""One-shot regression: 纠正即进化（给你自己用，不依赖外人）。

流程：写入错误事实 → feedback correct → 同义再问 → 新事实必须排第一。

  uvicorn app.main:app --port 8000
  python examples/correct_to_evolve.py --base-url http://127.0.0.1:8000

退出码：0 通过；1 失败。
"""

from __future__ import annotations

import argparse
import sys

from eraherm_memory import MemoryClient


def run(base_url: str, user_id: str) -> int:
    with MemoryClient(base_url) as client:
        health = client.health()
        print("health:", health.get("version"), health.get("status"))

        sess = client.create_session(user_id=user_id, meta={"demo": "correct_to_evolve"})
        sid = sess["id"]
        print("session:", sid)

        wrong = client.remember(
            content="数据库使用 MySQL",
            user_id=user_id,
            session_id=sid,
            importance=0.9,
            pinned=False,
            extract_graph=False,
        )
        print("seed wrong:", wrong.get("id"), "→ 数据库使用 MySQL")

        fb = client.feedback(
            user_id=user_id,
            answer_id="correct_to_evolve_1",
            feedback_type="correct",
            correction_text="应该是 PostgreSQL 不是 MySQL",
            related_memory_ids=[wrong["id"]],
            answer_text="你们用 MySQL",
            session_id=sid,
            async_mode=False,
        )
        reflection = (fb.get("reflection") or {}).get("status")
        print("feedback:", fb.get("feedback_id"), "reflection=", reflection)

        recall = client.recall(
            user_id=user_id,
            query="我们数据库用什么",
            session_id=sid,
            top_k=5,
        )
        items = recall.get("items") or []
        print("\n-- recall after correct --")
        for i, it in enumerate(items, 1):
            pin = " [pinned]" if it.get("pinned") else ""
            print(f"  {i}. score={it.get('score', 0):.3f}{pin} | {it.get('content')}")

        if not items:
            print("FAIL: recall empty（检查 embedding / min_score / user_id）", file=sys.stderr)
            client.close_session(sid)
            return 1

        top = items[0].get("content") or ""
        if "PostgreSQL" not in top:
            print(
                f"FAIL: top hit 不是纠正后的事实（got: {top!r}）",
                file=sys.stderr,
            )
            client.close_session(sid)
            return 1

        contents = [i.get("content") or "" for i in items]
        if any("MySQL" in c and "PostgreSQL" not in c for c in contents):
            mysql_rank = next(
                i for i, c in enumerate(contents) if "MySQL" in c and "PostgreSQL" not in c
            )
            pg_rank = next(i for i, c in enumerate(contents) if "PostgreSQL" in c)
            if pg_rank > mysql_rank:
                print(
                    f"FAIL: PostgreSQL 排名 {pg_rank + 1} 低于旧 MySQL 排名 {mysql_rank + 1}",
                    file=sys.stderr,
                )
                client.close_session(sid)
                return 1

        client.close_session(sid)
        print("\nPASS: 纠正即进化 — 新事实优先")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Correct-to-evolve smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user-id", default="u_correct_demo")
    args = parser.parse_args()
    raise SystemExit(run(args.base_url, args.user_id))


if __name__ == "__main__":
    main()
