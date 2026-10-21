from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    """Mutable execution state for one agent run.

    Keep this independent from LangChain/LangGraph so the runtime concepts are
    understood and testable before introducing a framework.
    """

    question: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    step: int = 0
    max_steps: int = 8
    tool_calls: int = 0
    final_answer: str | None = None

    def add_message(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    @property
    def finished(self) -> bool:
        return self.final_answer is not None
