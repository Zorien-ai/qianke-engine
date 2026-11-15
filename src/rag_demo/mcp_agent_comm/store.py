# -*- coding: utf-8 -*-
"""Agent Comm Bus：本地 SQLite 消息、群组、固定能力与任务自动路由。"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


class CommError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return fallback
    return value


def load_config(path: str | os.PathLike | None = None) -> dict[str, dict]:
    config_path = Path(path or os.environ.get("AGENT_COMM_CONFIG") or "config/agent_comm_agents.json")
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    data = json.loads(config_path.read_text(encoding="utf-8"))
    agents: dict[str, dict] = {}
    for item in data.get("agents") or []:
        agent_id = str(item.get("agent_id") or "").strip()
        if not agent_id:
            continue
        capabilities = [str(cap).strip() for cap in item.get("capabilities") or [] if str(cap).strip()]
        if not capabilities:
            raise ValueError(f"agent {agent_id} capabilities 不能为空")
        risk = str(item.get("max_risk") or "low").lower()
        if risk not in RISK_ORDER:
            raise ValueError(f"agent {agent_id} max_risk 非法: {risk}")
        agents[agent_id] = {
            "agent_id": agent_id,
            "display_name": str(item.get("display_name") or agent_id),
            "capabilities": list(dict.fromkeys(capabilities)),
            "max_risk": risk,
            "owner": str(item.get("owner") or ""),
            "auto_accept": bool(item.get("auto_accept", True)),
        }
    if not agents:
        raise ValueError("agent_comm_agents.json 没有 Agent")
    return agents


class AgentCommStore:
    def __init__(
        self,
        *,
        agent_id: str,
        config_path: str | None = None,
        db_path: str | None = None,
        ttl_days: float | None = None,
    ) -> None:
        self.agent_id = str(agent_id or "").strip()
        self.config = load_config(config_path)
        if self.agent_id not in self.config:
            raise CommError("AGENT_NOT_REGISTERED", f"Agent 未在固定能力配置中注册: {self.agent_id}")
        raw_ttl = ttl_days if ttl_days is not None else float(os.environ.get("AGENT_COMM_MESSAGE_TTL_DAYS", "30"))
        self.ttl_days = max(0.0, float(raw_ttl))
        raw_db = db_path or os.environ.get("AGENT_COMM_DB") or "var/agent_comm.sqlite3"
        self.db_path = Path(raw_db)
        if not self.db_path.is_absolute():
            self.db_path = Path.cwd() / self.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
        self._sync_agents()
        self.purge_expired()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                capabilities_json TEXT NOT NULL,
                max_risk TEXT NOT NULL,
                owner TEXT NOT NULL DEFAULT '',
                auto_accept INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_seen TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS room_members (
                room_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                joined_at TEXT NOT NULL,
                PRIMARY KEY (room_id, agent_id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL UNIQUE,
                sender_id TEXT NOT NULL,
                recipient_id TEXT,
                room_id TEXT,
                kind TEXT NOT NULL,
                content_json TEXT NOT NULL,
                task_id TEXT,
                correlation_id TEXT,
                reply_to TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT
            );
            CREATE INDEX IF NOT EXISTS messages_seq ON messages (seq);
            CREATE TABLE IF NOT EXISTS receipts (
                message_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'delivered',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (message_id, agent_id)
            );
            CREATE TABLE IF NOT EXISTS cursors (
                agent_id TEXT PRIMARY KEY,
                cursor INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                instruction TEXT NOT NULL,
                required_capabilities_json TEXT NOT NULL,
                risk TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                assignee_id TEXT,
                approval_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                reason TEXT NOT NULL DEFAULT '',
                decided_by TEXT NOT NULL DEFAULT '',
                decided_at TEXT,
                decision_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS message_audit (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                recipient_id TEXT,
                room_id TEXT,
                kind TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                task_id TEXT,
                correlation_id TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                purged_at TEXT NOT NULL
            );
            """
        )
        message_columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "expires_at" not in message_columns:
            self.conn.execute("ALTER TABLE messages ADD COLUMN expires_at TEXT")
        approval_columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(approvals)").fetchall()
        }
        for column, ddl in (
            ("decided_by", "TEXT NOT NULL DEFAULT ''"),
            ("decided_at", "TEXT"),
            ("decision_note", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in approval_columns:
                self.conn.execute(f"ALTER TABLE approvals ADD COLUMN {column} {ddl}")
        self.conn.commit()

    def _sync_agents(self) -> None:
        now = _now()
        for card in self.config.values():
            self.conn.execute(
                """INSERT INTO agents
                   (agent_id, display_name, capabilities_json, max_risk, owner, auto_accept, enabled, last_seen)
                   VALUES (?,?,?,?,?,?,1,?)
                   ON CONFLICT(agent_id) DO UPDATE SET
                     display_name=excluded.display_name,
                     capabilities_json=excluded.capabilities_json,
                     max_risk=excluded.max_risk,
                     owner=excluded.owner,
                     auto_accept=excluded.auto_accept,
                     enabled=1""",
                (
                    card["agent_id"],
                    card["display_name"],
                    json.dumps(card["capabilities"], ensure_ascii=False),
                    card["max_risk"],
                    card["owner"],
                    1 if card["auto_accept"] else 0,
                    now,
                ),
            )
        self.conn.commit()

    def _card(self, agent_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if row is None:
            return None
        return {
            "agent_id": row["agent_id"],
            "display_name": row["display_name"],
            "capabilities": _json(row["capabilities_json"], []),
            "max_risk": row["max_risk"],
            "owner": row["owner"],
            "auto_accept": bool(row["auto_accept"]),
            "enabled": bool(row["enabled"]),
            "last_seen": row["last_seen"],
        }

    def whoami(self) -> dict:
        self.conn.execute("UPDATE agents SET last_seen=? WHERE agent_id=?", (_now(), self.agent_id))
        self.conn.commit()
        return self._card(self.agent_id) or {}

    def list_agents(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM agents WHERE enabled=1 ORDER BY agent_id").fetchall()
        return [self._card(row["agent_id"]) for row in rows if row["agent_id"]]

    def create_room(self, name: str) -> dict:
        name = str(name or "").strip()[:80]
        if not name:
            raise CommError("INVALID_ROOM", "群名称不能为空")
        room_id = f"room_{uuid.uuid4().hex[:10]}"
        now = _now()
        self.conn.execute(
            "INSERT INTO rooms (room_id, name, created_by, created_at) VALUES (?,?,?,?)",
            (room_id, name, self.agent_id, now),
        )
        self.conn.execute(
            "INSERT INTO room_members (room_id, agent_id, role, joined_at) VALUES (?,?,'owner',?)",
            (room_id, self.agent_id, now),
        )
        self.conn.commit()
        return {"room_id": room_id, "name": name, "created_by": self.agent_id}

    def join_room(self, room_id: str) -> dict:
        room = self.conn.execute("SELECT * FROM rooms WHERE room_id=?", (room_id,)).fetchone()
        if room is None:
            raise CommError("ROOM_NOT_FOUND", "群不存在")
        self.conn.execute(
            "INSERT OR IGNORE INTO room_members (room_id, agent_id, role, joined_at) VALUES (?,?,'member',?)",
            (room_id, self.agent_id, _now()),
        )
        self.conn.commit()
        return {"room_id": room_id, "name": room["name"], "joined": True}

    def list_rooms(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT r.*, COUNT(m.agent_id) AS member_count
               FROM rooms r JOIN room_members m ON m.room_id=r.room_id
               WHERE r.room_id IN (SELECT room_id FROM room_members WHERE agent_id=?)
               GROUP BY r.room_id ORDER BY r.created_at DESC""",
            (self.agent_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _expires_at(self) -> str:
        now = datetime.now(timezone.utc)
        return (now + timedelta(days=self.ttl_days)).isoformat()

    def _insert_message(
        self,
        *,
        sender_id: str,
        recipient_id: str | None,
        room_id: str | None,
        kind: str,
        content: dict,
        task_id: str | None = None,
        correlation_id: str | None = None,
        reply_to: str | None = None,
    ) -> dict:
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        now = _now()
        expires_at = self._expires_at()
        self.conn.execute(
            """INSERT INTO messages
               (message_id, sender_id, recipient_id, room_id, kind, content_json, task_id,
                correlation_id, reply_to, created_at, expires_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                message_id,
                sender_id,
                recipient_id,
                room_id,
                kind,
                json.dumps(content, ensure_ascii=False),
                task_id,
                correlation_id,
                reply_to,
                now,
                expires_at,
            ),
        )
        self.conn.commit()
        return {
            "message_id": message_id,
            "to": recipient_id,
            "room_id": room_id,
            "kind": kind,
            "created_at": now,
            "expires_at": expires_at,
        }

    def _content_hash(self, content_json: str) -> str:
        return hashlib.sha256(str(content_json or "").encode("utf-8")).hexdigest()

    def purge_expired(self, *, limit: int = 500) -> dict:
        """删除过期正文，只保留长期审计元数据+内容哈希。"""
        now = _now()
        rows = self.conn.execute(
            """SELECT * FROM messages
               WHERE expires_at IS NOT NULL AND expires_at <= ?
               ORDER BY seq ASC LIMIT ?""",
            (now, max(1, min(int(limit or 500), 5000))),
        ).fetchall()
        purged = 0
        for row in rows:
            self.conn.execute(
                """INSERT INTO message_audit
                   (message_id, sender_id, recipient_id, room_id, kind, content_hash,
                    task_id, correlation_id, created_at, expires_at, purged_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row["message_id"],
                    row["sender_id"],
                    row["recipient_id"],
                    row["room_id"],
                    row["kind"],
                    self._content_hash(row["content_json"]),
                    row["task_id"],
                    row["correlation_id"],
                    row["created_at"],
                    row["expires_at"],
                    now,
                ),
            )
            self.conn.execute("DELETE FROM messages WHERE message_id=?", (row["message_id"],))
            purged += 1
        if purged:
            self.conn.commit()
        return {"purged": purged, "ttl_days": self.ttl_days}

    def recent_messages(self, *, limit: int = 30) -> list[dict]:
        self.purge_expired()
        rows = self.conn.execute(
            "SELECT * FROM messages ORDER BY seq DESC LIMIT ?",
            (max(1, min(int(limit or 30), 100)),),
        ).fetchall()
        return [
            {
                "message_id": row["message_id"],
                "seq": row["seq"],
                "sender": row["sender_id"],
                "recipient": row["recipient_id"],
                "room_id": row["room_id"],
                "kind": row["kind"],
                "content": _json(row["content_json"], {}),
                "task_id": row["task_id"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
            }
            for row in rows
        ]

    def send(
        self,
        *,
        to: str | None = None,
        room_id: str | None = None,
        kind: str = "chat",
        content: Any,
        correlation_id: str | None = None,
        reply_to: str | None = None,
        task_id: str | None = None,
    ) -> dict:
        self.purge_expired()
        if bool(to) == bool(room_id):
            raise CommError("INVALID_RECIPIENT", "to 与 room_id 必须二选一")
        kind = str(kind or "chat").strip()
        content = content if isinstance(content, dict) else {"text": str(content or "")}
        if to:
            if self._card(str(to)) is None:
                raise CommError("PEER_NOT_FOUND", f"Agent 不存在: {to}")
            recipient_id = str(to)
            room = None
        else:
            membership = self.conn.execute(
                "SELECT 1 FROM room_members WHERE room_id=? AND agent_id=?",
                (room_id, self.agent_id),
            ).fetchone()
            if membership is None:
                raise CommError("NOT_AUTHORIZED", "不在该群中")
            recipient_id = None
            room = str(room_id)
        return self._insert_message(
            sender_id=self.agent_id,
            recipient_id=recipient_id,
            room_id=room,
            kind=kind,
            content=content,
            task_id=task_id,
            correlation_id=correlation_id,
            reply_to=reply_to,
        )

    def read(self, *, cursor: int | None = None, limit: int = 20) -> dict:
        self.purge_expired()
        current = int(cursor if cursor is not None else self._cursor())
        limit = max(1, min(int(limit or 20), 100))
        rows = self.conn.execute(
            """SELECT DISTINCT m.*
               FROM messages m
               LEFT JOIN room_members rm ON rm.room_id=m.room_id AND rm.agent_id=?
               WHERE m.seq > ?
                 AND (m.recipient_id=? OR rm.agent_id IS NOT NULL)
               ORDER BY m.seq ASC LIMIT ?""",
            (self.agent_id, current, self.agent_id, limit),
        ).fetchall()
        messages = []
        next_cursor = current
        for row in rows:
            next_cursor = max(next_cursor, int(row["seq"]))
            messages.append(
                {
                    "message_id": row["message_id"],
                    "seq": row["seq"],
                    "sender": row["sender_id"],
                    "recipient": row["recipient_id"],
                    "room_id": row["room_id"],
                    "kind": row["kind"],
                    "content": _json(row["content_json"], {}),
                    "task_id": row["task_id"],
                    "correlation_id": row["correlation_id"],
                    "reply_to": row["reply_to"],
                    "created_at": row["created_at"],
                }
            )
        self._set_cursor(next_cursor)
        return {"messages": messages, "next_cursor": next_cursor, "has_more": len(messages) >= limit}

    def _cursor(self) -> int:
        row = self.conn.execute("SELECT cursor FROM cursors WHERE agent_id=?", (self.agent_id,)).fetchone()
        return int(row["cursor"]) if row else 0

    def _set_cursor(self, value: int) -> None:
        self.conn.execute(
            "INSERT INTO cursors (agent_id, cursor) VALUES (?,?) ON CONFLICT(agent_id) DO UPDATE SET cursor=excluded.cursor",
            (self.agent_id, int(value)),
        )
        self.conn.commit()

    def ack(self, message_ids: list[str]) -> dict:
        now = _now()
        accepted = 0
        for message_id in message_ids or []:
            row = self.conn.execute("SELECT 1 FROM messages WHERE message_id=?", (str(message_id),)).fetchone()
            if row is None:
                continue
            self.conn.execute(
                """INSERT INTO receipts (message_id, agent_id, state, updated_at)
                   VALUES (?,?,'read',?)
                   ON CONFLICT(message_id, agent_id) DO UPDATE SET state='read', updated_at=excluded.updated_at""",
                (str(message_id), self.agent_id, now),
            )
            accepted += 1
        self.conn.commit()
        return {"acked": accepted}

    def _risk_ok(self, risk: str, max_risk: str) -> bool:
        return RISK_ORDER.get(risk, 9) <= RISK_ORDER.get(max_risk, -1)

    def _pending_count(self, agent_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE assignee_id=? AND status IN ('ASSIGNED','RUNNING')",
            (agent_id,),
        ).fetchone()
        return int(row["n"] if row else 0)

    def propose_task(
        self,
        *,
        title: str,
        instruction: str = "",
        required_capabilities: list[str] | None = None,
        risk: str = "low",
        mode: str = "auto",
    ) -> dict:
        title = str(title or "").strip()[:120]
        if not title:
            raise CommError("INVALID_TASK", "任务标题不能为空")
        caps = [str(item).strip() for item in (required_capabilities or []) if str(item).strip()]
        caps = list(dict.fromkeys(caps))
        if not caps:
            raise CommError("INVALID_TASK", "required_capabilities 不能为空")
        risk = str(risk or "low").lower()
        mode = str(mode or "auto").lower()
        if risk not in RISK_ORDER:
            raise CommError("INVALID_RISK", "风险等级只能是 low / medium / high")
        if mode not in {"auto", "approval"}:
            raise CommError("INVALID_MODE", "模式只能是 auto / approval")
        candidates = []
        for card in self.list_agents():
            if card["agent_id"] == self.agent_id:
                continue
            if set(caps).issubset(set(card["capabilities"])):
                candidates.append(card)
        if not candidates:
            raise CommError("NO_ELIGIBLE_AGENT", f"没有 Agent 具备能力: {caps}")
        candidates.sort(key=lambda card: (self._pending_count(card["agent_id"]), card["agent_id"]))
        target = candidates[0]
        task_id = f"task_{uuid.uuid4().hex[:10]}"
        approval_id = None
        auto_ok = (
            mode == "auto"
            and target["auto_accept"]
            and self._risk_ok(risk, target["max_risk"])
        )
        status = "ASSIGNED" if auto_ok else "WAITING_APPROVAL"
        if not auto_ok:
            approval_id = f"appr_{uuid.uuid4().hex[:10]}"
            self.conn.execute(
                "INSERT INTO approvals (approval_id, task_id, status, reason, created_at) VALUES (?,?,'PENDING',?,?)",
                (approval_id, task_id, "requires human approval", _now()),
            )
        now = _now()
        self.conn.execute(
            """INSERT INTO tasks
               (task_id, title, instruction, required_capabilities_json, risk, mode, status,
                sender_id, assignee_id, approval_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id,
                title,
                str(instruction or "")[:4000],
                json.dumps(caps, ensure_ascii=False),
                risk,
                mode,
                status,
                self.agent_id,
                target["agent_id"],
                approval_id,
                now,
                now,
            ),
        )
        self.conn.commit()
        message = self.send(
            to=target["agent_id"],
            kind="task",
            content={
                "task_id": task_id,
                "title": title,
                "instruction": instruction,
                "required_capabilities": caps,
                "risk": risk,
                "mode": mode,
                "status": status,
                "approval_id": approval_id,
            },
            task_id=task_id,
        )
        return {
            "task_id": task_id,
            "status": status,
            "assignee": target["agent_id"],
            "approval_id": approval_id,
            "message_id": message["message_id"],
        }

    def task_status(self, task_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise CommError("TASK_NOT_FOUND", "任务不存在")
        data = dict(row)
        data["required_capabilities"] = _json(data.pop("required_capabilities_json"), [])
        return data

    def _approval_row(self, row: sqlite3.Row) -> dict:
        data = dict(row)
        data["required_capabilities"] = _json(data.pop("required_capabilities_json", []), [])
        return data

    def list_approvals(self, *, status: str | None = "PENDING", limit: int = 50) -> list[dict]:
        self.purge_expired()
        sql = """SELECT a.*, t.title, t.instruction, t.required_capabilities_json, t.risk,
                        t.mode, t.sender_id, t.assignee_id, t.status AS task_status
                 FROM approvals a JOIN tasks t ON t.task_id=a.task_id"""
        params: list[Any] = []
        if status:
            sql += " WHERE a.status=?"
            params.append(str(status).upper())
        sql += " ORDER BY a.created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit or 50), 200)))
        rows = self.conn.execute(sql, params).fetchall()
        return [self._approval_row(row) for row in rows]

    def get_approval(self, approval_id: str) -> dict | None:
        row = self.conn.execute(
            """SELECT a.*, t.title, t.instruction, t.required_capabilities_json, t.risk,
                      t.mode, t.sender_id, t.assignee_id, t.status AS task_status
               FROM approvals a JOIN tasks t ON t.task_id=a.task_id
               WHERE a.approval_id=?""",
            (approval_id,),
        ).fetchone()
        return self._approval_row(row) if row else None

    def decide_approval(self, approval_id: str, *, action: str, note: str = "", actor: str = "") -> dict:
        """人类审批：approve 后任务变为 ASSIGNED，reject 后变为 REJECTED。"""
        self.purge_expired()
        action = str(action or "").strip().lower()
        if action not in {"approve", "reject"}:
            raise CommError("INVALID_ACTION", "action 只能是 approve / reject")
        current = self.get_approval(approval_id)
        if current is None:
            raise CommError("APPROVAL_NOT_FOUND", "审批记录不存在")
        if current["status"] != "PENDING":
            current["idempotent"] = True
            return current
        now = _now()
        approval_status = "APPROVED" if action == "approve" else "REJECTED"
        task_status = "ASSIGNED" if action == "approve" else "REJECTED"
        self.conn.execute(
            """UPDATE approvals
               SET status=?, decided_by=?, decided_at=?, decision_note=?
               WHERE approval_id=?""",
            (approval_status, str(actor or "human"), now, str(note or "")[:1000], approval_id),
        )
        self.conn.execute(
            "UPDATE tasks SET status=?, updated_at=? WHERE task_id=?",
            (task_status, now, current["task_id"]),
        )
        human_id = f"human:{actor or 'admin'}"
        if action == "approve":
            self._insert_message(
                sender_id=human_id,
                recipient_id=current["assignee_id"],
                room_id=None,
                kind="task",
                content={
                    "task_id": current["task_id"],
                    "title": current["title"],
                    "instruction": current["instruction"],
                    "required_capabilities": current["required_capabilities"],
                    "risk": current["risk"],
                    "mode": current["mode"],
                    "status": "ASSIGNED",
                    "approval_id": approval_id,
                    "approved_by": actor,
                },
                task_id=current["task_id"],
            )
        else:
            self._insert_message(
                sender_id=human_id,
                recipient_id=current["sender_id"],
                room_id=None,
                kind="task_rejected",
                content={
                    "task_id": current["task_id"],
                    "title": current["title"],
                    "status": "REJECTED",
                    "approval_id": approval_id,
                    "reason": str(note or "human rejected"),
                },
                task_id=current["task_id"],
            )
        self.conn.commit()
        result = self.get_approval(approval_id) or current
        result["idempotent"] = False
        return result

    def list_tasks(self, *, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            """SELECT * FROM tasks
               WHERE sender_id=? OR assignee_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (self.agent_id, self.agent_id, max(1, min(int(limit or 20), 100))),
        ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["required_capabilities"] = _json(data.pop("required_capabilities_json"), [])
            result.append(data)
        return result


def open_admin_store(*, config_path: str | None = None, db_path: str | None = None) -> AgentCommStore:
    """人类控制台使用：能力校验不针对人类，选配置中的第一个 Agent 打开同一个 Bus。"""
    cards = load_config(config_path)
    return AgentCommStore(
        agent_id=next(iter(cards)),
        config_path=config_path,
        db_path=db_path,
    )
