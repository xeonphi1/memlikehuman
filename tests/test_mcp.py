import json
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_real_stdio_roundtrip_and_scope_isolation(tmp_path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "memlikehuman.cli", "--data-dir", str(tmp_path / "mcp"), "serve"],
    )
    async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert {t.name for t in tools.tools} == {
            "memory_record",
            "memory_recall",
            "memory_read",
            "session_checkpoint",
            "session_resume",
            "memory_correct",
            "memory_forget",
        }
        result = await session.call_tool(
            "memory_record",
            {
                "event_id": "stdio-e",
                "text": "我们正在做记忆系统",
                "role": "user",
                "source": "synthetic",
                "cues": [{"kind": "photo", "key": "photo:synthetic-stdio", "label": "记忆系统"}],
            },
        )
        assert not result.isError
        assert result.structuredContent["durable"] is True
        result = await session.call_tool("memory_read", {"record_id": "stdio-e"})
        assert result.structuredContent["event"]["text"] == "我们正在做记忆系统"
        recalled = await session.call_tool(
            "memory_recall",
            {
                "query": "",
                "cue_key": "photo:synthetic-stdio",
                "detail": "gist",
                "search_mode": "fast",
            },
        )
        assert not recalled.isError
        assert recalled.structuredContent["raw_events"][0]["id"] == "stdio-e"
        assert recalled.structuredContent["raw_events"][0]["resolution"] == "gist"
        other = await session.call_tool(
            "memory_read", {"record_id": "stdio-e", "project_id": "other"}
        )
        assert other.isError
        result = await session.call_tool(
            "session_checkpoint",
            {"covered_event_id": "stdio-e", "state": {"goal": "实现 MCP", "next_step": "测试"}},
        )
        assert not result.isError
        restored = await session.call_tool("session_resume", {"token_budget": 10000})
        packet = json.loads(restored.structuredContent["context"])
        assert packet["checkpoint"]["state"]["next_step"] == "测试"
        resource = await session.read_resource("persona://default/current")
        assert "知伴" in resource.contents[0].text
        prompt = await session.get_prompt("start_session", {"project_id": "default"})
        assert "cannot detect context fullness" in prompt.messages[0].content.text
