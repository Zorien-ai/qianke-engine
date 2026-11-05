# -*- coding: utf-8 -*-
"""B 端人设 Eval 数据集契约测试。

只校验 `tests/evals/agent/persona/dataset.v1.json` 的结构、计数与场景覆盖，
**不加载模型、不调用任何链路**，因此可以在任意环境稳定运行。
"""
import json
from pathlib import Path

PERSONA_EVAL_DIR = Path(__file__).parent / "evals" / "agent" / "persona"
DATASET_PATH = PERSONA_EVAL_DIR / "dataset.v1.json"
README_PATH = PERSONA_EVAL_DIR / "README.md"

REQUIRED_CASE_FIELDS = ("id", "category", "mode", "turns", "expect", "acceptance", "forbidden")
VALID_MODES = {"agent", "chat"}

# 22 条单轮必须覆盖的场景（与文档 §12.4 一一对应）
REQUIRED_SINGLE_TURN_CATEGORIES = {
    "首轮",
    "模糊需求",
    "统计",
    "定义",
    "分布",
    "两群对比",
    "空结果",
    "字段未入库",
    "口径错配",
    "预测",
    "归因",
    "坏消息",
    "质疑数据",
    "越权",
    "催促",
    "小样本",
    "敏感字段",
    "工具失败",
    "权限不足（cs）",
    "周报复盘",
    "数据新鲜度",
    "406 vs 403 口径解释",
}

# 3 条多轮必须覆盖的行为维度
REQUIRED_MULTI_TURN_KEYWORDS = ("口径", "客服腔", "质疑")

# 禁称 / 承诺 / emoji 维度（与文档 §6.5、§12.3 禁词表对齐）
BANNED_ADDRESS = ("老板", "亲", "宝子", "家人们", "亲爱的", "帅哥美女", "您嘞")
PROMISE_WORDS = ("保证", "一定能", "已发送", "已执行", "包在我身上")
EMOJI_CHARS = "😊🎉✨😄🙂👍❤"

REQUIRED_COVERAGE_DIMENSIONS = (
    "老板",
    "亲",
    "emoji",
    "感叹号",
    "承诺词",
    "超长",
    "权限不足",
    "新鲜度",
    "406-403",
)


def _load():
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def _cases():
    return _load()["cases"]


def _single_turn_cases():
    return [case for case in _cases() if len(case["turns"]) == 1]


def _multi_turn_cases():
    return [case for case in _cases() if len(case["turns"]) > 1]


def _forbidden_text(case):
    return "".join(case["forbidden"])


def test_dataset_file_parses_and_has_metadata():
    assert DATASET_PATH.is_file(), f"缺少数据集文件：{DATASET_PATH}"
    payload = _load()
    assert payload["version"] == "b-persona-eval-v1"
    assert payload["dataset"] == "demo"
    assert payload["related_doc"] == "docs/product/b-end-agent-persona.md"
    # 真实模型基线未运行：数据集自身必须如实标注
    assert payload["status"] == "draft"
    assert payload["baseline"] == "not_run"
    assert isinstance(payload["cases"], list)


def test_case_count_and_unique_ids():
    cases = _cases()
    assert len(cases) == 25
    ids = [case["id"] for case in cases]
    assert len(set(ids)) == len(ids), f"id 重复：{len(ids) - len(set(ids))} 个"
    for case in cases:
        assert case["id"].startswith(("persona_single_", "persona_multi_")), case["id"]


def test_case_fields_and_types():
    for case in _cases():
        for field in REQUIRED_CASE_FIELDS:
            assert field in case, f"{case.get('id')} 缺字段：{field}"
        assert isinstance(case["id"], str) and case["id"]
        assert isinstance(case["category"], str) and case["category"]
        assert isinstance(case["mode"], str) and case["mode"]
        assert isinstance(case["turns"], list) and case["turns"], f"{case['id']} turns 为空"
        assert all(isinstance(turn, str) and turn.strip() for turn in case["turns"]), case["id"]
        assert isinstance(case["expect"], str) and case["expect"].strip(), case["id"]
        assert isinstance(case["acceptance"], list) and case["acceptance"], case["id"]
        assert all(isinstance(item, str) and item.strip() for item in case["acceptance"]), case["id"]
        assert isinstance(case["forbidden"], list) and case["forbidden"], case["id"]
        assert all(isinstance(item, str) and item for item in case["forbidden"]), case["id"]


def test_modes_are_valid_and_both_used():
    modes = {case["mode"] for case in _cases()}
    assert modes <= VALID_MODES, f"非法 mode：{modes - VALID_MODES}"
    assert modes == VALID_MODES, "agent / chat 两条链路都必须有用例"


def test_single_and_multi_turn_counts():
    single = _single_turn_cases()
    multi = _multi_turn_cases()
    assert len(single) == 22, f"单轮应为 22 条，实际 {len(single)}"
    assert len(multi) == 3, f"多轮应为 3 条，实际 {len(multi)}"
    assert sum(len(case["turns"]) for case in multi) >= 9, "多轮用例应覆盖足够轮次（≥3 轮/条）"


def test_single_turn_categories_cover_required_scenarios():
    categories = [case["category"] for case in _single_turn_cases()]
    assert len(categories) == len(set(categories)), "单轮场景不应重复"
    assert set(categories) == REQUIRED_SINGLE_TURN_CATEGORIES, (
        f"缺失：{REQUIRED_SINGLE_TURN_CATEGORIES - set(categories)}；"
        f"多余：{set(categories) - REQUIRED_SINGLE_TURN_CATEGORIES}"
    )


def test_multi_turn_categories_cover_required_behaviors():
    categories = [case["category"] for case in _multi_turn_cases()]
    assert len(categories) == len(set(categories))
    for keyword in REQUIRED_MULTI_TURN_KEYWORDS:
        assert any(keyword in category for category in categories), f"多轮缺少「{keyword}」维度"


def test_every_case_forbids_at_least_one_banned_address_or_qin():
    for case in _cases():
        text = _forbidden_text(case)
        assert any(address in text for address in ("老板", "亲")), (
            f"{case['id']} 的 forbidden 至少应包含「老板」或「亲」"
        )
    all_text = "".join(_forbidden_text(case) for case in _cases())
    for address in BANNED_ADDRESS:
        assert address in all_text, f"数据集整体未覆盖禁称：{address}"


def test_coverage_dimensions_reference_existing_cases():
    payload = _load()
    coverage = payload.get("coverage")
    assert isinstance(coverage, dict)
    assert set(coverage) == set(REQUIRED_COVERAGE_DIMENSIONS), (
        f"缺失维度：{set(REQUIRED_COVERAGE_DIMENSIONS) - set(coverage)}；"
        f"多余维度：{set(coverage) - set(REQUIRED_COVERAGE_DIMENSIONS)}"
    )
    all_ids = {case["id"] for case in _cases()}
    for dimension, ids in coverage.items():
        assert isinstance(ids, list) and ids, f"coverage.{dimension} 为空"
        assert len(ids) == len(set(ids)), f"coverage.{dimension} 有重复 id"
        unknown = set(ids) - all_ids
        assert not unknown, f"coverage.{dimension} 引用了不存在的用例：{unknown}"


def test_coverage_content_matches_case_assertions():
    payload = _load()
    coverage = payload["coverage"]
    by_id = {case["id"]: case for case in _cases()}

    def covered(dimension):
        return [by_id[case_id] for case_id in coverage[dimension]]

    for case in covered("老板"):
        assert "老板" in case["forbidden"], case["id"]
    for case in covered("亲"):
        assert "亲" in case["forbidden"], case["id"]
    for case in covered("emoji"):
        assert any(char in _forbidden_text(case) for char in EMOJI_CHARS), case["id"]
    for case in covered("感叹号"):
        assert any(mark in _forbidden_text(case) for mark in ("！", "!")), case["id"]
    for case in covered("承诺词"):
        assert any(word in _forbidden_text(case) for word in PROMISE_WORDS), case["id"]
    for case in covered("超长"):
        assert any(("字" in item and "≤" in item) for item in case["acceptance"]), case["id"]
    for case in covered("权限不足"):
        assert "权限" in case["category"], case["id"]
    for case in covered("新鲜度"):
        assert "新鲜度" in case["category"], case["id"]
    for case in covered("406-403"):
        joined = " ".join(case["acceptance"])
        assert "403" in joined and "406" in joined and "14555" in joined, case["id"]


def test_readme_exists_and_marks_baseline_not_run():
    assert README_PATH.is_file(), f"缺少 README：{README_PATH}"
    text = README_PATH.read_text(encoding="utf-8")
    assert "基线尚未运行" in text
    assert "pytest tests/test_b_persona_eval_contract.py" in text
