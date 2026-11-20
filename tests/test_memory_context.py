# -*- coding: utf-8 -*-
"""记忆上下文 Phase 1：身份解析、过滤、元数据与冲突标记。"""
from __future__ import annotations

from rag_demo import memory_context as mc


def _item(
    memory_id: str,
    *,
    content: str = "喜欢跑步",
    kind: str = "preference",
    source: str = "extracted",
    tenant: str = "c_end",
    customer: str = "buyer_1",
    status: str = "ACTIVE",
    confidence: float | None = None,
    updated_at: str = "2026-11-20T10:00:00",
    conflict_key: str = "",
) -> mc.MemoryItem:
    return mc.MemoryItem(
        memory_id=memory_id,
        tenant_id=tenant,
        customer_id=customer,
        kind=kind,
        content=content,
        source=source,
        status=status,
        updated_at=updated_at,
        confidence=confidence,
        conflict_key=conflict_key,
    )


def test_authenticated_identity_is_resolved():
    identity = mc.resolve_authenticated_identity("c_end", "buyer_1")
    assert identity.resolved is True
    assert identity.customer_id == "buyer_1"
    assert identity.confidence == 1.0
    assert identity.evidence == ("authenticated_session",)


def test_missing_authenticated_customer_requires_clarification():
    identity = mc.resolve_authenticated_identity("c_end", "")
    assert identity.resolved is False
    assert identity.reason == "CUSTOMER_MISSING"
    assert "还没有确认客户身份" in mc.clarification_message(identity)


def test_identity_resolves_exact_id_and_alias():
    candidates = [
        {"customer_id": "buyer_1", "aliases": ["老王", "buyer_1"]},
        {"customer_id": "buyer_2", "aliases": ["小李", "buyer_2"]},
    ]
    by_id = mc.resolve_identity_from_candidates("m_1", "buyer_2", candidates)
    assert by_id.resolved is True
    assert by_id.customer_id == "buyer_2"

    by_alias = mc.resolve_identity_from_candidates("m_1", "老王", candidates)
    assert by_alias.resolved is True
    assert by_alias.customer_id == "buyer_1"


def test_ambiguous_identity_is_not_resolved():
    candidates = [
        {"customer_id": "buyer_1", "aliases": ["老王"]},
        {"customer_id": "buyer_2", "aliases": ["老王"]},
    ]
    identity = mc.resolve_identity_from_candidates("m_1", "老王", candidates)
    assert identity.resolved is False
    assert identity.ambiguous is True
    assert identity.reason == "MULTIPLE_MATCHES"
    assert "无法唯一确认" in mc.clarification_message(identity)


def test_unknown_identity_returns_no_context():
    identity = mc.resolve_identity_from_candidates("m_1", "不存在", [])
    packet = mc.assemble_context([_item("mem_1")], identity)
    assert packet.items == ()
    assert packet.needs_clarification is True


def test_assemble_filters_tenant_customer_status_and_duplicates():
    identity = mc.resolve_authenticated_identity("c_end", "buyer_1")
    items = [
        _item("mem_keep", confidence=0.8),
        _item("mem_other_tenant", tenant="other", confidence=1.0),
        _item("mem_other_customer", customer="buyer_2", confidence=1.0),
        _item("mem_deleted", status="DELETED", confidence=1.0),
        _item("mem_dup", content="喜欢游泳", confidence=0.5),
        _item("mem_duplicate", content="喜欢跑步", confidence=0.9),
    ]
    packet = mc.assemble_context(items, identity)
    assert [item.memory_id for item in packet.items] == ["mem_keep", "mem_dup"]
    assert "tenant:mem_other_tenant" in packet.dropped
    assert "customer:mem_other_customer" in packet.dropped
    assert "status:mem_deleted" in packet.dropped
    assert "duplicate:mem_duplicate" in packet.dropped


def test_assemble_keeps_source_updated_at_and_confidence():
    identity = mc.resolve_authenticated_identity("c_end", "buyer_1")
    packet = mc.assemble_context(
        [_item("mem_1", source="user_explicit", updated_at="2026-11-20T10:00:00", confidence=0.87)],
        identity,
    )
    assert packet.items[0].source == "user_explicit"
    assert packet.items[0].updated_at == "2026-11-20T10:00:00"
    assert packet.items[0].confidence == 0.87
    text = mc.format_items(packet, header="你记得的事")
    assert "来源=user_explicit" in text
    assert "更新=2026-11-20T10:00:00" in text
    assert "置信度=0.87" in text


def test_assemble_marks_conflicts_without_dropping():
    identity = mc.resolve_authenticated_identity("c_end", "buyer_1")
    packet = mc.assemble_context(
        [
            _item("mem_1", content="预算 500 元", conflict_key="budget"),
            _item("mem_2", content="预算 800 元", conflict_key="budget"),
        ],
        identity,
    )
    assert len(packet.items) == 2
    assert packet.conflicts == ("conflict:budget",)
    text = mc.format_items(packet)
    assert "存在冲突标记" in text


def test_assemble_limits_items_and_chars():
    identity = mc.resolve_authenticated_identity("c_end", "buyer_1")
    items = [_item(f"mem_{i}", content=f"{i}" + "x" * 19) for i in range(5)]
    packet = mc.assemble_context(items, identity, max_items=3)
    assert len(packet.items) == 3
    assert any(item.startswith("budget_items:") for item in packet.dropped)

    packet = mc.assemble_context(items, identity, max_items=10, max_chars=25)
    assert len(packet.items) == 1
    assert any(item.startswith("budget_chars:") for item in packet.dropped)


def test_memory_item_from_record_marks_unknown_metadata():
    item = mc.memory_item_from_record(
        tenant_id="c_end",
        customer_id="buyer_1",
        record={"memory_id": "mem_1", "kind": "preference", "content": "喜欢跑步", "source": "extracted"},
    )
    assert item.confidence is None
    assert item.updated_at is None
    assert mc.format_confidence(item.confidence) == "未校准"
