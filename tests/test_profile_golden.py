"""画像黄金集文件结构与运行器纯函数测试。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "evals" / "b_profile" / "golden.json"
RUNNER = ROOT / "scripts" / "run_profile_golden.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_profile_golden", RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_profile_golden_cases_are_valid():
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = data["cases"]
    assert len(cases) >= 10
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    assert {case["source"] for case in cases} <= {"qianke", "imported", "all"}
    for case in cases:
        assert case["question"].strip()
        assert isinstance(case["expect"], dict)


def test_sources_any_semantics():
    runner = _load_runner()
    sources = [{"source": "m_sim_tea_sop.md"}, {"source": "qianke_user"}]
    ok, missing = runner._sources_ok(sources, ["merchant_rules.md", "m_sim_tea_sop.md"])
    assert ok is True and missing == []
    ok, missing = runner._sources_ok(sources, ["merchant_rules.md"])
    assert ok is False and missing == ["merchant_rules.md"]


def test_cards_any_and_answer_groups():
    runner = _load_runner()
    cards = [{"user_id": "buyer_217"}, {"user_id": "qk_u001"}]
    assert runner._cards_ok(cards, ["buyer_217"])[0] is True
    assert runner._cards_ok(cards, ["buyer_999"])[0] is False
    assert runner._cards_ok(cards, ["buyer_"])[0] is True
    assert runner._answer_ok("buyer_217 是冷启动新客", [["buyer_217"], ["冷启动"]])[0] is True
    assert runner._answer_ok("无法判断", [["冷启动"]])[0] is False
