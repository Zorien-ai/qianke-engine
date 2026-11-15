# -*- coding: utf-8 -*-
"""MCP stdio server：把 Agent Comm Bus 暴露为 MCP tools。

用法:
    python -m rag_demo.mcp_agent_comm --agent system

环境变量:
    AGENT_COMM_AGENT_ID  当前 Agent（也可用 --agent）
    AGENT_COMM_CONFIG    固定能力配置，默认 config/agent_comm_agents.json
    AGENT_COMM_DB        SQLite 路径，默认 var/agent_comm.sqlite3

注意：stdout 只输出 MCP JSON-RPC，日志全部写 stderr。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

from .store import AgentCommStore, CommError

logger = logging.getLogger("qianke.agent_comm")


def _tool(name: str, description: str, properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
    }


TOOLS = [
    _tool(
        "comm_whoami",
        "返回当前 Agent 身份与固定能力（由平台配置，Agent 不能自行修改）。",
    ),
    _tool(
        "comm_list_agents",
        "列出所有已注册 Agent 的固定能力、风险上限和 owner，用于发现协作者。",
    ),
    _tool(
        "comm_create_room",
        "创建群组，用于多个 Agent 和人类共同协作。",
        {"name": {"type": "string", "description": "群名称"}},
        ["name"],
    ),
    _tool(
        "comm_join_room",
        "加入已有群组。",
        {"room_id": {"type": "string", "description": "群 id"}},
        ["room_id"],
    ),
    _tool("comm_list_rooms", "列出当前 Agent 已加入的群组。"),
    _tool(
        "comm_send",
        "发送消息：to 单聊，room_id 群聊，二选一。",
        {
            "to": {"type": "string", "description": "接收方 agent_id"},
            "room_id": {"type": "string", "description": "群 id"},
            "kind": {"type": "string", "description": "消息类型：chat/request/response/event", "default": "chat"},
            "content": {"type": "object", "description": "结构化消息内容"},
            "correlation_id": {"type": "string"},
            "reply_to": {"type": "string"},
        },
        ["content"],
    ),
    _tool(
        "comm_read",
        "读取当前 Agent 的未读消息（含群消息），游标自动推进。",
        {
            "cursor": {"type": "integer", "description": "可选游标；不传用服务端已保存游标"},
            "limit": {"type": "integer", "default": 20},
        },
    ),
    _tool(
        "comm_ack",
        "确认已读消息。",
        {"message_ids": {"type": "array", "items": {"type": "string"}}},
        ["message_ids"],
    ),
    _tool(
        "comm_propose_task",
        "提出任务并按固定能力自动路由。mode=auto 时低风险任务自动分配，否则生成待审批记录。",
        {
            "title": {"type": "string"},
            "instruction": {"type": "string"},
            "required_capabilities": {"type": "array", "items": {"type": "string"}},
            "risk": {"type": "string", "enum": ["low", "medium", "high"], "default": "low"},
            "mode": {"type": "string", "enum": ["auto", "approval"], "default": "auto"},
        },
        ["title", "required_capabilities"],
    ),
    _tool(
        "comm_list_tasks",
        "列出当前 Agent 发出或收到的任务。",
        {"limit": {"type": "integer", "default": 20}},
    ),
    _tool(
        "comm_task_status",
        "查看单个任务状态。",
        {"task_id": {"type": "string"}},
        ["task_id"],
    ),
]


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _content_result(value: Any, *, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": _json_text(value)}],
        "isError": is_error,
    }


class McpServer:
    def __init__(self, store: AgentCommStore) -> None:
        self.store = store

    def call_tool(self, name: str, arguments: dict) -> dict:
        args = arguments or {}
        try:
            if name == "comm_whoami":
                return _content_result(self.store.whoami())
            if name == "comm_list_agents":
                return _content_result(self.store.list_agents())
            if name == "comm_create_room":
                return _content_result(self.store.create_room(str(args.get("name") or "")))
            if name == "comm_join_room":
                return _content_result(self.store.join_room(str(args.get("room_id") or "")))
            if name == "comm_list_rooms":
                return _content_result(self.store.list_rooms())
            if name == "comm_send":
                return _content_result(
                    self.store.send(
                        to=args.get("to"),
                        room_id=args.get("room_id"),
                        kind=str(args.get("kind") or "chat"),
                        content=args.get("content") or {},
                        correlation_id=args.get("correlation_id"),
                        reply_to=args.get("reply_to"),
                    )
                )
            if name == "comm_read":
                cursor = args.get("cursor")
                return _content_result(
                    self.store.read(
                        cursor=int(cursor) if cursor is not None else None,
                        limit=int(args.get("limit") or 20),
                    )
                )
            if name == "comm_ack":
                ids = args.get("message_ids") or []
                if not isinstance(ids, list):
                    raise CommError("INVALID_ARGUMENT", "message_ids 必须是数组")
                return _content_result(self.store.ack([str(item) for item in ids]))
            if name == "comm_propose_task":
                caps = args.get("required_capabilities") or []
                if not isinstance(caps, list):
                    raise CommError("INVALID_ARGUMENT", "required_capabilities 必须是数组")
                return _content_result(
                    self.store.propose_task(
                        title=str(args.get("title") or ""),
                        instruction=str(args.get("instruction") or ""),
                        required_capabilities=[str(item) for item in caps],
                        risk=str(args.get("risk") or "low"),
                        mode=str(args.get("mode") or "auto"),
                    )
                )
            if name == "comm_list_tasks":
                return _content_result(self.store.list_tasks(limit=int(args.get("limit") or 20)))
            if name == "comm_task_status":
                return _content_result(self.store.task_status(str(args.get("task_id") or "")))
            raise CommError("UNKNOWN_TOOL", f"未知工具: {name}")
        except CommError as exc:
            logger.warning("tool %s failed: %s %s", name, exc.code, exc.message)
            return _content_result({"error": {"code": exc.code, "message": exc.message}}, is_error=True)
        except ValueError as exc:
            logger.warning("tool %s invalid: %s", name, exc)
            return _content_result({"error": {"code": "INVALID_ARGUMENT", "message": str(exc)}}, is_error=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("tool %s crashed", name)
            return _content_result(
                {"error": {"code": "INTERNAL_ERROR", "message": f"{type(exc).__name__}: {exc}"}},
                is_error=True,
            )

    def handle(self, message: dict) -> dict | None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if method is None:
            return None
        if method.startswith("notifications/"):
            return None
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "qianke-agent-comm", "version": "0.1.0"},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32602, "message": "arguments 必须是对象"},
                }
            return {"jsonrpc": "2.0", "id": request_id, "result": self.call_tool(name, arguments)}
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }

    def serve(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"parse error: {exc}"},
                }
            else:
                if not isinstance(message, dict):
                    response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32600, "message": "invalid request"},
                    }
                else:
                    response = self.handle(message)
            if response is not None:
                sys.stdout.write(_json_text(response) + "\n")
                sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qianke Agent Comm MCP server")
    parser.add_argument("--agent", default=os.environ.get("AGENT_COMM_AGENT_ID", ""))
    parser.add_argument("--config", default=os.environ.get("AGENT_COMM_CONFIG", ""))
    parser.add_argument("--db", default=os.environ.get("AGENT_COMM_DB", ""))
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    if not args.agent:
        logger.error("缺少 --agent 或 AGENT_COMM_AGENT_ID")
        return 2
    try:
        store = AgentCommStore(
            agent_id=args.agent,
            config_path=args.config or None,
            db_path=args.db or None,
        )
    except (CommError, ValueError) as exc:
        logger.error("Agent Comm 启动失败: %s", exc)
        return 2
    logger.info("Agent Comm MCP ready: agent=%s db=%s", store.agent_id, store.db_path)
    try:
        McpServer(store).serve()
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
