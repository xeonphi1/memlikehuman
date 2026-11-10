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


@pytest.mark.asyncio
@pytest.mark.parametrize("host_capture", [False, True])
async def test_configured_defaults_apply_to_all_tools_and_explicit_scopes_still_work(
    tmp_path, host_capture
):
    from conftest import remember

    from memlikehuman.engine import Engine
    from memlikehuman.models import Scope

    data_dir = tmp_path / "scoped-mcp"
    selected = Scope(persona_id="whale", project_id="companionship")
    engine = Engine(data_dir)
    memory_id = remember(engine, selected)
    args = [
        "-m",
        "memlikehuman.cli",
        "--data-dir",
        str(data_dir),
        "--persona",
        selected.persona_id,
        "--project",
        selected.project_id,
        "serve",
    ]
    if host_capture:
        args.append("--host-capture")
    params = StdioServerParameters(command=sys.executable, args=args)
    async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
        initialized = await session.initialize()
        assert '"persona_id":"whale"' in initialized.instructions
        assert '"project_id":"companionship"' in initialized.instructions
        if host_capture:
            assert (
                "Do not call memory_record for messages already captured"
                in initialized.instructions
            )
            assert (
                "After durable user/assistant messages call memory_record"
                not in initialized.instructions
            )
        else:
            assert (
                "After durable user/assistant messages call memory_record"
                in initialized.instructions
            )
        tools = await session.list_tools()
        for tool in tools.tools:
            properties = tool.inputSchema["properties"]
            assert properties["persona_id"]["default"] == selected.persona_id
            assert properties["project_id"]["default"] == selected.project_id

        # Omission uses the configured partition, including writes and task restoration.
        result = await session.call_tool(
            "memory_record",
            {"event_id": "configured-event", "text": "整理照片", "role": "user", "source": "test"},
        )
        assert not result.isError
        assert engine.store.event(selected, "configured-event")["text"] == "整理照片"
        with pytest.raises(ValueError):
            engine.store.event(Scope(), "configured-event")
        read = await session.call_tool("memory_read", {"record_id": "configured-event"})
        assert read.structuredContent["event"]["text"] == "整理照片"
        checkpoint = await session.call_tool(
            "session_checkpoint",
            {
                "covered_event_id": "configured-event",
                "state": {"goal": "整理照片", "next_step": "备份"},
            },
        )
        assert not checkpoint.isError
        restored = await session.call_tool("session_resume", {"token_budget": 10000})
        packet = json.loads(restored.structuredContent["context"])
        assert packet["checkpoint"]["state"]["next_step"] == "备份"

        # Explicit "default" is a real partition, not an omission sentinel.
        other = await session.call_tool(
            "memory_record",
            {
                "event_id": "explicit-default",
                "text": "默认分区独有",
                "role": "user",
                "source": "test",
                "persona_id": "default",
                "project_id": "default",
            },
        )
        assert not other.isError
        assert engine.store.event(Scope(), "explicit-default")["text"] == "默认分区独有"
        recall = await session.call_tool("memory_recall", {"query": "默认分区独有"})
        assert not recall.structuredContent["raw_events"]
        wrong_scope = await session.call_tool(
            "memory_read", {"record_id": "configured-event", "project_id": "default"}
        )
        assert wrong_scope.isError

        corrected = await session.call_tool(
            "memory_correct",
            {"memory_id": memory_id, "content": "住在杭州", "reason": "合成测试纠错"},
        )
        assert not corrected.isError
        forgotten = await session.call_tool("memory_forget", {"record_id": "e1"})
        assert not forgotten.isError
        with pytest.raises(ValueError):
            engine.store.event(selected, "e1")
        assert engine.store.event(Scope(), "explicit-default")  # No cross-scope deletion.

        prompt = await session.get_prompt("start_session", {})
        assert f"Selected scope: {selected.model_dump_json()}" in prompt.messages[0].content.text
        assert ("Host-capture mode" in prompt.messages[0].content.text) == host_capture
        override = await session.get_prompt("start_session", {"project_id": "other"})
        assert (
            'Selected scope: {"persona_id":"whale","project_id":"other"}'
            in override.messages[0].content.text
        )
