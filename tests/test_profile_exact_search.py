from rag_demo.b_end import insights


def test_extract_requested_buyer_ids():
    assert insights._requested_buyer_ids("buyer_217 你怎么看") == ["buyer_217"]
    assert insights._requested_buyer_ids("buyer_217你怎么看") == ["buyer_217"]
    assert insights._requested_buyer_ids("buyer_217 和 buyer_193 谁更值得跟进") == ["buyer_217", "buyer_193"]
    assert insights._requested_buyer_ids("哪些客户买过绿茶") == []


def test_exact_buyer_id_short_circuits_semantic_search(monkeypatch):
    row = {"buyer_id": "buyer_217", "order_count": 0, "has_order": False, "has_chat": True}
    monkeypatch.setattr(insights.store, "get_qianke_user_profile", lambda merchant_id, buyer_id: row if buyer_id == "buyer_217" else None)
    monkeypatch.setattr(insights.store, "search_qianke_user_profiles", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not semantic-search")))
    assert insights._search_qianke_rows("m_sim_tea", "buyer_217 你怎么看", limit=10) == [row]
