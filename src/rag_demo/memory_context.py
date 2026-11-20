# -*- coding: utf-8 -*-
"""Agent 记忆上下文：身份解析 + 上下文组装（Phase 1）。

设计目标：
- 记忆读取前先确认客户身份；身份不唯一时返回澄清，不读取记忆。
- 组装时强制 tenant / customer / status 边界。
- 每个上下文片段保留 source / updated_at / confidence，便于 Prompt 和 Trace 解释。
- 纯逻辑，不依赖数据库、LLM 或请求上下文，便于单测和复用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

ACTIVE_STATUS = "ACTIVE"
UNKNOWN_CONFIDENCE = "未校准"


@dataclass(frozen=True)
class IdentityResolution:
    """身份解析结果；resolved=False 时调用方只能补问，不能读取记忆。"""

    tenant_id: str
    customer_id: str | None
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    ambiguous: bool = False
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return bool(self.customer_id) and not self.ambiguous and self.confidence >= 0.5

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "customer_id": self.customer_id,
            "confidence": round(float(self.confidence), 4),
            "evidence": list(self.evidence),
            "ambiguous": self.ambiguous,
            "resolved": self.resolved,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MemoryItem:
    """一条可进入上下文的记忆；content 已经是脱敏后的文本。"""

    memory_id: str
    tenant_id: str
    customer_id: str
    kind: str
    content: str
    source: str
    status: str = ACTIVE_STATUS
    created_at: str | None = None
    updated_at: str | None = None
    confidence: float | None = None
    confidence_basis: str = "unknown"
    conflict_key: str = ""


@dataclass(frozen=True)
class ContextPacket:
    identity: IdentityResolution
    items: tuple[MemoryItem, ...] = ()
    dropped: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    clarification: str = ""

    @property
    def needs_clarification(self) -> bool:
        return bool(self.clarification)


def resolve_authenticated_identity(
    tenant_id: str,
    customer_id: str | None,
    *,
    evidence: Sequence[str] = ("authenticated_session",),
    confidence: float = 1.0,
) -> IdentityResolution:
    """已认证会话的身份解析：customer_id 来自服务端会话，不接受客户端自报。"""
    tenant = " ".join(str(tenant_id or "").split())
    customer = " ".join(str(customer_id or "").split())
    if not tenant:
        return IdentityResolution("", None, 0.0, tuple(evidence), False, "TENANT_MISSING")
    if not customer:
        return IdentityResolution(tenant, None, 0.0, tuple(evidence), False, "CUSTOMER_MISSING")
    return IdentityResolution(
        tenant_id=tenant,
        customer_id=customer,
        confidence=max(0.0, min(1.0, float(confidence))),
        evidence=tuple(evidence),
        ambiguous=False,
        reason="",
    )


def resolve_identity_from_candidates(
    tenant_id: str,
    claimed: str | None,
    candidates: Iterable[dict[str, Any]],
) -> IdentityResolution:
    """按客户 ID / 别名解析身份；多命中必须判定 ambiguous，不能猜。

    candidate 结构示例：
        {"customer_id": "buyer_1", "aliases": ["老王", "buyer_1"]}
    """
    tenant = " ".join(str(tenant_id or "").split())
    claim = " ".join(str(claimed or "").split()).casefold()
    if not tenant:
        return IdentityResolution("", None, 0.0, (), False, "TENANT_MISSING")
    if not claim:
        return IdentityResolution(tenant, None, 0.0, (), False, "CLAIM_MISSING")

    matched: list[tuple[str, str]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        customer_id = " ".join(str(candidate.get("customer_id") or "").split())
        if not customer_id:
            continue
        aliases = [str(item or "").strip() for item in candidate.get("aliases") or []]
        names = [str(candidate.get("name") or "").strip()]
        values = [customer_id, *aliases, *names]
        for value in values:
            if value and value.casefold() == claim:
                matched.append((customer_id, value))
                break

    unique: dict[str, str] = {}
    for customer_id, value in matched:
        unique.setdefault(customer_id, value)
    if len(unique) == 1:
        customer_id, value = next(iter(unique.items()))
        return IdentityResolution(
            tenant_id=tenant,
            customer_id=customer_id,
            confidence=1.0,
            evidence=(f"matched:{value}",),
            ambiguous=False,
            reason="",
        )
    if len(unique) > 1:
        return IdentityResolution(
            tenant_id=tenant,
            customer_id=None,
            confidence=0.0,
            evidence=tuple(f"candidate:{item}" for item in sorted(unique)),
            ambiguous=True,
            reason="MULTIPLE_MATCHES",
        )
    return IdentityResolution(tenant, None, 0.0, (), False, "NO_MATCH")


def clarification_message(identity: IdentityResolution) -> str:
    """身份未唯一确认时的统一补问文案；不暴露候选客户。"""
    if identity.ambiguous:
        return "当前身份无法唯一确认。请先确认是哪位客户，再读取或写入其记忆。"
    if identity.reason in {"CUSTOMER_MISSING", "CLAIM_MISSING"}:
        return "还没有确认客户身份。请先补充客户信息，再读取或写入记忆。"
    if identity.reason == "NO_MATCH":
        return "没有找到可靠的客户记录。请先确认客户信息，再读取或写入记忆。"
    return "客户身份校验未通过。请先确认身份。"


def assemble_context(
    items: Iterable[MemoryItem],
    identity: IdentityResolution,
    *,
    max_items: int = 8,
    max_chars: int = 1600,
) -> ContextPacket:
    """按身份/租户/状态过滤并组装上下文；失败时返回澄清而不是猜测。"""
    if not identity.resolved:
        return ContextPacket(identity=identity, clarification=clarification_message(identity))

    dropped: list[str] = []
    deduped: dict[tuple[str, str], MemoryItem] = {}
    for item in items:
        if not isinstance(item, MemoryItem):
            continue
        content = " ".join(str(item.content or "").split())
        if not content:
            dropped.append(f"empty:{item.memory_id}")
            continue
        if item.tenant_id != identity.tenant_id:
            dropped.append(f"tenant:{item.memory_id}")
            continue
        if item.customer_id != identity.customer_id:
            dropped.append(f"customer:{item.memory_id}")
            continue
        if str(item.status or "").upper() != ACTIVE_STATUS:
            dropped.append(f"status:{item.memory_id}")
            continue
        key = (item.kind, content)
        if key in deduped:
            dropped.append(f"duplicate:{item.memory_id}")
            continue
        deduped[key] = item

    def sort_key(item: MemoryItem) -> tuple[float, str]:
        confidence = item.confidence if isinstance(item.confidence, (int, float)) else -1.0
        return (float(confidence), str(item.updated_at or item.created_at or ""))

    selected: list[MemoryItem] = []
    used_chars = 0
    for item in sorted(deduped.values(), key=sort_key, reverse=True):
        if len(selected) >= max(0, max_items):
            dropped.append(f"budget_items:{item.memory_id}")
            continue
        if used_chars + len(item.content) > max(0, max_chars):
            dropped.append(f"budget_chars:{item.memory_id}")
            continue
        selected.append(item)
        used_chars += len(item.content)

    conflicts = _find_conflicts(selected)
    return ContextPacket(
        identity=identity,
        items=tuple(selected),
        dropped=tuple(dropped),
        conflicts=tuple(conflicts),
        clarification="",
    )


def _find_conflicts(items: Sequence[MemoryItem]) -> list[str]:
    """同一 conflict_key 出现不同内容时标记冲突；不自动覆盖，交给用户/策略。"""
    groups: dict[str, set[str]] = {}
    for item in items:
        key = " ".join(str(item.conflict_key or "").split())
        if not key:
            continue
        groups.setdefault(key, set()).add(" ".join(str(item.content or "").split()))
    return [
        f"conflict:{key}"
        for key, contents in sorted(groups.items())
        if len(contents) > 1
    ]


def format_confidence(confidence: float | None) -> str:
    if not isinstance(confidence, (int, float)):
        return UNKNOWN_CONFIDENCE
    return f"{max(0.0, min(1.0, float(confidence))):.2f}"


def format_items(packet: ContextPacket, *, header: str = "记忆上下文") -> str:
    """把 ContextPacket 格式化为带来源/时效/置信度的 System Prompt 段落。"""
    if not packet.items:
        return ""
    lines = [f"【{header}】"]
    if packet.conflicts:
        lines.append("注意：以下记忆存在冲突标记，不要静默覆盖；以当前对话为准并在必要时确认。")
    for item in packet.items:
        updated = str(item.updated_at or item.created_at or "未知")[:19]
        meta = f"来源={item.source or '未知'}；更新={updated}；置信度={format_confidence(item.confidence)}"
        lines.append(f"- [{item.kind}] {item.content}（{meta}）")
    return "\n".join(lines)


def memory_item_from_record(
    *,
    tenant_id: str,
    customer_id: str,
    record: dict[str, Any],
    default_source: str = "unknown",
    default_kind: str = "memory",
    conflict_key: str = "",
) -> MemoryItem:
    """把现有 store 返回值转成 MemoryItem；缺失字段显式标为未知。"""
    return MemoryItem(
        memory_id=str(record.get("memory_id") or record.get("id") or ""),
        tenant_id=tenant_id,
        customer_id=customer_id,
        kind=str(record.get("kind") or default_kind),
        content=str(record.get("content") or ""),
        source=str(record.get("source") or default_source),
        status=str(record.get("status") or ACTIVE_STATUS),
        created_at=str(record.get("created_at") or "") or None,
        updated_at=str(record.get("updated_at") or "") or None,
        confidence=record.get("confidence") if isinstance(record.get("confidence"), (int, float)) else None,
        confidence_basis=str(record.get("confidence_basis") or "unknown"),
        conflict_key=str(record.get("conflict_key") or conflict_key),
    )
