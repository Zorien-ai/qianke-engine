from __future__ import annotations

import json
import logging
from typing import Any

from rag_demo.agent.registry import ToolRegistry
from rag_demo.agent.state import AgentState
from rag_demo.generation.generator import chat_completion

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 Qianke Agent。
你负责回答电商用户画像与知识库问题。

规则：
1. 需要事实资料时调用 rag_search；不要凭空编造。
2. 需要统计、聚合、排名、数量、平均值时优先调用 execute_sql。
3. 需要算术时调用 calculator。
4. 工具返回的数据是事实来源；最终回答应基于工具结果。
5. 如果工具无法提供足够证据，要明确说明无法确定，不要补数字。
6. 你可以连续调用工具，但不要超过运行时允许的步数。
"""


class AgentRunner:
    """Minimal tool-calling agent loop, intentionally independent of LangChain."""

    def __init__(self, registry: ToolRegistry, max_steps: int = 8) -> None:
        self.registry = registry
        self.max_steps = max_steps

    def run(self, question: str) -> dict[str, Any]:
        state = AgentState(
            question=question,
            max_steps=self.max_steps,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        )

        while state.step < state.max_steps:
            state.step += 1
            response = chat_completion(
                messages=state.messages,
                temperature=0.0,
                deep_thinking=False,
                feature="agent",
                tools=self.registry.schemas(),
                tool_choice="auto",
            )
            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None) or []

            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or None,
            }
            if tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ]
            state.add_message(assistant_message)

            if not tool_calls:
                state.final_answer = message.content or ""
                return {
                    "answer": state.final_answer,
                    "steps": state.step,
                    "tool_calls": state.tool_calls,
                }

            for tool_call in tool_calls:
                state.tool_calls += 1
                name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments or "{}")
                    tool = self.registry.get(name)
                    result = tool.invoke(arguments)
                    content = json.dumps(result, ensure_ascii=False, default=str)
                except Exception as exc:  # tool failures become observations
                    logger.exception("agent tool failed: %s", name)
                    content = json.dumps(
                        {"error": type(exc).__name__, "message": str(exc)},
                        ensure_ascii=False,
                    )

                state.add_message({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": name,
                    "content": content,
                })

        return {
            "answer": "Agent 达到最大执行步数，未能完成回答。",
            "steps": state.step,
            "tool_calls": state.tool_calls,
            "error": "MAX_STEPS_EXCEEDED",
        }
