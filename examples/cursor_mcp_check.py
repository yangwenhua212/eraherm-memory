"""自验脚本：通过 MCP stdio client 驱动 eraherm_mcp_server.py 全链路冒烟。

覆盖：health / recall / remember / evolve（纠正即进化）/ impact。
需先起服务：uvicorn app.main:app --port 8000

  python examples/cursor_mcp_check.py
"""
import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _text(result) -> str:
    return result.content[0].text if result.content else "(no content)"


async def main() -> None:
    params = StdioServerParameters(
        command="/home/admin/eraherm-memory/.venv/bin/python",
        args=["eraherm_mcp_server.py"],
        env={"ERAHERM_API_URL": "http://127.0.0.1:8000", "ERAHERM_USER_ID": "cursor_demo"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"[tools] {len(tools.tools)}:", ", ".join(t.name for t in tools.tools))

            # 1. health
            r = await session.call_tool("eraherm_health", {})
            print("[health]", _text(r)[:80])

            # 2. recall existing
            r = await session.call_tool("eraherm_recall", {"query": "我们数据库用什么", "user_id": "u_correct_demo"})
            items = json.loads(_text(r)).get("items", [])
            print(f"[recall] top1: {items[0]['content'][:40] if items else '(空)'}")

            # 3. remember new fact
            r = await session.call_tool("eraherm_remember", {"content": "项目 Cursor 适配器用 MCP stdio 连接", "pinned": True})
            mid = json.loads(_text(r)).get("id")
            print(f"[remember] id={mid}")

            # 4. evolve: correct it
            r = await session.call_tool("eraherm_evolve", {"correction": "应该是 fastmcp 不是 mcp", "answer": "用 mcp 连接", "related_memory_ids": [mid]})
            print("[evolve]", _text(r)[:100])

            # 5. recall after evolve
            r = await session.call_tool("eraherm_recall", {"query": "Cursor 适配器怎么连接"})
            items = json.loads(_text(r)).get("items", [])
            top = items[0]["content"] if items else "(空)"
            print(f"[recall-after-evolve] top1: {top[:50]}")
            print("PASS" if "fastmcp" in top else "FAIL: 纠正后新事实未排第一")

            # 6. impact
            r = await session.call_tool("eraherm_impact", {"entity_name": "MCP", "user_id": "u_correct_demo"})
            print("[impact]", _text(r)[:120])


if __name__ == "__main__":
    asyncio.run(main())
