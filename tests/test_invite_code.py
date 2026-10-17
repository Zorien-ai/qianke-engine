# -*- coding: utf-8 -*-
"""邀请码生成规则单测（M3 企业后台：邀请码重置）

邀请码是员工注册的唯一入口：企业管理员重置后旧码必须立刻失效（DB 查），
新码又要满足登录页的 `^[A-Za-z0-9]{6,16}$` 校验、且不能被看错抄错。
"""
import re

from rag_demo.auth import _new_invite_code

# auth._new_invite_code 里去掉的易混字符：0/O、1/I
_ALPHABET = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def test_invite_code_format_matches_login_validation():
    code = _new_invite_code()
    assert len(code) == 8
    # 登录页注册校验：6~16 位字母或数字
    assert re.fullmatch(r"[A-Za-z0-9]{6,16}", code)


def test_invite_code_avoids_confusable_chars():
    """企业管理员多半是手抄/口述给同事的，0/O、1/I 必须不出现"""
    for _ in range(50):
        code = _new_invite_code()
        assert set(code) <= _ALPHABET, code
        assert not (set(code) & set("01OI")), code


def test_invite_code_is_random_enough():
    """8 位 32 字符表空间足够大；连出重复说明随机源出了问题"""
    codes = {_new_invite_code() for _ in range(300)}
    assert len(codes) >= 295
