#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : chitchat.py
@Function: 拒答兜底文案——能力清单固定，业务示例从当前数据集生成

为什么要有这个模块
------------------
改造前这段文案是 `prompts.CHITCHAT_REPLY` 一个常量，写死了

    「标签口径：高客单 / 流失预警 / 高价值」
    「运营与客服：召回策略、退换货流程、优惠券处理」

那是 dianshuang 的业务域。而 M2 的用户会上传机械设备、餐饮、教育的数据——
他问错一句话，收到的引导里全是他业务里不存在的东西。
而且这是他**第一次**看到这段文案（它只在拒答时出现），正好落在他最需要
一句准确引导的时刻。

分层原则（与 SQL_SCHEMA 动态化同一条道理）
------------------------------------------
    能力清单  —— 系统真实支持的链路，**代码决定，用户改不了**。
                 让用户写「支持预测」而系统答不了，比不给引导更伤。
    业务示例  —— 必须来自他自己的数据；采不到就不举例，不回退成 demo 的例句。
    助手名称  —— 用户可配（存数据集级 UI 配置，见 db/schema.read_ui_config）。

数据来源
--------
`schema_facts.get_tables()`：与提示词里的表结构共用同一份缓存，
所以这里不会额外增加一次全表扫描。
"""
import logging

from rag_demo.db.schema import read_ui_config
from rag_demo.db.schema_facts import get_tables
from rag_demo.prompts import CHITCHAT_REPLY_TEMPLATE

logger = logging.getLogger(__name__)

DEFAULT_ASSISTANT_NAME = "用户画像分析助手"

# 能力清单：系统真实支持的四类链路。
#
# 描述刻意保持**业务中性**：改前的「高客单 / 召回策略 / 优惠券」是电商词，
# 换成机械设备的数据就会误导。具体的业务感交给示例句——
# 能可靠推断的那两类才举例（见 _examples），推不出来的宁可空着。
CAPABILITIES: tuple[tuple[str, str], ...] = (
    ("画像查询", "某个用户是谁、某类用户有什么特征"),
    ("标签口径", "某个标签、某个指标是怎么定义的"),
    ("聚合统计", "有多少人、分布如何、占比多少"),
    ("运营与客服", "流程规范、策略方案、常见问题怎么处理"),
)


def _safe_config() -> dict[str, str]:
    """读 UI 配置；数据库不可用时当没配（用默认名），不影响拒答这件事本身"""
    try:
        return read_ui_config()
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 UI 配置失败，使用默认值: %s", e)
        return {}


def _safe_tables():
    """取表事实；失败返回空列表——宁可少举例，也不退回写死的示例"""
    try:
        return get_tables()
    except Exception as e:  # noqa: BLE001
        logger.warning("读取表事实失败，示例句将省略: %s", e)
        return []


def _examples(tables) -> list[str | None]:
    """
    逐类生成一条示例问句；生成不了就是 None（那一类只显示能力描述）

    顺序必须与 CAPABILITIES 一一对应。

    为什么只给「画像查询」和「聚合统计」举例：
        这两类能**可靠地从结构推断**——用户ID样例是现成的、枚举列名就是维度名。
        知识库那两类推不出来：`doc_name` 只告诉你文档叫什么，
        推不出这篇讲的是标签定义还是售后流程。
        拿「《member_benefits》里是怎么定义的」去配「标签口径」，
        等于示例在撒谎——正是这份文案要修的那种错。
        宁可那一类不举例。
    """
    profile = next((t for t in tables if t.name == "user_profile_vectors"), None)
    examples: list[str | None] = []

    # 画像查询：拿一个真实的用户ID当前缀，一眼看出该问什么
    ex = None
    if profile is not None and profile.rows:
        uid = next((c for c in profile.columns if c.name == "user_id"), None)
        if uid and uid.samples:
            ex = f"查一下 {uid.samples[0]} 是谁"
    examples.append(ex)

    # 标签口径：推不出主题，不举例（见函数开头说明）
    examples.append(None)

    # 聚合统计：用当前库里真实存在的枚举列（如「会员等级」「城市」）。
    # 只取取值数 >= 3 的：性别这种二值列当示例没有信息量。
    ex = None
    if profile is not None and profile.rows:
        col = next(
            (
                c for c in profile.columns
                if c.kind == "enum" and len(c.values) >= 3 and c.name != "user_id"
            ),
            None,
        )
        if col:
            ex = f"各{col.doc}的分布"
    examples.append(ex)

    # 运营与客服：同上，推不出主题就不举例
    examples.append(None)

    return examples


def build_reply() -> str:
    """
    生成当前数据集下的拒答兜底文案

    调用时机：入口路由判 chitchat、或多路规划复核改道 chitchat（都是低频路径，
    一次采集的缓存成本可以接受）。
    """
    cfg = _safe_config()
    name = (cfg.get("assistant_name") or "").strip() or DEFAULT_ASSISTANT_NAME

    examples = _examples(_safe_tables())
    lines = []
    for (title, desc), ex in zip(CAPABILITIES, examples):
        line = f"- **{title}**：{desc}"
        if ex:
            line += f"（例：「{ex}」）"
        lines.append(line)

    sample = (cfg.get("sample_question") or "").strip() or next(
        (e for e in examples if e), ""
    )
    hint = (
        f"换个相关的问题试试？比如「{sample}」" if sample else "换个相关的问题试试？"
    )

    return CHITCHAT_REPLY_TEMPLATE.format(
        assistant_name=name,
        capabilities="\n".join(lines),
        sample_hint=hint,
    )
