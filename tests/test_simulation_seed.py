"""模拟种子脚本的静态/计划测试；不写数据库。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "seed_simulation.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("seed_simulation", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_simulation_plan_is_complete_and_unique():
    module = _load_module()
    plan = module.seed(merchants=6, consumers=30, apply=False)

    assert plan["dry_run"] is True
    assert len(plan["merchants"]) == 6
    assert len(plan["consumers"]) == 30
    assert plan["products"] == 18
    assert len(set(plan["consumers"])) == 30
    assert all(phone.isdigit() and len(phone) == 11 for phone in plan["consumers"])

    merchant_ids = [merchant.merchant_id for merchant in module.MERCHANTS]
    product_ids = [f"SIM-{product.suffix}" for merchant in module.MERCHANTS for product in merchant.products]
    assert len(set(merchant_ids)) == len(merchant_ids)
    assert len(set(product_ids)) == len(product_ids)


def test_simulation_plan_is_deterministic():
    module = _load_module()
    first = module.seed(merchants=6, consumers=30, apply=False)
    second = module.seed(merchants=6, consumers=30, apply=False)
    assert first == second
