#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : mock_data.py
@Function: 向导用的静态定义（字段识别字典 / 构建步骤 / 示例问题）

M1 时这个文件装的是「假数据」，好让流程先跑起来；到 M2 四步全部接真之后，
这里只剩下**本身就该是静态的东西**：

    FIELD_DEFS     系统字段与同义词表 —— 是配置，不是数据（入库口径与它同一套）
    BUILD_STEPS    构建五步的名称与权重 —— 进度条的骨架，数量由真实事件填
    EXAMPLE_*      示例问句 —— 纯文案

被删掉的（不是搬走，是真的不再需要）：
    ANSWER_BANK / FALLBACK_ANSWER  假答案。第 4 步起答案来自真实 pipeline，
                                   留着它就有「两处真源」，早晚有人改错一处
    SAMPLE_CSV_FILES / SAMPLE_MD_FILES  假的示例文件清单。「用示例数据填满」现在是
                                   把仓库自带的**真实数据**复制进上传目录，
                                   走与真人上传完全相同的落盘/解析路径

字段识别沿用 MVP 文档的口径：**同义词字典匹配，不做 LLM 智能识别**
（见 docs/MVP产品目标.md 5.2）。
"""

# ================= 字段定义与同义词字典 =================
# canonical: 系统内部字段名（与 tools/sql_tool.py、prompts.py 的列名口径一致）
# synonyms: 允许的列名写法。匹配时统一做「去空格 / 去下划线 / 转小写」归一，
#           因此 "user_id" / "User ID" / "用户ID" 会命中同一条。
FIELD_DEFS: list[dict] = [
    {
        "key": "user_id",
        "label": "用户ID",
        "required": True,
        "hint": "每行用户/订单的唯一标识，几乎所有查询都依赖它",
        "synonyms": [
            "user_id", "userid", "uid", "customer_id", "member_id", "buyer_id",
            "用户id", "用户编号", "用户标识", "会员id", "客户id", "买家id", "用户",
        ],
    },
    {
        "key": "amount",
        "label": "订单金额",
        "required": False,
        "hint": "客单价、高价值客户判定的依据；会员等级也按它的人均分布自动分档（不给这一列就没有等级）",
        "synonyms": [
            "amount", "order_amount", "pay_amount", "total_amount", "price", "gmv",
            "订单金额", "实付金额", "支付金额", "成交金额", "金额", "客单价", "交易金额",
        ],
    },
    {
        "key": "purchase_time",
        "label": "下单时间",
        "required": False,
        "hint": "活跃度、流失预警等时间相关问句的依据",
        "synonyms": [
            "purchase_time", "order_time", "pay_time", "create_time", "trade_time",
            "下单时间", "订单时间", "支付时间", "成交时间", "购买时间", "交易时间", "创建时间",
        ],
    },
    {
        "key": "city",
        "label": "城市",
        "required": False,
        "hint": "地域分布类问句（如「哪些城市集中」）",
        "synonyms": [
            "city", "region", "province", "area", "城市", "地区", "省份", "所在城市",
            "收货城市", "城市名称",
        ],
    },
    {
        "key": "gender",
        "label": "性别",
        "required": False,
        "hint": "人群筛选常用维度",
        "synonyms": ["gender", "sex", "性别", "用户性别"],
    },
    {
        "key": "age",
        "label": "年龄",
        "required": False,
        "hint": "人群筛选常用维度",
        "synonyms": ["age", "年龄", "用户年龄", "年龄段"],
    },
    {
        "key": "member_level",
        "label": "会员等级",
        "required": False,
        "hint": "你自己的等级口径（黑卡 / 金卡 / VIP3…）：映射了就直接用你的，不映射才按消费金额推导",
        "synonyms": [
            "member_level", "member_grade", "level", "vip_level", "grade", "tier",
            "会员等级", "客户等级", "会员级别", "会员星级", "VIP等级", "等级",
        ],
    },
    {
        "key": "category",
        "label": "商品类目",
        "required": False,
        "hint": "品类偏好类问句（如「喜欢美妆的用户」）",
        "synonyms": [
            "category", "cate", "class", "一级品类", "二级品类",
            "类目", "品类", "商品类目", "商品分类", "类别", "商品类别",
        ],
    },
    {
        "key": "product_name",
        "label": "商品名称",
        "required": False,
        "hint": "商品级检索与展示",
        "synonyms": [
            "product_name", "product", "sku_name", "item_name", "goods_name",
            "商品名称", "商品名", "产品名称", "宝贝名称", "商品标题", "商品",
        ],
    },
]

# 归一规则：去空格、去下划线、中划线，转小写。
# 中文列名不受影响，英文的 "User ID" / "user-id" / "user_id" 会归一成同一个 key。
_NORMALIZE_DROP = str.maketrans("", "", " _-")


def normalize_column(name: str) -> str:
    """列名归一：去分隔符 + 转小写。中英文列名都走同一条路径。"""
    return (name or "").strip().lower().translate(_NORMALIZE_DROP)


def match_column(column: str) -> str | None:
    """
    单个列名 → 系统字段 key；匹配不到返回 None

    两级匹配，顺序不能反：
        1) 精确命中同义词（"实付金额" 直接等于字典项）——最可信
        2) 包含命中（"订单实付金额(元)" 含 "实付金额"）——兜底
    先精确后包含，是为了避免「订单金额」被「金额」这类短词抢先认走。
    """
    norm = normalize_column(column)
    if not norm:
        return None

    for field in FIELD_DEFS:
        for syn in field["synonyms"]:
            if norm == normalize_column(syn):
                return field["key"]

    for field in FIELD_DEFS:
        for syn in field["synonyms"]:
            syn_norm = normalize_column(syn)
            # 短词（<2 字符）不做包含匹配，否则 "id" 会命中一切
            if len(syn_norm) >= 2 and syn_norm in norm:
                return field["key"]

    return None


# ================= 构建步骤与进度骨架 =================
# weight 之和 = 100，用于把「步骤内进度」折算成总百分比。
# 顺序与 MVP 文档 5.4 描述一致：清洗 → 聚合 → 向量化 → 分块 → 建索引。
# 注意：这里只有**步骤的名字与权重**，每一步处理了多少条由真实事件给出
# （见 builder.run_build 的 emit），前端不会看到任何预估的数字。
BUILD_STEPS: list[dict] = [
    {"key": "clean", "label": "清洗交易数据", "weight": 22, "unit": "行"},
    {"key": "profile", "label": "聚合用户画像", "weight": 18, "unit": "个用户"},
    {"key": "embed", "label": "生成画像向量", "weight": 24, "unit": "条画像"},
    {"key": "chunk", "label": "切分规则文档", "weight": 16, "unit": "篇文档"},
    {"key": "index", "label": "建立检索索引", "weight": 20, "unit": "个分块"},
]


# ================= 示例问题 =================
# 按「已确认的字段」拼示例，且**只出检索类问句**——
# 统计类问句（"有多少用户"）在向导里答不好，放出来就是挖坑（见 MVP 文档第六条）。
EXAMPLE_TEMPLATES: dict[str, list[str]] = {
    "city": [
        "深圳的钻石会员都是什么特征",
        "母婴偏好用户主要集中在哪些城市",
    ],
    "category": ["喜欢美妆的用户都有什么特征"],
    "gender": ["高客单、喜欢美妆的女性用户有哪些"],
    "amount": ["客单价 500 元以上的用户都有什么共同点"],
}

# 与字段无关的通用问句：文档规则类，任何时候都值得给
EXAMPLE_COMMON: list[str] = [
    "高价值用户是怎么定义的",
    "流失预警的判定标准是什么",
    "高潜力客应该投什么样的券",
]
