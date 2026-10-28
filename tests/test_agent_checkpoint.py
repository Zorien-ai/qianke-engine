"""LangGraph checkpointer 与 interrupt 原语测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from rag_demo.agent import loop
from rag_demo.agent.checkpoint import sqlite_checkpointer
from rag_demo.agent.state import AgentConfig


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def invoke(self, messages):
        return self._responses.pop(0)


def _tool_call():
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "calculator",
            "args": {"expression": "1+1"},
            "id": "call_1",
            "type": "tool_call",
        }],
    )


def test_run_agent_writes_checkpoint(tmp_path, monkeypatch):
    saver = sqlite_checkpointer(tmp_path / "checkpoints.sqlite")
    fake = _FakeLLM([AIMessage(content="完成")])
    monkeypatch.setattr(loop, "get_llm", lambda allowed_tools=None: fake)
    monkeypatch.setattr(loop, "build_system_prompt", lambda config=None: "sys")

    result = loop.run_agent(
        "你好",
        config=AgentConfig(max_steps=2),
        checkpointer=saver,
        thread_id="thread-checkpoint-1",
    )

    assert result["status"] == "COMPLETED"
    graph = loop.build_graph(checkpointer=saver)
    state = graph.get_state({"configurable": {"thread_id": "thread-checkpoint-1"}})
    assert state.values["messages"]


def test_interrupt_before_tools_can_resume(tmp_path, monkeypatch):
    saver = sqlite_checkpointer(tmp_path / "interrupt.sqlite")
    fake = _FakeLLM([_tool_call(), AIMessage(content="结果是 2")])
    monkeypatch.setattr(loop, "get_llm", lambda allowed_tools=None: fake)

    graph = loop.build_graph(checkpointer=saver, interrupt_before_tools=True)
    config = {"configurable": {"thread_id": "thread-interrupt-1"}}
    state = graph.invoke({"messages": [HumanMessage(content="1+1")]}, config=config)

    # 静态断点 interrupt_before 通过 next=('tools',) 表示挂起，而不是写入 __interrupt__
    assert state["status"] == "RUNNING"
    assert graph.get_state(config).next == ("tools",)

    resumed = graph.invoke(None, config=config)
    assert resumed["status"] == "COMPLETED"
    assert graph.get_state(config).next == ()
