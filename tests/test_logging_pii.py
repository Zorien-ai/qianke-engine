"""日志 PII 脱敏测试。"""
from __future__ import annotations

import logging

from rag_demo.logging_setup import PiiRedactionFilter, redact_pii


def test_redact_phone_email_id_card():
    text = redact_pii("手机 13800138000，邮箱 alice@example.com，身份证 110101199001011234")
    assert "13800138000" not in text
    assert "alice@example.com" not in text
    assert "110101199001011234" not in text
    assert "138****8000" in text
    assert "a***@example.com" in text


def test_redact_leaves_normal_text():
    assert redact_pii("订单 order_123 金额 89.00") == "订单 order_123 金额 89.00"


def test_filter_redacts_formatted_record():
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="联系 %s / %s", args=("13800138000", "bob@test.com"), exc_info=None,
    )
    assert PiiRedactionFilter().filter(record) is True
    message = record.getMessage()
    assert "13800138000" not in message
    assert "bob@test.com" not in message
    assert "138****8000" in message
    assert "b***@test.com" in message
