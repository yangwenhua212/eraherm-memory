# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Demo: AgentMemory — the five-capability "memory." layer for Agent hosts.

  uvicorn app.main:app --port 8000
  python examples/agent_memory.py

Maps to docs/HERMES_INTEGRATION.md §0::

    memory.learn()      # 从对话/反馈中沉淀
    memory.remember()   # 显式写入事实
    memory.reflect()    # 整理 / 压缩 / 冲突处理
    memory.recall()     # 语义召回
    memory.evolve()     # 纠正即进化（新事实压过旧版）
"""

from __future__ import annotations

import argparse

from eraherm_memory import AgentMemory, MemoryClient


def _demo(base_url: str, admin_token: str) -> None:
    with MemoryClient(base_url) as client:
        memory = AgentMemory(client, user_id="agent_memory_demo")

        print("== remember: 显式写入事实 ==")
        memory.remember("数据库使用 PostgreSQL", pinned=True)

        print("\n== learn: 从对话沉淀事实 ==")
        mem = memory.learn("用户说：项目用 Python 开发，通信走 MCP")
        print("learned:", mem["content"] if mem else None)

        print("\n== recall: 语义召回（换词也能中）==")
        print(memory.recall_text("数据库用的什么"))

        print("\n== evolve: 纠正即进化 ==")
        memory.evolve("数据库用的是 PostgreSQL，不是 MySQL", wrong_answer="MySQL")

        print("\n== recall after correct: 新事实压过旧版 ==")
        print(memory.recall_text("数据库选型"))

        print("\n== reflect: 整理压缩（需 admin token）==")
        out = memory.reflect(admin_token=admin_token)
        print("reports:", len(out.get("reports", [])))

        memory.end_session()
        print("\ndone")


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentMemory five-capability demo")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-token", default="change-me")
    args = parser.parse_args()
    _demo(args.base_url, args.admin_token)


if __name__ == "__main__":
    main()
