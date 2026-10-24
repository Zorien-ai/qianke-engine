#!/usr/bin/env python
"""Agent Eval 入口：20 条 case = calculator 5 + rag_search 5 + execute_sql 5 + collaboration 5。

    uv run python scripts/run_agent_eval.py --validate-only
    uv run python scripts/run_agent_eval.py --only CALC-01 --limit 1
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rag_demo.agent.eval.runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
