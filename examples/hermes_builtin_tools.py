# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Demo: register EraHerm as Hermes built-in tools (no curl).

  uvicorn app.main:app --port 8000
  python examples/hermes_builtin_tools.py

Wire into Hermes roughly like::

    tools = HermesMemoryTools(client, user_id="hermes:boss")
    for spec in tools.openai_tools():
        hermes.add_tool(spec, lambda n, a, _t=tools: _t.dispatch(n, a))
"""

from __future__ import annotations

import argparse
import json

from eraherm_memory import HermesMemoryTools, MemoryClient


def _demo(base_url: str) -> None:
    with MemoryClient(base_url) as client:
        tools = HermesMemoryTools(client, user_id="hermes_tools_demo")
        print("session:", tools.session_id)
        print("tools:", tools.tool_names())
        print("\n-- openai schema (first) --")
        print(json.dumps(tools.openai_tools()[0], ensure_ascii=False, indent=2))

        print("\n-- remember --")
        print(
            tools.dispatch(
                "memory_remember",
                {
                    "content": "用户喜欢喝冰美式",
                    "pinned": True,
                    "memory_type": "preference",
                    "importance": 0.95,
                },
            )
        )

        print("\n-- recall (paraphrase) --")
        print(tools.dispatch("memory_recall", {"query": "用户下午喝什么"}))

        print("\n-- correct --")
        print(
            tools.dispatch(
                "memory_correct",
                {
                    "correction": "用户喜欢喝冰美式，不是热美式",
                    "wrong_answer": "热美式",
                },
            )
        )

        print("\n-- recall after correct --")
        print(tools.dispatch("memory_recall", {"query": "用户的饮品偏好"}))

        tools.end_session()
        print("\ndone")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes built-in memory tools demo")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    _demo(args.base_url)


if __name__ == "__main__":
    main()
