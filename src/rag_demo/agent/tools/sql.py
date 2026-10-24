"""SQL 薄壳：SQL Tool Contract，复用现有 sql_tool 的校验与只读执行。"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from rag_demo.agent.tool import ToolResult


class ExecuteSqlInput(BaseModel):
    """execute_sql 的 JSON Schema。"""

    model_config = ConfigDict(extra="forbid")
    sql: str = Field(..., min_length=1, description="只读 SELECT/WITH SQL，必须带 LIMIT")


def run_sql(sql: str) -> dict[str, Any]:
    """领域逻辑：复用 sql_tool.execute_sql_dict（validate + 只读执行）。"""
    from rag_demo.tools import sql_tool

    return sql_tool.execute_sql_dict(sql)


def _sql_adapter(sql: str) -> dict[str, Any]:
    result = run_sql(sql)
    if result.get("error"):
        message = str(result["error"])
        code = "SQL_VALIDATION_ERROR" if "校验失败" in message else "SQL_EXECUTION_ERROR"
        return ToolResult.failure(
            code,
            message,
            {
                "sql": sql,
                "columns": result.get("columns", []),
                "rows": result.get("rows", []),
                "row_count": result.get("row_count", 0),
            },
        ).dump()

    return ToolResult.success(
        sql=sql,
        columns=result.get("columns", []),
        rows=result.get("rows", []),
        row_count=result.get("row_count", 0),
    ).dump()


@tool(args_schema=ExecuteSqlInput)
def execute_sql(sql: str) -> dict[str, Any]:
    """执行只读 SQL 并返回 columns / rows（list[dict]）/ row_count。

    复用千客引擎现有 sql_tool 的安全校验与只读连接；SQL 报错时返回统一
    ToolError，Agent 可据此修正 SQL 后重试。
    """
    return _sql_adapter(sql)
