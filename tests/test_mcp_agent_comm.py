# -*- coding: utf-8 -*-
"""Agent Comm Bus / MCP 固定能力与自动路由测试。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rag_demo.mcp_agent_comm.store import AgentCommStore, CommError, load_config


CONFIG = {
    "agents": [
        {
            "agent_id": "c_end",
            "display_name": "C 端 Agent",
            "capabilities": ["c_end", "commerce", "ui"],
            "max_risk": "low",
            "owner": "owner",
            "auto_accept": True,
        },
        {
            "agent_id": "b_end",
            "display_name": "B 端 Agent",
            "capabilities": ["b_end", "merchant", "ui"],
            "max_risk": "low",
            "owner": "owner",
            "auto_accept": True,
        },
        {
            "agent_id": "system",
            "display_name": "系统 Agent",
            "capabilities": ["system", "eval", "monitor", "release"],
            "max_risk": "medium",
            "owner": "owner",
            "auto_accept": True,
        },
    ]
}


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
    return path


def _store(tmp_path: Path, config_path: Path, agent_id: str, ttl_days=None) -> AgentCommStore:
    return AgentCommStore(
        agent_id=agent_id,
        config_path=str(config_path),
        db_path=str(tmp_path / "bus.sqlite3"),
        ttl_days=ttl_days,
    )


def test_fixed_capabilities_are_config_only():
    cards = load_config(str(Path("config/agent_comm_agents.json")))
    assert cards["c_end"]["capabilities"] == ["c_end", "commerce", "ui"]
    assert cards["system"]["capabilities"] == ["system", "eval", "monitor", "release"]
    assert cards["system"]["max_risk"] == "medium"


def test_auto_routes_task_by_capability(tmp_path, config_path):
    store = _store(tmp_path, config_path, "system")
    try:
        result = store.propose_task(
            title="C 端商品详情验收",
            required_capabilities=["c_end", "ui"],
            risk="low",
            mode="auto",
        )
        assert result["status"] == "ASSIGNED"
        assert result["assignee"] == "c_end"
        assert result["approval_id"] is None
        c_end = _store(tmp_path, config_path, "c_end")
        try:
            inbox = c_end.read()
            assert inbox["messages"]
            assert inbox["messages"][0]["kind"] == "task"
            assert inbox["messages"][0]["task_id"] == result["task_id"]
        finally:
            c_end.close()
    finally:
        store.close()


def test_task_rejects_no_eligible_agent(tmp_path, config_path):
    store = _store(tmp_path, config_path, "system")
    try:
        with pytest.raises(CommError) as exc:
            store.propose_task(title="不存在的能力", required_capabilities=["quantum"])
        assert exc.value.code == "NO_ELIGIBLE_AGENT"
    finally:
        store.close()


def test_high_risk_task_goes_to_approval(tmp_path, config_path):
    store = _store(tmp_path, config_path, "system")
    try:
        result = store.propose_task(
            title="跨端高风险操作",
            required_capabilities=["b_end"],
            risk="high",
            mode="auto",
        )
        assert result["status"] == "WAITING_APPROVAL"
        assert result["approval_id"]
        assert result["assignee"] == "b_end"
    finally:
        store.close()


def test_direct_message_and_room(tmp_path, config_path):
    c_end = _store(tmp_path, config_path, "c_end")
    system = _store(tmp_path, config_path, "system")
    try:
        room = c_end.create_room("联调群")
        system.join_room(room["room_id"])
        c_end.send(room_id=room["room_id"], content={"text": "C 端完成"})
        messages = system.read()["messages"]
        assert any(item["content"].get("text") == "C 端完成" for item in messages)
        c_end.send(to="system", content={"text": "单聊消息"})
        messages = system.read()["messages"]
        assert any(item["content"].get("text") == "单聊消息" for item in messages)
    finally:
        c_end.close()
        system.close()


def test_mcp_stdio_initialize_and_tool_call(tmp_path, config_path):
    db_path = tmp_path / "mcp.sqlite3"
    env = dict(os.environ)
    env["AGENT_COMM_CONFIG"] = str(config_path)
    env["AGENT_COMM_DB"] = str(db_path)
    env["AGENT_COMM_AGENT_ID"] = "system"
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "comm_whoami", "arguments": {}}},
    ]
    payload = "\n".join(json.dumps(item, ensure_ascii=False) for item in requests) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "rag_demo.mcp_agent_comm"],
        input=payload,
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=Path.cwd(),
        env=env,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    by_id = {item.get("id"): item for item in lines}
    assert by_id[1]["result"]["serverInfo"]["name"] == "qianke-agent-comm"
    tools = by_id[2]["result"]["tools"]
    assert any(item["name"] == "comm_propose_task" for item in tools)
    whoami = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert whoami["agent_id"] == "system"
    assert whoami["capabilities"] == ["system", "eval", "monitor", "release"]


def test_task_requires_capability_list(tmp_path, config_path):
    store = _store(tmp_path, config_path, "system")
    try:
        with pytest.raises(CommError) as exc:
            store.propose_task(title="无能力任务", required_capabilities=[])
        assert exc.value.code == "INVALID_TASK"
    finally:
        store.close()


def test_human_approval_releases_task(tmp_path, config_path):
    from rag_demo.mcp_agent_comm.store import open_admin_store

    system = _store(tmp_path, config_path, "system")
    admin = open_admin_store(config_path=str(config_path), db_path=str(tmp_path / "bus.sqlite3"))
    b_end = _store(tmp_path, config_path, "b_end")
    try:
        task = system.propose_task(
            title="高风险退款",
            instruction="需要人工确认",
            required_capabilities=["b_end"],
            risk="high",
            mode="auto",
        )
        pending = admin.list_approvals(status="PENDING")
        assert len(pending) == 1
        result = admin.decide_approval(task["approval_id"], action="approve", note="同意", actor="admin")
        assert result["status"] == "APPROVED"
        assert result["task_status"] == "ASSIGNED"
        inbox = b_end.read()["messages"]
        assert any(item["kind"] == "task" and item["content"].get("status") == "ASSIGNED" for item in inbox)
    finally:
        system.close(); admin.close(); b_end.close()


def test_human_rejects_task(tmp_path, config_path):
    from rag_demo.mcp_agent_comm.store import open_admin_store

    system = _store(tmp_path, config_path, "system")
    admin = open_admin_store(config_path=str(config_path), db_path=str(tmp_path / "bus.sqlite3"))
    try:
        task = system.propose_task(
            title="高风险操作",
            required_capabilities=["b_end"],
            risk="high",
            mode="auto",
        )
        result = admin.decide_approval(task["approval_id"], action="reject", note="不做", actor="admin")
        assert result["status"] == "REJECTED"
        assert result["task_status"] == "REJECTED"
    finally:
        system.close(); admin.close()


def test_expired_payload_is_purged_and_hash_kept(tmp_path, config_path):
    store = _store(tmp_path, config_path, "system", ttl_days=0)
    try:
        store.send(to="c_end", content={"text": "短期正文"})
        purge = store.purge_expired()
        assert purge["purged"] == 1
        assert store.recent_messages() == []
        row = store.conn.execute("SELECT content_hash FROM message_audit").fetchone()
        assert row is not None
        assert len(row["content_hash"]) == 64
    finally:
        store.close()


def test_workspace_human_room_and_task(tmp_path, config_path):
    from rag_demo.mcp_agent_comm.store import open_admin_store

    admin = open_admin_store(config_path=str(config_path), db_path=str(tmp_path / "bus.sqlite3"))
    try:
        room = admin.create_room("工作台联调群")
        admin.post_human_message(room["room_id"], {"text": "人类工作台消息"}, actor="admin")
        messages = admin.room_messages(room["room_id"])
        assert messages[-1]["sender"] == "human:admin"
        assert messages[-1]["content"]["text"] == "人类工作台消息"

        task = admin.propose_task(
            title="C 端回归",
            required_capabilities=["c_end"],
            risk="low",
            mode="auto",
            sender_id="human:admin",
        )
        assert task["status"] == "ASSIGNED"
        assert task["assignee"] == "c_end"
        all_tasks = admin.list_all_tasks()
        assert any(item["task_id"] == task["task_id"] and item["sender_id"] == "human:admin" for item in all_tasks)
        rooms = admin.list_all_rooms()
        assert any(item["room_id"] == room["room_id"] and item["member_count"] >= 1 for item in rooms)
    finally:
        admin.close()
