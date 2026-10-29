"""Agent Tool 权限策略。

建立“暴露前过滤 + 执行时复核”的机制：
- 只把当前身份允许的 Tool 绑定给 LLM / ToolNode；
- LLM 若仍产出未授权 Tool 调用，chatbot 节点在执行前拒绝。

B 端默认矩阵（未完成正式权限评审前的最小安全默认）：
    admin / ent_admin / exec / analyst / ops -> rag_search + execute_sql + calculator
    cs                                         -> rag_search + calculator
    guest                                      -> 无
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

B_AGENT_TOOL_NAMES: tuple[str, ...] = (
    "rag_search",
    "execute_sql",
    "calculator",
    "prepare_followup_task",
)

_ANALYTICS_ROLES = frozenset({"admin", "ent_admin", "exec", "analyst", "ops"})
_CS_ROLE = "cs"
_GUEST_ROLE = "guest"


def _account_role(account: dict[str, Any] | None) -> str:
    if account is None:
        return "offline"
    if account.get("is_system_admin"):
        return "admin"
    if account.get("is_enterprise_admin"):
        return "ent_admin"
    return str(account.get("role") or _GUEST_ROLE)


@dataclass(frozen=True)
class ToolPolicy:
    allowed: frozenset[str]

    def __init__(self, allowed: Iterable[str] | None = None) -> None:
        object.__setattr__(
            self,
            "allowed",
            frozenset(allowed if allowed is not None else B_AGENT_TOOL_NAMES),
        )

    def authorize(self, tool_name: str, account: dict[str, Any] | None = None) -> bool:
        if tool_name not in self.allowed:
            return False
        if account is None:
            return True
        if account.get("is_demo"):
            return False
        return account.get("status") != "disabled"

    def allowed_tools(self, account: dict[str, Any] | None = None) -> tuple[str, ...]:
        if account is not None:
            if account.get("is_demo") or account.get("status") == "disabled":
                return ()
        return tuple(name for name in B_AGENT_TOOL_NAMES if name in self.allowed)

    @classmethod
    def for_account(cls, account: dict[str, Any] | None = None) -> "ToolPolicy":
        if account is None:
            return cls()
        role = _account_role(account)
        if role in _ANALYTICS_ROLES:
            return cls(B_AGENT_TOOL_NAMES)
        if role == _CS_ROLE:
            return cls(("rag_search", "calculator"))
        return cls(())
