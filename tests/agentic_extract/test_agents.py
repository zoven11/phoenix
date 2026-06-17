from agentic_extract import agents


class DummyAgent:
    def __init__(self, *args, **kwargs):
        _ = (args, kwargs)


class DummyToolkit:
    def register_tool_function(self, *args, **kwargs):
        _ = (args, kwargs)


def test_workspace_shell_tool_uses_phoenix_timeout(monkeypatch):
    captured = {}

    async def fake_execute_shell_command(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(agents, "execute_shell_command", fake_execute_shell_command)

    tool = agents.create_workspace_shell_tool(timeout=900)
    import asyncio

    result = asyncio.run(tool("xdev eval"))

    assert result == "ok"
    assert captured == {"command": "xdev eval", "timeout": 900}


def test_workspace_shell_tool_allows_per_call_timeout_override(monkeypatch):
    captured = {}

    async def fake_execute_shell_command(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(agents, "execute_shell_command", fake_execute_shell_command)

    tool = agents.create_workspace_shell_tool(timeout=900)
    import asyncio

    asyncio.run(tool("xdev run --pdf sample.pdf", timeout_sec=120))

    assert captured == {"command": "xdev run --pdf sample.pdf", "timeout": 120}


def test_workspace_shell_tool_can_block_full_eval_in_repair_mode(monkeypatch):
    called = False

    async def fake_execute_shell_command(**kwargs):
        nonlocal called
        called = True
        return "ok"

    monkeypatch.setattr(agents, "execute_shell_command", fake_execute_shell_command)

    tool = agents.create_workspace_shell_tool(timeout=900, allow_full_eval=False)
    import asyncio

    result = asyncio.run(tool("xdev eval"))

    assert called is False
    assert "blocks full `xdev eval`" in result.content[0]["text"]


def test_business_agent_allows_full_eval_but_dev_agent_blocks_it(monkeypatch):
    captured = []

    def fake_create_base_toolkit(*args, **kwargs):
        _ = args
        captured.append(kwargs)
        return DummyToolkit()

    monkeypatch.setattr(agents, "_create_base_toolkit", fake_create_base_toolkit)
    monkeypatch.setattr(agents, "create_model", lambda **kwargs: (object(), object()))
    monkeypatch.setattr(agents, "_create_compression_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(agents, "ReActAgent", DummyAgent)
    monkeypatch.setattr(agents, "register_agent_logging", lambda _agent: None)
    monkeypatch.setattr(agents, "register_loop_detection_hook", lambda _agent: None)
    monkeypatch.setattr(agents, "register_ruff_check_hook", lambda _agent: None)
    monkeypatch.setattr(
        "agentic_extract.labeling.workflow.create_label_all_documents_tool",
        lambda **kwargs: object(),
    )

    agents.create_business_agent("model", "base", "key")
    agents.create_dev_agent("model", "base", "key")

    assert captured[0].get("allow_full_eval", True) is True
    assert captured[1]["allow_full_eval"] is False
