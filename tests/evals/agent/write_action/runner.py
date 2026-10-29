# -*- coding: utf-8 -*-
"""B 端受控写 Eval Runner：prepare_followup_task + HITL 用户确认。

确定性 Eval：
- 不接真实 LLM：ScriptedLLM 按 dataset 返回固定 AIMessage 轨迹；
- 不接网络 / 真实业务库：每个 case 使用独立 SQLite（QIANKE_AGENT_ACTION_DB + 重置 actions._DB_PATH）；
- 复用真实链路：loop.run_agent（LangGraph + ToolNode + ToolPolicy 执行前复核）、
  actions.action_scope、actions.create_followup_draft / confirm_action / cancel_action。

运行：
    python tests/evals/agent/write_action/runner.py                  # 跑全量，stdout 输出 JSON 摘要
    python tests/evals/agent/write_action/runner.py --validate-only  # 只校验数据集
    python tests/evals/agent/write_action/runner.py --output out.json

退出码：全部通过 0；存在失败 1；数据集非法 2。

本模块同时被 tests/test_agent_write_action_eval.py 复用（不另写一套判分逻辑）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402

from rag_demo.agent import actions, loop  # noqa: E402
from rag_demo.agent.policy import ToolPolicy  # noqa: E402
from rag_demo.agent.state import AgentConfig  # noqa: E402
from rag_demo.agent.tools.action import prepare_followup_task  # noqa: E402

SUITE_VERSION = "agent-write-action-eval-v1"
DATASET_PATH = Path(__file__).with_name("dataset.v1.json")

TOOL_NAME = "prepare_followup_task"
ACTION_TYPE = "followup_task"
ACTION_TABLE = "agent_action"
ACTION_DB_NAME = "agent_actions.sqlite"
ACTION_INDEX = "idx_agent_action_request"

EXPECTED_ACTION_COLUMNS = [
    "action_id",
    "account_id",
    "dataset",
    "request_id",
    "action_type",
    "title",
    "description",
    "owner",
    "priority",
    "due_date",
    "status",
    "created_at",
    "confirmed_at",
    "confirmed_by",
    "completed_at",
]

CASE_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")

# 显式写意图的确定性标记：命中任一即视为“用户明确要求创建任务/待办/跟进”。
# 对应 docs/agent-write-action.md 与 SYSTEM_PROMPT 中的门槛规则。
INTENT_MARKERS = (
    "创建任务",
    "创建一条任务",
    "创建一条跟进任务",
    "建任务",
    "建个任务",
    "安排跟进",
    "安排成跟进",
    "安排成任务",
    "记录成待办",
    "记成待办",
    "加个待办",
    "生成跟进任务",
    "生成待办",
    "落成任务",
)

# 沙箱“业务表”：只用于快照对照，证明写动作没有碰业务数据。
BUSINESS_TABLE_SPECS: dict[str, dict[str, Any]] = {
    "orders": {
        "ddl": "order_id TEXT PRIMARY KEY, amount INTEGER NOT NULL",
        "rows": [("o1", 100), ("o2", 260)],
    },
    "customers": {
        "ddl": "customer_id TEXT PRIMARY KEY, segment TEXT NOT NULL",
        "rows": [("c1", "silent"), ("c2", "active")],
    },
    "coupon_grants": {
        "ddl": "grant_id TEXT PRIMARY KEY, status TEXT NOT NULL",
        "rows": [("g1", "unused"), ("g2", "used")],
    },
}

_WRITE_SQL_RE = re.compile(
    r"\b(?P<verb>INSERT\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|"
    r"TRUNCATE\s+TABLE|DROP\s+TABLE|ALTER\s+TABLE)\s+"
    r"(?P<table>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_DDL_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)

# 七个必需覆盖维度（task-34 验收点）→ 允许落入该维度的 case category。
REQUIRED_COVERAGE: dict[str, frozenset[str]] = {
    "no_draft_without_intent": frozenset({"no_write_intent"}),
    "draft_with_explicit_intent": frozenset({"explicit_write_intent"}),
    "draft_to_confirmed": frozenset({"hitl_confirm"}),
    "permission_demo_cs_guest": frozenset(
        {"permission_cs", "permission_guest", "permission_demo"}
    ),
    "cross_account_confirm_denied": frozenset({"hitl_cross_account"}),
    "duplicate_confirm_denied": frozenset({"hitl_duplicate_confirm"}),
    "only_agent_action_table_written": frozenset({"write_isolation"}),
}

# 额外覆盖（不在 task-34 必需清单内，但同一份数据里顺带验证）。
EXTRA_COVERAGE: dict[str, frozenset[str]] = {
    "hitl_cancel": frozenset({"hitl_cancel"}),
    "permission_allowed_roles": frozenset({"permission_allowed_roles"}),
}

ALLOWED_COVERAGE: dict[str, frozenset[str]] = {
    **REQUIRED_COVERAGE,
    **EXTRA_COVERAGE,
}


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def has_explicit_write_intent(query: str) -> bool:
    """确定性写意图判定：只认显式“创建任务/安排跟进/记录成待办”等措辞。"""
    text = str(query or "")
    return any(marker in text for marker in INTENT_MARKERS)


def load_dataset(path: str | Path | None = None) -> dict[str, Any]:
    dataset_path = Path(path) if path is not None else DATASET_PATH
    return json.loads(dataset_path.read_text(encoding="utf-8"))


class Checks:
    """收集单个 case 的断言结果，保证 JSON 可序列化。"""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.items.append(
            {
                "name": name,
                "ok": bool(ok),
                "detail": "" if ok else str(detail),
            }
        )
        return bool(ok)

    def eq(self, name: str, actual: Any, expected: Any) -> bool:
        ok = actual == expected
        detail = "" if ok else f"expected={expected!r} actual={actual!r}"
        return self.check(name, ok, detail)


class ScriptedLLM:
    """确定性 LLM 桩：按预置 AIMessage 轨迹逐次返回，不接真实模型。"""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def invoke(self, messages: Any) -> AIMessage:  # noqa: ARG002 - 契约签名
        self.calls += 1
        if not self._responses:
            raise RuntimeError("ScriptedLLM 轨迹已耗尽，case 脚本与实际调用次数不一致")
        return self._responses.pop(0)


@contextmanager
def _patched_agent(llm: ScriptedLLM) -> Iterator[None]:
    """替换 LLM 与 System Prompt 构建，避免真实模型 / 数据库 schema 依赖。"""
    original_get_llm = loop.get_llm
    original_build_prompt = loop.build_system_prompt
    loop.get_llm = lambda allowed_tools=None: llm  # noqa: ARG005 - 兼容两种调用签名
    loop.build_system_prompt = lambda config=None: "qianke-write-action-eval-system-prompt"  # noqa: ARG005
    try:
        yield
    finally:
        loop.get_llm = original_get_llm
        loop.build_system_prompt = original_build_prompt


@contextmanager
def _case_action_db(case_dir: Path) -> Iterator[Path]:
    """每个 case 独立 SQLite：设置 QIANKE_AGENT_ACTION_DB 并重置 actions._DB_PATH。"""
    db_path = case_dir / "var" / ACTION_DB_NAME
    db_path.parent.mkdir(parents=True, exist_ok=True)
    previous_env = os.environ.get("QIANKE_AGENT_ACTION_DB")
    previous_db_path = actions._DB_PATH
    os.environ["QIANKE_AGENT_ACTION_DB"] = str(db_path)
    actions._DB_PATH = None
    try:
        yield db_path
    finally:
        actions._DB_PATH = previous_db_path
        if previous_env is None:
            os.environ.pop("QIANKE_AGENT_ACTION_DB", None)
        else:
            os.environ["QIANKE_AGENT_ACTION_DB"] = previous_env


def _account(dataset: dict[str, Any], key: str) -> dict[str, Any]:
    return dataset["accounts"][key]


def _scripted_responses(
    script: list[dict[str, Any]] | None, final_answer: str
) -> list[AIMessage]:
    responses: list[AIMessage] = []
    for turn_index, turn in enumerate(script or []):
        tool_calls = []
        for call_index, call in enumerate(turn.get("tool_calls") or []):
            tool_calls.append(
                {
                    "name": call["name"],
                    "args": call.get("args") or {},
                    "id": call.get("id") or f"call_{turn_index}_{call_index}",
                    "type": "tool_call",
                }
            )
        responses.append(AIMessage(content="", tool_calls=tool_calls))
    responses.append(AIMessage(content=final_answer or ""))
    return responses


def _run_scripted_agent(
    *,
    dataset_name: str,
    account: dict[str, Any],
    request_id: str,
    query: str,
    script: list[dict[str, Any]] | None,
    final_answer: str,
    max_steps: int = 4,
    max_tool_calls: int = 3,
) -> tuple[dict[str, Any], ScriptedLLM, list[str]]:
    allowed = list(ToolPolicy.for_account(account).allowed_tools(account))
    if not allowed:
        raise RuntimeError("当前账号没有任何可见 Tool，无法运行 agent_trajectory case")
    llm = ScriptedLLM(_scripted_responses(script, final_answer))
    with _patched_agent(llm):
        with actions.action_scope(dataset_name, account, request_id):
            result = loop.run_agent(
                query,
                config=AgentConfig(max_steps=max_steps, max_tool_calls=max_tool_calls),
                request_id=request_id,
                allowed_tools=allowed,
            )
    return result, llm, allowed


def _write_tool_payloads(result: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for message in result.get("messages") or []:
        if isinstance(message, ToolMessage) and getattr(message, "name", None) == TOOL_NAME:
            try:
                payloads.append(json.loads(message.content))
            except (TypeError, json.JSONDecodeError):
                payloads.append({"ok": False, "parse_error": str(message.content)[:200]})
    return payloads


def _requested_write_calls(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        call
        for call in result.get("tool_calls") or []
        if call.get("name") == TOOL_NAME
    ]


def _write_statements(source: str) -> list[dict[str, str]]:
    """扫描源码中的写 SQL 目标表（只用于契约断言，不执行任何 SQL）。"""
    statements: list[dict[str, str]] = []
    for match in _WRITE_SQL_RE.finditer(source):
        verb = " ".join(match.group("verb").upper().split())
        statements.append({"verb": verb, "table": match.group("table").lower()})
    return statements


def _ddl_table_targets(source: str) -> list[str]:
    return [match.group(1).lower() for match in _DDL_TABLE_RE.finditer(source)]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_business_db(path: Path, tables: list[str]) -> None:
    conn = sqlite3.connect(path)
    try:
        for table in tables:
            spec = BUSINESS_TABLE_SPECS[table]
            conn.execute(f"CREATE TABLE {table}({spec['ddl']})")
            columns = [part.strip().split()[0] for part in spec["ddl"].split(",")]
            placeholders = ", ".join("?" for _ in columns)
            conn.executemany(
                f"INSERT INTO {table} VALUES ({placeholders})", spec["rows"]
            )
        conn.commit()
    finally:
        conn.close()


def _business_snapshot(path: Path, tables: list[str]) -> dict[str, list[dict[str, Any]]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        snapshot: dict[str, list[dict[str, Any]]] = {}
        for table in tables:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            snapshot[table] = [dict(row) for row in rows]
        return snapshot
    finally:
        conn.close()


def _sqlite_tables(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def _sqlite_indexes(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL ORDER BY name"
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def _sqlite_columns(path: Path, table: str) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return [row[1] for row in rows]
    finally:
        conn.close()


def _sqlite_rows(path: Path, table: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY created_at, action_id").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 场景：agent 轨迹（意图门槛 / 显式写 / 越权 Tool 调用）
# ---------------------------------------------------------------------------


def _scenario_agent_trajectory(
    case: dict[str, Any],
    dataset: dict[str, Any],
    case_dir: Path,
    db_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = case["params"]
    expect = case["expect"]
    account = _account(dataset, params["account"])
    dataset_name = params.get("dataset", "test")
    request_id = params["request_id"]
    query = params["query"]
    checks = Checks()

    if "query_has_explicit_write_intent" in expect:
        checks.eq(
            "query_explicit_write_intent",
            has_explicit_write_intent(query),
            expect["query_has_explicit_write_intent"],
        )

    allowed = list(ToolPolicy.for_account(account).allowed_tools(account))
    if not allowed:
        checks.check("agent_tools_available", False, "policy 未给该账号任何 Tool")
        return checks.items, {"agent_tools": []}
    checks.check("agent_tools_available", True)

    result, llm, allowed = _run_scripted_agent(
        dataset_name=dataset_name,
        account=account,
        request_id=request_id,
        query=query,
        script=params.get("script"),
        final_answer=params.get("final_answer", ""),
    )
    payloads = _write_tool_payloads(result)
    requested = _requested_write_calls(result)
    drafts = actions.list_for_request(request_id, account)

    checks.eq("agent_status", result.get("status"), expect.get("status", "COMPLETED"))
    checks.eq("llm_invocations", llm.calls, expect.get("llm_invocations", len(params.get("script") or []) + 1))
    checks.eq("write_tool_requests", len(requested), expect.get("write_tool_requests", 0))
    checks.eq("write_tool_results", len(payloads), expect.get("write_tool_results", 0))
    checks.eq("followup_drafts", len(drafts), expect.get("followup_drafts", 0))
    checks.eq("agent_tool_call_count", result.get("tool_call_count"), len(requested) + _count_readonly_calls(result))

    if expect.get("tool_results_ok"):
        checks.check(
            "write_tool_ok",
            bool(payloads) and all(payload.get("ok") is True for payload in payloads),
            [payload.get("error") for payload in payloads],
        )
    if "requires_confirmation" in expect:
        checks.check(
            "requires_confirmation",
            bool(payloads)
            and all(
                payload.get("requires_confirmation") is expect["requires_confirmation"]
                for payload in payloads
            ),
            payloads,
        )
    if "draft_status" in expect:
        checks.check(
            "draft_status",
            bool(drafts) and all(row["status"] == expect["draft_status"] for row in drafts),
            [row["status"] for row in drafts],
        )
    for field, expected in (expect.get("draft_fields") or {}).items():
        checks.check(
            f"draft.{field}",
            bool(drafts) and all(row.get(field) == expected for row in drafts),
            [row.get(field) for row in drafts],
        )
    if expect.get("scope_binding"):
        checks.check(
            "scope_binding",
            bool(drafts)
            and all(
                row["account_id"] == account["id"]
                and row["dataset"] == dataset_name
                and row["request_id"] == request_id
                for row in drafts
            ),
            drafts,
        )
    for keyword in expect.get("final_contains") or []:
        checks.check(
            f"final_contains:{keyword}",
            keyword in str(result.get("final_answer") or ""),
            result.get("final_answer"),
        )

    detail = {
        "status": result.get("status"),
        "llm_invocations": llm.calls,
        "tool_calls": [call.get("name") for call in result.get("tool_calls") or []],
        "followup_drafts": len(drafts),
        "final_answer": result.get("final_answer"),
        "allowed_tools": allowed,
    }
    return checks.items, detail


def _count_readonly_calls(result: dict[str, Any]) -> int:
    return sum(
        1
        for message in result.get("messages") or []
        if isinstance(message, ToolMessage) and getattr(message, "name", None) != TOOL_NAME
    )


# ---------------------------------------------------------------------------
# 场景：HITL 确认 / 取消 / 重复 / 跨账号
# ---------------------------------------------------------------------------


def _scenario_hitl(
    case: dict[str, Any],
    dataset: dict[str, Any],
    case_dir: Path,
    db_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = case["params"]
    expect = case["expect"]
    owner = _account(dataset, params["account"])
    dataset_name = params.get("dataset", "test")
    request_id = params["request_id"]
    checks = Checks()

    with actions.action_scope(dataset_name, owner, request_id):
        draft = actions.create_followup_draft(
            title=params["title"],
            description=params.get("description", ""),
            owner=params.get("owner", ""),
            priority=params.get("priority", "normal"),
        )
    checks.eq("initial_status", draft["status"], "DRAFT")

    steps = params.get("steps") or []
    expected_steps = expect.get("steps") or []
    checks.eq("step_count", len(steps), len(expected_steps))
    step_details: list[dict[str, Any]] = []
    for index, (step, step_expect) in enumerate(zip(steps, expected_steps), start=1):
        actor = _account(dataset, step["account"])
        error_code: str | None = None
        row: dict[str, Any] | None = None
        try:
            if step["action"] == "confirm":
                row = actions.confirm_action(draft["action_id"], actor)
            elif step["action"] == "cancel":
                row = actions.cancel_action(draft["action_id"], actor)
            else:  # pragma: no cover - dataset 校验已挡住
                raise ValueError(f"未知 HITL 动作：{step['action']}")
        except actions.ActionError as exc:
            error_code = exc.code
        checks.eq(f"step{index}.error", error_code, step_expect.get("error"))
        if "status" in step_expect:
            checks.check(
                f"step{index}.status",
                row is not None and row.get("status") == step_expect["status"],
                row.get("status") if row else None,
            )
        step_details.append(
            {
                "action": step["action"],
                "account": step["account"],
                "error": error_code,
                "status": row.get("status") if row else None,
            }
        )

    rows = actions.list_for_request(request_id, owner)
    checks.eq("action_rows", len(rows), 1)
    final = rows[0] if rows else {}
    checks.eq("final_status", final.get("status"), expect.get("final_status"))
    if "final_confirmed_by" in expect:
        checks.eq("final_confirmed_by", final.get("confirmed_by"), expect["final_confirmed_by"])
    if "final_confirmed_at_null" in expect:
        checks.check(
            "final_confirmed_at_null",
            (final.get("confirmed_at") is None) is expect["final_confirmed_at_null"],
            final.get("confirmed_at"),
        )
    checks.eq("final_action_type", final.get("action_type"), ACTION_TYPE)

    detail = {
        "steps": step_details,
        "final_status": final.get("status"),
        "confirmed_by": final.get("confirmed_by"),
    }
    return checks.items, detail


# ---------------------------------------------------------------------------
# 场景：Tool 权限矩阵（可见性 + 执行层拒绝）
# ---------------------------------------------------------------------------


def _scenario_permission(
    case: dict[str, Any],
    dataset: dict[str, Any],
    case_dir: Path,
    db_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = case["params"]
    expect = case["expect"]
    dataset_name = params.get("dataset", "test")
    checks = Checks()
    detail: dict[str, Any] = {"accounts": {}}

    for key in params["accounts"]:
        account = _account(dataset, key)
        policy = ToolPolicy.for_account(account)
        visible_tools = policy.allowed_tools(account)
        visible = TOOL_NAME in visible_tools
        authorized = policy.authorize(TOOL_NAME, account)
        can_start = bool(visible_tools)

        checks.eq(f"{key}.write_tool_visible", visible, expect["write_tool_visible"])
        checks.eq(f"{key}.authorized", authorized, expect["authorized"])
        checks.eq(f"{key}.agent_can_start", can_start, expect["agent_can_start"])
        account_detail: dict[str, Any] = {
            "id": account["id"],
            "visible_tools": list(visible_tools),
            "authorized": authorized,
            "agent_can_start": can_start,
        }

        if expect.get("execution_error"):
            request_id = f"{params['request_id']}_{key}"
            with actions.action_scope(dataset_name, account, request_id):
                payload = prepare_followup_task.invoke(
                    {
                        "title": "权限探针任务",
                        "description": "",
                        "owner": "",
                        "priority": "normal",
                        "due_date": "",
                    }
                )
            checks.eq(f"{key}.execution_ok", payload.get("ok"), False)
            checks.eq(
                f"{key}.execution_error",
                (payload.get("error") or {}).get("code"),
                expect["execution_error"],
            )
            drafts = actions.list_for_request(request_id, account)
            checks.eq(f"{key}.drafts", len(drafts), 0)
            account_detail["execution_error"] = (payload.get("error") or {}).get("code")

        detail["accounts"][key] = account_detail

    return checks.items, detail


# ---------------------------------------------------------------------------
# 场景：写入隔离（只写 agent_action / 业务表快照不变 / 源码写目标扫描）
# ---------------------------------------------------------------------------


def _scenario_isolation(
    case: dict[str, Any],
    dataset: dict[str, Any],
    case_dir: Path,
    db_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = case["params"]
    expect = case["expect"]
    account = _account(dataset, params["account"])
    dataset_name = params.get("dataset", "test")
    request_id = params["request_id"]
    business_tables = list(params["business_tables"])
    checks = Checks()

    business_db = case_dir / "business.sqlite"
    _seed_business_db(business_db, business_tables)
    business_hash_before = _sha256_file(business_db)
    business_rows_before = _business_snapshot(business_db, business_tables)

    result, _llm, _allowed = _run_scripted_agent(
        dataset_name=dataset_name,
        account=account,
        request_id=request_id,
        query=params["query"],
        script=params.get("script"),
        final_answer=params.get("final_answer", ""),
    )
    drafts = actions.list_for_request(request_id, account)
    checks.eq("agent_status", result.get("status"), "COMPLETED")
    checks.eq("drafts_before_confirm", len(drafts), 1)
    confirmed = actions.confirm_action(drafts[0]["action_id"], account) if drafts else {}
    checks.eq("confirm_status", confirmed.get("status"), "CONFIRMED")

    # 1) 业务表快照：内容与哈希都不变
    checks.check(
        "business_db_hash_unchanged",
        _sha256_file(business_db) == business_hash_before,
        "业务库文件内容被修改",
    )
    checks.eq(
        "business_rows_unchanged",
        _business_snapshot(business_db, business_tables),
        business_rows_before,
    )

    # 2) 动作库只包含 agent_action 表与约定索引
    tables = _sqlite_tables(db_path)
    checks.eq("action_db_tables", tables, [ACTION_TABLE])
    checks.check(
        "no_business_tables_in_action_db",
        not (set(tables) & set(business_tables)),
        tables,
    )
    checks.check(
        "action_index_created",
        ACTION_INDEX in _sqlite_indexes(db_path),
        _sqlite_indexes(db_path),
    )
    checks.eq("action_table_columns", _sqlite_columns(db_path, ACTION_TABLE), EXPECTED_ACTION_COLUMNS)

    # 3) 动作表快照：只有一条 CONFIRMED 记录，字段绑定正确
    rows = _sqlite_rows(db_path, ACTION_TABLE)
    checks.eq("action_rows", len(rows), expect["action_rows"])
    final = rows[0] if rows else {}
    checks.eq("row_action_type", final.get("action_type"), ACTION_TYPE)
    checks.eq("row_status", final.get("status"), expect["final_status"])
    checks.eq("row_account_id", final.get("account_id"), account["id"])
    checks.eq("row_dataset", final.get("dataset"), dataset_name)
    checks.eq("row_request_id", final.get("request_id"), request_id)
    checks.check("row_confirmed_by", final.get("confirmed_by") == account["id"], final.get("confirmed_by"))
    checks.check("row_confirmed_at_set", bool(final.get("confirmed_at")), final.get("confirmed_at"))
    checks.check("row_created_at_set", bool(final.get("created_at")), final.get("created_at"))

    # 4) 源码写目标扫描：写动作只允许落到 agent_action
    actions_source = (SRC_DIR / "rag_demo" / "agent" / "actions.py").read_text(encoding="utf-8")
    tool_source = (SRC_DIR / "rag_demo" / "agent" / "tools" / "action.py").read_text(encoding="utf-8")
    statements = _write_statements(actions_source)
    checks.eq("source_write_tables", sorted({row["table"] for row in statements}), [ACTION_TABLE])
    checks.eq(
        "source_write_verbs",
        sorted({row["verb"] for row in statements}),
        ["ALTER TABLE", "INSERT INTO", "UPDATE"],
    )
    checks.eq("source_ddl_tables", sorted(set(_ddl_table_targets(actions_source))), [ACTION_TABLE])
    checks.check(
        "tool_module_has_no_sql_write",
        not _write_statements(tool_source) and not _ddl_table_targets(tool_source),
        _write_statements(tool_source),
    )

    # 5) 沙箱内只有两个 sqlite 文件：业务库 + 动作库
    sqlite_files = sorted(
        path.relative_to(case_dir).as_posix() for path in case_dir.rglob("*.sqlite")
    )
    checks.eq("sandbox_sqlite_files", sqlite_files, ["business.sqlite", f"var/{ACTION_DB_NAME}"])

    detail = {
        "business_tables": business_tables,
        "action_db_tables": tables,
        "action_rows": len(rows),
        "final_status": final.get("status"),
        "write_targets": sorted({row["table"] for row in statements}),
    }
    return checks.items, detail


SCENARIOS = {
    "agent_trajectory": _scenario_agent_trajectory,
    "hitl": _scenario_hitl,
    "permission": _scenario_permission,
    "isolation": _scenario_isolation,
}


def _run_case(
    case: dict[str, Any],
    dataset: dict[str, Any],
    case_dir: Path,
    db_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    handler = SCENARIOS.get(case["scenario"])
    if handler is None:  # pragma: no cover - dataset 校验已挡住
        raise ValueError(f"未知场景：{case['scenario']}")
    return handler(case, dataset, case_dir, db_path)


# ---------------------------------------------------------------------------
# 数据集契约校验
# ---------------------------------------------------------------------------


def validate_dataset(dataset: dict[str, Any]) -> list[str]:
    """返回问题清单；空列表代表数据集满足契约。"""
    problems: list[str] = []

    def add(message: str) -> None:
        problems.append(message)

    for key in (
        "version",
        "suite",
        "title",
        "status",
        "baseline",
        "dataset",
        "related_doc",
        "contract_doc",
        "tool",
        "action_type",
    ):
        if not isinstance(dataset.get(key), str) or not dataset.get(key, "").strip():
            add(f"缺少或非法字段：{key}")
    if dataset.get("version") != SUITE_VERSION:
        add(f"version 必须为 {SUITE_VERSION}")
    if dataset.get("status") != "deterministic":
        add("status 必须为 deterministic（本套 Eval 不依赖真实模型）")
    if dataset.get("baseline") != "not_required":
        add("baseline 必须为 not_required（确定性 Eval 不需要真实模型基线）")
    if dataset.get("suite") != "write_action":
        add("suite 必须为 write_action")
    if dataset.get("tool") != TOOL_NAME:
        add(f"tool 必须为 {TOOL_NAME}")
    if dataset.get("action_type") != ACTION_TYPE:
        add(f"action_type 必须为 {ACTION_TYPE}")

    accounts = dataset.get("accounts")
    if not isinstance(accounts, dict) or not accounts:
        add("accounts 缺失或为空")
        accounts = {}
    seen_account_ids: set[str] = set()
    for key, account in accounts.items():
        if not isinstance(key, str) or not CASE_ID_PATTERN.fullmatch(key):
            add(f"accounts 的 key 非法：{key!r}")
        if not isinstance(account, dict) or not str(account.get("id") or ""):
            add(f"账号 {key} 缺少 id")
            continue
        if account["id"] in seen_account_ids:
            add(f"账号 id 重复：{account['id']}")
        seen_account_ids.add(account["id"])

    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        add("cases 缺失或为空")
        return problems

    categories_by_id: dict[str, str] = {}
    seen_cases: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            add("cases 存在非对象元素")
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
            add(f"case id 非法：{case_id!r}")
            continue
        if case_id in seen_cases:
            add(f"case id 重复：{case_id}")
            continue
        seen_cases.add(case_id)
        category = case.get("category")
        if not isinstance(category, str) or not category:
            add(f"{case_id} 缺少 category")
            category = ""
        categories_by_id[case_id] = category
        scenario = case.get("scenario")
        if scenario not in SCENARIOS:
            add(f"{case_id} 的 scenario 非法：{scenario!r}")
        params = case.get("params")
        expect = case.get("expect")
        if not isinstance(params, dict):
            add(f"{case_id} 缺少 params")
            continue
        if not isinstance(expect, dict):
            add(f"{case_id} 缺少 expect")
            continue

        referenced = []
        if "account" in params:
            referenced.append(params["account"])
        referenced.extend(params.get("accounts") or [])
        referenced.extend(
            step.get("account")
            for step in params.get("steps") or []
            if isinstance(step, dict) and step.get("account")
        )
        for ref in referenced:
            if ref not in accounts:
                add(f"{case_id} 引用了不存在的账号：{ref!r}")

        if scenario == "hitl":
            steps = params.get("steps") or []
            expected_steps = expect.get("steps") or []
            if not steps:
                add(f"{case_id} hitl 场景缺少 steps")
            if len(steps) != len(expected_steps):
                add(f"{case_id} steps 与 expect.steps 长度不一致")
        if scenario == "agent_trajectory":
            if not isinstance(params.get("query"), str) or not params.get("query"):
                add(f"{case_id} 缺少 query")
            for turn in params.get("script") or []:
                for call in turn.get("tool_calls") or []:
                    if call.get("name") == TOOL_NAME and not isinstance(call.get("args"), dict):
                        add(f"{case_id} 的 prepare_followup_task 调用缺少 args")
        if scenario == "permission":
            if not params.get("accounts"):
                add(f"{case_id} permission 场景缺少 accounts")
            for key in ("write_tool_visible", "authorized", "agent_can_start"):
                if not isinstance(expect.get(key), bool):
                    add(f"{case_id} 缺少布尔期望：{key}")
        if scenario == "isolation":
            business_tables = params.get("business_tables")
            if not isinstance(business_tables, list) or not business_tables:
                add(f"{case_id} isolation 场景缺少 business_tables")
            else:
                if ACTION_TABLE in business_tables:
                    add(f"{case_id} 的业务表不能包含动作表 {ACTION_TABLE}")
                unknown = set(business_tables) - set(BUSINESS_TABLE_SPECS)
                if unknown:
                    add(f"{case_id} 含未知业务表：{sorted(unknown)}")

        if category == "no_write_intent":
            if has_explicit_write_intent(str(params.get("query") or "")):
                add(f"{case_id} 标为无写意图，但 query 命中显式写意图标记")
            if expect.get("followup_drafts") != 0:
                add(f"{case_id} 无写意图用例必须期望 0 个 DRAFT")
            if expect.get("write_tool_results") != 0:
                add(f"{case_id} 无写意图用例必须期望 0 次写工具结果")
        if category == "explicit_write_intent":
            if not has_explicit_write_intent(str(params.get("query") or "")):
                add(f"{case_id} 标为显式写意图，但 query 未命中任何写意图标记")
            if int(expect.get("followup_drafts") or 0) < 1:
                add(f"{case_id} 显式写意图用例必须期望生成 DRAFT")
            if int(expect.get("write_tool_results") or 0) < 1:
                add(f"{case_id} 显式写意图用例必须期望写工具成功执行")

    coverage = dataset.get("coverage")
    if not isinstance(coverage, dict) or not coverage:
        add("coverage 缺失或为空")
        return problems
    missing_dimensions = set(REQUIRED_COVERAGE) - set(coverage)
    if missing_dimensions:
        add(f"coverage 缺少必需维度：{sorted(missing_dimensions)}")
    unknown_dimensions = set(coverage) - set(ALLOWED_COVERAGE)
    if unknown_dimensions:
        add(f"coverage 含未知维度：{sorted(unknown_dimensions)}")

    covered_cases: set[str] = set()
    for dimension, case_ids in coverage.items():
        allowed_categories = ALLOWED_COVERAGE.get(dimension, frozenset())
        if not isinstance(case_ids, list) or not case_ids:
            add(f"coverage.{dimension} 必须是非空列表")
            continue
        for case_id in case_ids:
            if case_id not in seen_cases:
                add(f"coverage.{dimension} 引用了不存在的 case：{case_id}")
                continue
            if case_id in covered_cases:
                add(f"case 被多个 coverage 维度重复引用：{case_id}")
            covered_cases.add(case_id)
            category = categories_by_id.get(case_id, "")
            if category not in allowed_categories:
                add(
                    f"coverage.{dimension} 的 case {case_id} 分类为 {category}，"
                    f"不在允许集合 {sorted(allowed_categories)}"
                )
    uncovered = seen_cases - covered_cases
    if uncovered:
        add(f"未被 coverage 覆盖的 case：{sorted(uncovered)}")
    return problems


# ---------------------------------------------------------------------------
# Suite 执行与汇总
# ---------------------------------------------------------------------------


def run_suite(
    workdir: str | Path,
    dataset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行整套确定性 Eval，返回 JSON 可序列化摘要（含 pass_rate）。"""
    dataset = dataset or load_dataset()
    problems = validate_dataset(dataset)
    if problems:
        raise ValueError("Eval 数据集非法：" + "；".join(problems))

    root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    case_results: list[dict[str, Any]] = []

    for case in dataset["cases"]:
        case_dir = root / case["id"]
        if case_dir.exists():
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True)
        try:
            with _case_action_db(case_dir) as db_path:
                checks, detail = _run_case(case, dataset, case_dir, db_path)
        except Exception as exc:  # noqa: BLE001 - 单个 case 崩溃不应吞掉其它结果
            checks = [
                {
                    "name": "case_executed",
                    "ok": False,
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            ]
            detail = {}
        passed = bool(checks) and all(check["ok"] for check in checks)
        case_results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "scenario": case["scenario"],
                "status": "PASS" if passed else "FAIL",
                "checks": checks,
                "detail": detail,
            }
        )

    total = len(case_results)
    passed = sum(1 for row in case_results if row["status"] == "PASS")
    failed = total - passed
    by_category: dict[str, dict[str, Any]] = {}
    for row in case_results:
        bucket = by_category.setdefault(
            row["category"], {"total": 0, "passed": 0, "pass_rate": 0.0}
        )
        bucket["total"] += 1
        if row["status"] == "PASS":
            bucket["passed"] += 1
    for bucket in by_category.values():
        bucket["pass_rate"] = round(bucket["passed"] / bucket["total"], 4)

    check_total = sum(len(row["checks"]) for row in case_results)
    check_passed = sum(
        1 for row in case_results for check in row["checks"] if check["ok"]
    )

    return {
        "suite": dataset["suite"],
        "version": dataset["version"],
        "deterministic": True,
        "llm": "scripted",
        "network": "none",
        "storage": "per-case-tmp-sqlite",
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "check_total": check_total,
        "check_passed": check_passed,
        "by_category": by_category,
        "failed_cases": [row["id"] for row in case_results if row["status"] == "FAIL"],
        "cases": case_results,
    }


def _emit(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:  # Windows 管道默认 gbk，显式切 UTF-8，避免中文摘要写不出来
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError, OSError):
        pass
    print(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="B 端受控写确定性 Eval runner（prepare_followup_task + HITL）"
    )
    parser.add_argument("--dataset", default=str(DATASET_PATH), help="dataset.v1.json 路径")
    parser.add_argument("--validate-only", action="store_true", help="只校验数据集，不执行用例")
    parser.add_argument("--workdir", default=None, help="可选：动作 DB 沙箱目录（默认临时目录）")
    parser.add_argument("--output", default=None, help="可选：把 JSON 摘要写入指定文件")
    args = parser.parse_args(argv)

    try:
        dataset = load_dataset(args.dataset)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"数据集读取失败：{exc}\n")
        return 2

    problems = validate_dataset(dataset)
    if problems:
        _emit(
            {
                "suite": dataset.get("suite", "write_action"),
                "version": dataset.get("version"),
                "valid": False,
                "problems": problems,
                "total": 0,
                "pass_rate": 0.0,
            }
        )
        return 2

    if args.validate_only:
        _emit(
            {
                "suite": dataset["suite"],
                "version": dataset["version"],
                "valid": True,
                "problems": [],
                "total": len(dataset["cases"]),
            }
        )
        return 0

    workdir = Path(args.workdir) if args.workdir else None
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="qianke_write_action_eval_") as tmp:
            summary = run_suite(Path(tmp), dataset)
    else:
        summary = run_suite(workdir, dataset)

    _emit(summary)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
