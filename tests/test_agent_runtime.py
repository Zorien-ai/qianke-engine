from types import SimpleNamespace

import pytest

from rag_demo.agent.registry import ToolRegistry
from rag_demo.agent.tool import Tool
from rag_demo.agent.tools import calculator


def test_registry_rejects_duplicate_tool_names():
    tool = Tool("x", "x", {"type": "object"}, lambda: 1)
    registry = ToolRegistry([tool])
    with pytest.raises(ValueError, match="duplicate tool"):
        registry.register(tool)


def test_calculator_does_not_execute_python():
    assert calculator("(10 + 2) * 3") == {"result": 36}
    with pytest.raises(ValueError):
        calculator("__import__('os').getcwd()")


def test_agent_loop_executes_tool_then_returns_answer(monkeypatch):
    from rag_demo.agent.loop import AgentRunner

    calls = []

    def fake_chat_completion(**kwargs):
        calls.append(list(kwargs["messages"]))
        if len(calls) == 1:
            message = SimpleNamespace(
                content=None,
                tool_calls=[
                    SimpleNamespace(
                        id="call_1",
                        function=SimpleNamespace(
                            name="calculator",
                            arguments='{"expression":"2+3"}',
                        ),
                    )
                ],
            )
        else:
            message = SimpleNamespace(content="5", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr("rag_demo.agent.loop.chat_completion", fake_chat_completion)

    registry = ToolRegistry([
        Tool(
            "calculator",
            "calculate",
            {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
            calculator,
        )
    ])

    result = AgentRunner(registry, max_steps=3).run("2+3 等于多少？")

    assert result["answer"] == "5"
    assert result["steps"] == 2
    assert result["tool_calls"] == 1
    assert calls[1][-1]["role"] == "tool"
    assert calls[1][-1]["tool_call_id"] == "call_1"


def test_agent_loop_stops_at_max_steps(monkeypatch):
    from rag_demo.agent.loop import AgentRunner

    def fake_chat_completion(**kwargs):
        message = SimpleNamespace(
            content=None,
            tool_calls=[
                SimpleNamespace(
                    id="call_forever",
                    function=SimpleNamespace(
                        name="calculator",
                        arguments='{"expression":"1+1"}',
                    ),
                )
            ],
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr("rag_demo.agent.loop.chat_completion", fake_chat_completion)
    registry = ToolRegistry([
        Tool("calculator", "calculate", {"type": "object"}, calculator)
    ])

    result = AgentRunner(registry, max_steps=2).run("一直算")

    assert result["error"] == "MAX_STEPS_EXCEEDED"
    assert result["steps"] == 2
