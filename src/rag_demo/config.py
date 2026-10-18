#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : config.py
@Function: 全局配置（路径 / 数据库 / 检索参数 / 计算设备）
"""
import os

import torch

# 项目根目录：src/rag_demo/config.py -> rag_demo -> src -> 根
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------- 数据与模型路径 ----------
DATA_DIR = os.path.join(BASE_DIR, "data", "dianshuang")
DOCS_DIR = os.path.join(BASE_DIR, "data", "docs")
MODEL_PATH = os.path.join(BASE_DIR, "models", "bge-m3")
RERANKER_PATH = os.path.join(BASE_DIR, "models", "bge-reranker-v2-m3")

# ---------- 数据库 ----------
_DB_BASE = {
    "host": "localhost",
    "port": 5432,
    "user": "postgres",
    "password": "123456",
}

# demo：仓库自带的示例数据。它**同时是评测基线**（33 题、F1 等都跑在这份上），
#       所以任何时候都不能被用户上传的数据覆盖——覆盖了评测记录无法复现，
#       Demo 演示也失去底座。
DB_CONFIG = {**_DB_BASE, "dbname": "vec_db"}

# user：M2 起用户自己上传并构建的数据。可以随便覆盖、随便清空，与 demo 互不影响。
USER_DB_CONFIG = {**_DB_BASE, "dbname": "vec_db_user"}

# test：M2 真实构建的**首跑库**。
#
# 为什么要有它：writes_to（写作用域守卫）与 dataset_lock（并发互斥）第一次接上真实
# ingest 的那一刻，是「以为有保护」和「保护真的生效」之间差距最大的时刻。若直接在
# user 上试、而守卫恰好没生效，写操作会静默落到默认数据集 demo 上把它清空——
# demo 同时是评测基线，清掉不可逆。先在 test 上把整条链路（含守卫与并发）跑通，
# 再去碰 user。
#
# 它脏了可以随便删库重建，不承载任何需要保留的数据。
TEST_DB_CONFIG = {**_DB_BASE, "dbname": "vec_db_test"}

# 数据集注册表：**这是「数据分开存」这件事的唯一真源**。
#
# 为什么按「数据库」分，而不是按表前缀 / 独立 schema 分：
#   分表名或分 schema 都要逐个记得改表名，而 search_index 这种派生表最容易漏——
#   一旦漏了，构建会用 TRUNCATE 把 demo 的 BM25 索引清掉，而向量检索路径还好着，
#   表现是「demo 的 BM25 半瘫」，属于最难看懂的一类故障。
#   分库则「分」这个动作只发生在连接层一处，所有表（含派生表）自动跟着走。
#
# 另一个好处是失败模式：忘切库会**连不上/找不到表并明确报错**；
#   而忘 SET search_path 或漏改表名，只会安静地打到 demo 表上，查出错数据还不报错。
#   宁可明确失败，不要静默用错数据。
DATASETS = {
    "demo": DB_CONFIG,
    "user": USER_DB_CONFIG,
    "test": TEST_DB_CONFIG,
}

# ---------- Text2SQL 只读账号 ----------
# SQL 由 LLM 生成，应用层正则只能是「早失败提示」，不是安全边界。
# 真正的边界落在这里：查询路用下面这个只有 SELECT 权限的账号连接，
# 即使校验被绕过（双引号表名、query_to_xml 之类），也写不了库、读不到授权外的表。
#
# 账号由 db/connection.ensure_readonly_access() 幂等创建并授权
# （tools/init_db.py 与 db/provision.py 在建库后调用；老环境首次查询时自愈）。
# 生产环境必须用环境变量改掉默认密码。
READONLY_DB_USER = os.environ.get("RAG_SQL_READONLY_USER", "sql_reader")
READONLY_DB_PASSWORD = os.environ.get("RAG_SQL_READONLY_PASSWORD", "sql_reader_demo_pwd")

# 单次 SQL 最多取多少行：LIMIT 由 LLM 决定，可能写成 1000000，
# 必须在取数侧强制截断，否则一次查询就能把服务卡住 / 把内存打满。
SQL_FETCH_MAX = 100

# ---------- 企业数据集（M3：数据库按企业划分） ----------
# 隔离单位是**企业**，不是个人：同一企业的员工共享一个库，企业之间互不可见。
# 数据集名 ent_<企业ID>，库名 vec_db_ent_<企业ID>；企业审核通过时注册，
# 第一次构建时才真正 CREATE DATABASE（建库是重操作，不该挂在一次点击上）。
ENTERPRISE_DATASET_PREFIX = "ent_"
ENTERPRISE_DB_PREFIX = "vec_db_ent_"
# 系统管理员在向导里调试用哪个库（不能是 demo：demo 是评测基线兼演示底座）
ADMIN_DEBUG_DATASET = "test"


def enterprise_dataset_name(enterprise_id: int) -> str:
    return f"{ENTERPRISE_DATASET_PREFIX}{int(enterprise_id)}"


def enterprise_db_name(enterprise_id: int) -> str:
    return f"{ENTERPRISE_DB_PREFIX}{int(enterprise_id)}"


def register_dataset(name: str, dbname: str) -> dict:
    """
    运行时注册一个数据集（企业审核通过 / 启动时从账号库恢复）

    `DATASETS` 同时是「合法数据集白名单」，connection._resolve 会据此校验。
    因此动态库必须走这里注册，否则第一次 get_conn 就会抛 UnknownDataset。
    连接、锁、BM25 索引都按数据集名分键，注册后自动各走各的。
    """
    DATASETS[name] = {**_DB_BASE, "dbname": dbname}
    return DATASETS[name]

# 默认数据集：**保持 demo**。pipeline / hybrid_retriever / sql_tool 里几十处
# get_conn() 都不传参数，因此它们的默认行为与改造前完全一致——评测脚本不用改，
# 这正是保住既有评测基线的前提。向导的路由会显式切到 user。
DEFAULT_DATASET = "demo"

# 注（第五轮）：会员等级不再「按金额分档推导」——用户没映射等级列时该维度就是未知，
# 因此原先的 DEMO_MEMBER_LEVEL_NAMES / MEMBER_LEVEL_TIER_COUNT 已无使用方并删除；
# `ui-config` 里的 member_level_names 字段保留可读（旧配置兼容）但已 deprecated。

# ---------- 检索参数 ----------
TOP_K_VECTOR = 20   # 向量单路召回数量
TOP_K_BM25 = 20     # BM25 单路召回数量
TOP_K_RRF = 30      # RRF 融合后候选数量
TOP_K_PROFILE = 3   # 画像池保留条数（**全局**：跨路合并统一精排后取 Top-K，不是每路）
TOP_K_WIKI = 2      # 文档池保留条数（**每路**上限，非强制填满）

# ---------- 「返回多少个用户」的可调范围（接口层按角色放行） ----------
# 只有运营及以上角色能调（见 permissions.CAP_TOPK）。
# 它调的就是 TOP_K_PROFILE——画像池的全局名额，在统一精排时直接生效
# （而不是精排完再截断：那样等于「先按 3 个挑完再扔」，两套口径）。
# 默认 None = 用上面的 TOP_K_PROFILE(3)；评测 / 工具脚本不传即维持基线。
TOP_K_PROFILE_MIN = 1
TOP_K_PROFILE_MAX = 30
TOP_K_PROFILE_MIN = 1
TOP_K_PROFILE_MAX = 30

# ---------- API 文档开关 ----------
# /docs 与 /openapi.json 会完整暴露所有接口、请求模型与字段结构（含尚未对外的特权接口），
# 属 Demo 便利项。生产环境必须置 False —— 它是"绕过前端直接看接口"的最短路径。
ENABLE_API_DOCS = True

# ---------- API 角色（Demo 过渡态，⚠ 接入电商系统后必须改） ----------
# 当前没有登录态，角色只能由请求头 X-Role 传入，等于"调用方自报身份"。
# 这里定义**请求头缺失**时的兜底角色：
#
#   "admin" —— 沿用改造前的全权行为。理由：既有的工具脚本（check_stream_cache /
#              check_api_options / profile_*）都不带角色头，默认 guest 会让它们全挂。
#   "guest" —— 真正的安全默认值，但会让上述脚本失效。
#
# ⚠ 现在选 admin 是**过渡妥协**，意味着"不带身份的人拿到全部权限"。
#   接入电商系统后必须做两件事：① 角色改从登录态取；② 本值改成 "guest"。
#   判定依据：只要本值是 admin，这套权限就只是**演示开关**，不是安全边界。
DEFAULT_API_ROLE = "admin"

# 关键词召回走哪一路：bm25 / sparse / both
#   bm25   仅 BM25（默认）—— 快、命中率略高（实测 hit@20 100% vs 94.1%）
#   sparse 仅 BGE-M3 原生稀疏向量 —— 命中时名次更靠前，但每次多一次模型前向（约 80ms）
#   both   两路都跑再 RRF 融合 —— 质量最稳，代价最大
# 背景：A/B 实验显示两者各有强项，详见 bug/10.11/2026-10-11_BM25对BGE-M3稀疏向量实验.md
KEYWORD_RETRIEVER = "bm25"

# ---------- 检索索引持久化（search_index 表） ----------
# BM25 分词结果与 BGE-M3 稀疏权重统一落库，取代此前的本地 pkl 缓存：
#   1. 启动免去重新 jieba 分词 8146 条
#   2. 稀疏检索走 pgvector sparsevec 的库内计算，不再把全量权重拉进内存
#   3. 多实例共享同一份索引，一致性由数据库保证（不再依赖内容指纹）
SEARCH_INDEX_TABLE = "search_index"
SPARSE_VEC_DIM = 250002   # BGE-M3 词表大小，即 sparsevec 的维度上限

# ---------- 提示词里的数据事实（运行时从实库采集） ----------
# 表结构里的条数、枚举取值、数值范围、时间覆盖、客单价分位都来自当前数据集，
# 不再写死在提示词里（原因见 db/schema_facts.py 模块注释）。
# 采集结果按数据集缓存：每次问答都重扫分布没有价值，而数据只在 ingest 后变化，
# 那条路径会显式失效缓存（见 ingest_data 末尾的 invalidate）。
SQL_SCHEMA_CACHE_TTL = 300     # 秒；兜底过期时间，防止绕过 invalidate 的写入
SQL_SCHEMA_ENUM_LIMIT = 20     # 每个枚举列最多展示多少个取值（按条数降序）

# 稠密向量的维度：bge-m3 输出 1024 维，建表时用来声明 embedding vector(1024)。
# 单独提出来是因为它同时出现在建表 DDL 和检索 SQL 的 %s::vector 转换里，
# 散着写迟早对不上。
EMBED_DIM = 1024

# 五路 query 检索（直接/分解/简化/关键词/HyDE）
# 开启后每次问答多一次 LLM 调用（4 个变体一起生成）与 4 次额外检索，RQ 更稳但更慢。
# 关闭则退化为单路混合检索。
ENABLE_MULTI_QUERY = True  # TODO(perf): [P1] 开启后平均耗时 +51%，详见 bug/性能隐患台账.md

# 按需多路：由 LLM 判断需要哪几路，不是一律全跑。
# 上限指「额外方式」的个数（不含永远执行的「直接检索」），防止模型贪心全选。
MULTI_QUERY_MAX_VARIANTS = 2

# wiki 精排分数门槛：低于此分不占名额（0 = 不过滤，保持原有行为）。
#
# 实测（bge-reranker-v2-m3，sigmoid 后）：强相关 chunk ≈ 0.8，明显无关 ≈ 0.005。
# 但「是否该占名额」不能用分数判定，实测三组反例：
#   DA-01「哪些标签跟美妆相关」需要 tag_definitions.md ...... 0.001
#   OPT-02「深圳钻石会员特征」不需要 analysis_report_template.md ... 0.010
#   OPT-01「高客单美妆女性」需要 tag_definitions.md 的高客单定义 .... 0.054
# 需要的最分（0.001）反而低于不需要的（0.010）——根因是 chunk 粒度错配：
# reranker 判断「单个 chunk 能否直接作答」，而 DA-01 需要的是「chunk 集合能否提供线索」。
# 故默认设 0 不过滤，待 Parent Document 召回落地后再启用（详见 bug/10.11 问题 5）。
WIKI_MIN_SCORE = 0.0

# ---------- Parent Document 召回 ----------
# 命中的 wiki chunk 扩展为所在文档的全文，解决「chunk 级分数无法支撑文档级取舍」的问题。
# 典型场景：DA-01「哪些标签跟美妆相关」需要 tag_definitions.md 的全部标签定义，
# 而其中任一个 chunk 单独看都答不了该问题（rerank 只给 0.001）。
WIKI_EXPAND_FULLTEXT = True
WIKI_MAX_CHARS = 1200   # 单篇文档扩展后的最大字符数（TODO(perf): [P2] 调小可降耗时，见 bug/性能隐患台账.md）

# ---------- LLM 调用 ----------
# 思考模式（reasoning）：开启时模型会先输出一大段推理过程，再给最终答案。
# 那段推理不返回给用户、也进不了答案，但**照样消耗时间和 token**。
#
# 实测（2026-10-14，deepseek-flash，同一问题）：
#     开启  20.36s  completion_tokens 2930（其中 reasoning 2197，占 75%）
#     关闭   7.46s  completion_tokens  863（无 reasoning）
# 关闭后**快 63%**，而且耗时波动大幅收窄 —— reasoning 长度本身波动很大，
# 是此前「同一 prompt 耗时差 11~14 倍」的主要原因之一（见台账 P9）。
#
# ⚠️ 关闭参数是 {"thinking": {"type": "disabled"}}：
#    服务端期望的是 ThinkingOptions 结构体，传布尔值 false 会直接 422。
#    另外 "enable_thinking" 字段**无效**（实测传了照旧输出 reasoning）。
ENABLE_THINKING = False

# ---------- 送入 LLM 的 SQL 段精简 ----------
# 实测（2026-10-14，OPT-05）：context 总长 3146 字，其中 SQL 段占 1503 字（48%），
# 比全部检索资料（1296 字）加起来还大。构成是 SQL 原文 + 未做任何处理的原始结果行。
#
# 两处浪费：
#   1. SQL 原文——模型只需要「结果」，不需要知道查询怎么写的（它又不改 SQL）。
#      而复杂 SQL 常有 5 个 CTE、50 行，光原文就 500~800 字
#   2. 结果行未截断——一格里可能塞着整段文本或十几个字段
#
# 这些开关是为了「保护现有行为」：需要回退时改配置即可，不必回滚代码。
CONTEXT_INCLUDE_SQL_TEXT = False   # 是否把 SQL 原文也放进 context
SQL_ROWS_MAX = 20                  # 最多送入多少行结果
SQL_CELL_MAX_CHARS = 40            # 单个单元格最长字符数

# ---------- 计算设备 ----------
# RTX 3060 6GB 显存紧张：两个 568M 模型 fp32 约 4.4GB 必 OOM，
# 故 cuda 下统一用 fp16（约 2.2GB）；cpu 下保持 fp32（CPU 不支持 fp16 算子）。
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32

# ---------- 意图路由（闲聊 / 业务）----------
# 改造前：关键词规则（tools/router.py 的 CHITCHAT_KEYWORDS）。规则只拦得住
#         「你好 / 谢谢 / 天气怎么样」这类显式寒暄，漏判的闲聊要继续走
#         「多路规划 LLM(3.8s) + 检索(0.5s) + 答案生成(20.9s)」——为拦一句闲聊
#         付约 25s（耗时数据见 bug/10.14/2026-10-14_性能逐模块计时与方案A实验.md）。
# 改造后：BERT 二分类（bert_query_classify 微调产物）在入口层判掉，单条约 13ms。
#         数值对比（准确率 / 逐条延迟 / 代价换算）见
#         bug/bert意图路由替换-延迟与准确率对比.md
#
#   "bert"   BERT 判定（默认）
#   "hybrid" 规则先短路（命中即拦截，省掉 13ms），未命中再交 BERT
#   "rule"   强制关键词规则（回退开关 / 对照实验用）
# 三种模式在 BERT 不可用时（模型目录缺失、加载失败）一律回退规则，服务不中断。
INTENT_ROUTER = "bert"

# 微调产物目录。注意它在 .gitignore 里（不入库），新环境需先跑 train.py——
# 缺失时 router 自动回退规则，只是漏判变多。
INTENT_MODEL_PATH = os.path.join(
    BASE_DIR, "src", "rag_demo", "bert_query_classify", "models", "bert-intent"
)

# 判闲聊的概率门槛：**故意取高值**。
# 两个方向的代价不对称：
#   业务→闲聊（误伤）= 拒答真问题，且 BERT 这一层没有兜底——query_processor 的
#                       路由复核只能捞「漏判」（它只在 RAG 分支里才有机会改道）
#   闲聊→业务（漏判）= 多走一次检索 + 生成，约 25s 白花，但**答得出来**
# 所以宁可漏判。门槛扫描实测（0.5~0.99 的误伤/漏判曲线）见上述对比文档。
INTENT_CHITCHAT_THRESHOLD = 0.9

# 与训练时的 max_length 一致（bert_query_classify/train.py MAX_LENGTH=64）。
# 超长截断：闲聊判断不看长尾，截断能省 forward 时间且不影响结果。
INTENT_MAX_LENGTH = 64

# ---------- 入口路由回流埋点 ----------
# 「还要不要再补数据」只能由**线上真实 query 分布**回答，而真实流量是没有标签的：
# 用户不会告诉你他问的是闲聊还是业务。所以必须先把每次判定记下来
# （query / 判定 / P(闲聊) / 门槛 / 耗时），事后才能补标签、看分布，再决定补什么形态。
#
# 落盘在 logs/（不入库）——这是运行期数据，不是仓库数据。
# 分析脚本：src/rag_demo/bert_query_classify/analyze_routes.py
INTENT_TELEMETRY = True
INTENT_TELEMETRY_PATH = os.path.join(BASE_DIR, "logs", "intent_routes.jsonl")
# 高流量场景按比例采样；1.0 = 全量。当前量级很小，全量记，样本才够看分布。
INTENT_TELEMETRY_SAMPLE_RATE = 1.0
