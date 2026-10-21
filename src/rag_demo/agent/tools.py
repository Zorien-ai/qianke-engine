from __future__ import annotations

from rag_demo.agent.tool import Tool
from rag_demo.pipeline import answer_question
from rag_demo.tools import sql_tool


def rag_search(question: str) -> dict:
    """Reuse Qianke's existing RAG pipeline instead of duplicating retrieval."""
    result = answer_question(question, use_cache=True)
    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "route": result.get("route", "rag"),
    }


def execute_sql(question: str) -> dict:
    """Reuse the existing guarded Text2SQL path."""
    return sql_tool.query(question)


def calculator(expression: str) -> dict:
    """Intentionally tiny calculator; no eval/exec in v0."""
    import ast
    import operator

    operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def calc(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in operators:
            return operators[type(node.op)](calc(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            return operators[type(node.op)](calc(node.left), calc(node.right))
        raise ValueError("unsupported expression")

    tree = ast.parse(expression, mode="eval")
    return {"result": calc(tree.body)}


RAG_SEARCH = Tool(
    name="rag_search",
    description="Search Qianke's e-commerce knowledge/profile data and return grounded sources.",
    schema={
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
        "additionalProperties": False,
    },
    fn=rag_search,
)

EXECUTE_SQL = Tool(
    name="execute_sql",
    description="Answer a structured/statistical question through Qianke's read-only Text2SQL pipeline.",
    schema={
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
        "additionalProperties": False,
    },
    fn=execute_sql,
)

CALCULATOR = Tool(
    name="calculator",
    description="Calculate a basic arithmetic expression without executing arbitrary Python code.",
    schema={
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
        "additionalProperties": False,
    },
    fn=calculator,
)
