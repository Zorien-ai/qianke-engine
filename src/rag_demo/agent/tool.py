"""Tool Contract：JSON-compatible 输入/输出 + 统一错误模型。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, Field


class ToolError(BaseModel):
    """所有工具共享的错误结构。"""

    code: str
    message: str


class ToolResult(BaseModel):
    """统一成功/失败返回。

    成功: {"ok": true, "data": {...}}，并保留 data 中的顶层字段方便 LLM 读取。
    失败: {"ok": false, "error": {"code": "...", "message": "..."}}
    """

    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: ToolError | None = None

    @classmethod
    def success(cls, data: dict[str, Any] | None = None, **extra: Any) -> "ToolResult":
        payload = {**(data or {}), **extra}
        return cls(ok=True, data=payload)

    @classmethod
    def failure(
        cls,
        code: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(ok=False, data=data or {}, error=ToolError(code=code, message=message))

    def dump(self) -> dict[str, Any]:
        """序列化为 LangChain ToolNode 可直接消费的 JSON-compatible dict。"""
        payload: dict[str, Any] = {"ok": self.ok, "data": self.data}
        if self.ok:
            # 例如 calculator 的 expression/result、SQL 的 columns/rows，
            # 既有统一 data，也保留工具示例中的顶层字段。
            payload.update(self.data)
        if self.error is not None:
            payload["error"] = self.error.model_dump()
        return payload


@dataclass(frozen=True)
class Tool:
    """轻量 Tool 描述：给 Agent Runtime / MCP 使用。

    fn 接收 Python 类型参数，返回 JSON-compatible dict；业务逻辑不感知 JSON。
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., dict[str, Any]]

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            return ToolResult.failure("INVALID_ARGUMENTS", "arguments 必须是 JSON object").dump()
        try:
            return self.fn(**arguments)
        except TypeError as exc:
            return ToolResult.failure("INVALID_ARGUMENTS", str(exc)).dump()
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure("TOOL_ERROR", f"{type(exc).__name__}: {exc}").dump()
