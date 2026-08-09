# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Hermes ↔ EraHerm-Memory demos.

Prefer importing from the SDK (stable for Hermes repos)::

    from eraherm_memory import MemoryClient, HermesMemoryBridge, HermesMemoryTools

Built-in tools (no curl)::

    python examples/hermes_builtin_tools.py --base-url http://127.0.0.1:8000

Turn-loop bridge::

    python examples/hermes_memory_adapter.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse

from eraherm_memory import HermesMemoryBridge, MemoryClient


def _demo(base_url: str) -> None:
    def print_alerts(alerts: list) -> None:
        for a in alerts:
            print(f"  ! alert[{a.get('type')}] {a.get('message')}")

    with MemoryClient(base_url) as client:
        print("health:", client.health())
        bridge = HermesMemoryBridge(
            client,
            user_id="hermes_demo",
            on_alerts=print_alerts,
        )
        print("session:", bridge.session_id)

        client.remember(
            content="Hermes 项目 API 层使用 FastAPI",
            user_id="hermes_demo",
            session_id=bridge.session_id,
            importance=0.9,
        )
        client.remember(
            content="A服务依赖B服务和Redis。C服务依赖A服务。",
            user_id="hermes_demo",
            session_id=bridge.session_id,
            importance=0.9,
            extract_graph=True,
        )

        user_q = "我们项目 API 用什么？改 A服务 会影响谁？"
        ctx = bridge.before_turn(user_q)
        print("\n-- system suffix --\n", bridge.build_system_suffix(ctx))

        answer = "根据记忆，API 用 FastAPI；改 A服务 可能影响 C服务。"
        print("\n-- hermes answer --\n", answer)

        post = bridge.after_turn(
            "请记住：数据库我们用 PostgreSQL",
            answer,
            answer_id="turn_1",
        )
        print("remembered:", [m.get("id") for m in post.remembered])

        wrong_answer = "你们用 MySQL"
        fb = bridge.after_turn(
            "不对，应该是 PostgreSQL 不是 MySQL",
            wrong_answer,
            answer_id="turn_2",
        )
        print("feedback:", fb.feedback)

        ctx2 = bridge.before_turn("数据库是什么")
        print("\n-- recall after correct --\n", ctx2.recall_block)

        closed = bridge.end_session()
        print("session closed:", closed)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes memory bridge demo")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    _demo(args.base_url)


if __name__ == "__main__":
    main()
