from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Tool:
    """A small runtime-neutral tool definition.

    The LLM sees `schema`; the runtime only executes `fn` after validating the
    tool name and parsing JSON arguments.
    """

    name: str
    description: str
    schema: dict[str, Any]
    fn: Callable[..., Any]

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }

    def invoke(self, arguments: dict[str, Any]) -> Any:
        return self.fn(**arguments)
