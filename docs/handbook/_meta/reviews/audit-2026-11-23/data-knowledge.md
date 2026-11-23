# data-knowledge 批次内容质量审计报告

> **批次**：`docs/handbook/04-data-knowledge/`（04 · Data & Knowledge，共 10 篇 + index.md）
> **审计日期**：2026-11-23
> **基线文章**：`docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.1.md`（v0.5.1，1751 行；已作为状态口径、实现边界与证据写法的基准）
> **审计范围**：
> - 10 篇正文：`01-rag-architecture.md` … `10-enterprise-knowledge-base.md`
> - `docs/handbook/04-data-knowledge/index.md`（目录一致性）
> - 相关代码：`src/rag_demo/{retrieval,generation,db,agent,mvp,api,control,merchant,tools,storage}/`、`src/rag_demo/config.py`、`answer_guard.py`、`permissions.py`、`auth.py`、`logging_setup.py`、`profile_view.py`、`kb_stats.py`、`cache.py`、`pipeline.py`、`splitter.py`、`ingest_*.py`
> - 相关测试/实验产物：`tests/`、`tests/ablation_rrf_k/`、`tests/eval_report.md`、`bug/10.11/`、`docs/数据模型.md`、`docs/product/merchant-dashboard-v1-technical-design.md`、`data/docs/tag_definitions.md`、`docker-compose*.yml`
> - 协议/基线文档：`AGENTS.md`（§10/§12/§13/§18/§19）、`docs/agent.md`、`docs/agent-design-current-vs-target.md`
> **审计环境（重要）**：仓库 `F:\workspace\python\rag-demo`，HEAD `32ad31bc2636`，分支 `b-end-2.0-p0`；工作区存在未提交修改（AGENTS.md、src/rag_demo/api/main.py 等），本报告以**当前工作区文件**为代码事实依据，不是对 HEAD 快照的断言。
> **审计边界**：只读审计，未修改任何文章/配置/代码，未写其他文件；**未运行 pytest、Eval、浏览器或性能压测**，下文“证据”均为静态代码/文档/实验产物核对；“未核验”项明确标注，不以“看起来合理”代替证据。

## 结论统计

| 结论 | 篇数 | 文章 |
|---|---:|---|
| 通过 | 5 | 01、03、04、08、10 |
| 条件通过 | 5 | 02、05、06、07、09 |
| 不通过 | 0 | — |

| 严重级别 | 数量 | 分布 |
|---|---:|---|
| P0 | 0 | — |
| P1 | 2 | 05 上下文脱敏表述、06 代码围栏未闭合 |
| P2 | 18 | 02(3)、03(1)、04(1)、05(2)、06(2)、07(3)、08(1)、09(3)、10(2) |

总体判断：本批 10 篇的**技术主线与 Qianke 代码/实验产物高度对得上**，尤其是 RAG 链路、混合检索参数与实测数字、pgvector/pgvector 表结构、SQL 安全四层、控制面/商家 schema、KB 接口与清空语义，均能逐项复核。主要风险集中在三类：① 少量“实现边界”表述过于绝对（05 上下文脱敏、05/06 demo 只读、10 文档级 ACL）；② 一处 Markdown 结构硬伤（06 代码围栏）与一处跨篇自相矛盾（06 缓存键 vs 01/代码）；③ 伪代码中混入了不存在的具体代码标识（07 `list_orders_by_paid_at`、08 `metrics.py`）。

---

## 批次级辅助检查

1. **12 个二级章节结构**：10 篇均为 `## 1.`…`## 12.` 共 12 个 H2，符合基线文章与 `var/check_handbook_final.py` 的 `sections12` 规则。**例外**：06 第 8 节代码块关闭围栏写在文字行末（`...质量规则 DSL``` `），全文围栏 15 个（奇数），渲染时第 8 节之后可能整体落入代码块，属于结构不合格（见 06 的 P1）。
2. **frontmatter**：10 篇字段齐全（title/description/section/section_order/order/slug/doc_status/implementation_status/version/updated/reading_minutes/prerequisites/tags/related），`order` 1–10 连续，`slug` 与文件名及互引一致，`description` 长度 84–97 字（符合信息架构 80–160 字），H1 与 `title` 一致，每篇至少 1 张 Mermaid 图。异常：02 `implementation_status: 已实现` 与正文“部分实现/规划中”不一致（已单列 P2）；09 `部分实现` 与正文明确“已实现”段相比偏保守（保守标注不构成虚假声明，未单列为问题，仅提示可改“已实现 + 部分实现”）。
3. **跨篇自相矛盾**：01 §5 写“问答缓存键包含数据集、问题、检索参数、**数据版本**、RRF k、历史与人格”；06 §5 写“`answer_cache.clear()` 清空问答缓存（**缓存键不含数据版本**）”。代码事实支持 01（`src/rag_demo/cache.py:93-129`、`src/rag_demo/pipeline.py:108-112`、`src/rag_demo/api/main.py:1822-1825` 均把 `data_version` 拼入键），06 表述错误。
4. **文档过时状态**：`docs/agent.md`（2026-10-28）与 `docs/agent-design-current-vs-target.md` 仍写“3 个原子 Tool”，而基线 v0.5.1 已按代码核验为 7 个注册 Tool；本批 10 篇未直接引用“3 Tool”数字，不构成直接错误，但后续引用旧文档时须以基线/代码为准。
5. **证据类型**：本批大量使用“代码注释记录/仓库内实验产物”，对应文件均存在且数字可逐项对上（11.0s→15.1s +16%、多路规划约 6s/31%、整次问答 9~17s/92~96%、BM25 18.3ms vs 稀疏 130.6ms、17 题/15 题打平、33 题 90.9% 等）；这是本批证据强度较高的部分。
6. **外部链接**：文章中的论文/官方文档 URL（arXiv、pgvector、Neo4j、DAMA、NIST 等）均为常见权威地址，但本次未逐一 HTTP 访问，统一列入“未核验”。

---

## 1. `docs/handbook/04-data-knowledge/01-rag-architecture.md`

- **文件路径**：`docs/handbook/04-data-knowledge/01-rag-architecture.md`（220 行）
- **结论**：**通过**
- **实现状态声明是否成立**：成立。正文 §8 的“已实现 / 部分实现 / 规划中”三分与代码一致；“索引新鲜度部分实现”“检索侧过滤未统一”等边界未被写成已实现。
- **证据核验结果**：

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| 离线 chunk 400 / overlap 40；父块 ≤1600 字 | `src/rag_demo/splitter.py:57-58,65` | 成立 |
| BGE-M3 1024 维 → pgvector + HNSW | `src/rag_demo/config.py:264`；`src/rag_demo/db/schema.py:66-77,102-114` | 成立 |
| TOP_K_VECTOR/BGE=20、TOP_K_RRF=30、TOP_K_PROFILE/WIKI=3、ENABLE_MULTI_QUERY=True | `src/rag_demo/config.py:185-189,269` | 成立 |
| RRF 用名次、公式 Σ1/(k+rank+1) | `src/rag_demo/retrieval/hybrid_retriever.py:290-326`（实现为 `+1.0/(k+rank+1)`） | 成立 |
| 分池取舍：画像全局精排 Top-K、文档每路保名额再合并 | `src/rag_demo/retrieval/query_processor.py:322-470,541` | 成立 |
| 父块回填 11.0s→15.1s（+16%，代码注释） | `src/rag_demo/retrieval/reranker.py:94` | 成立 |
| 多路规划一次 LLM 调用、约 6s/占 31%；整次问答 9~17s、92~96% 在生成 | `src/rag_demo/retrieval/query_processor.py:488`；`src/rag_demo/cache.py:10`；`src/rag_demo/pipeline.py:31` | 成立 |
| 失败语义：检索不可用 error、LLM 不可用 llm_error 分开 | `src/rag_demo/pipeline.py:150,160,166-174` | 成立 |
| 权限裁剪统一 `render()`；租户隔离独立物理库；可溯源 sources+trace | `src/rag_demo/permissions.py:620-664`；`src/rag_demo/config.py:68-95`；`src/rag_demo/pipeline.py:354-371`（生成结果 + trace；sources 由 generate/响应结构承载） | 成立 |
| 问答缓存键含 dataset/检索参数/数据版本/RRF k/历史/人格 | `src/rag_demo/cache.py:93-129`；`src/rag_demo/pipeline.py:108-112` | 成立 |
| 离线评测 2026-11-11、33 题、90.9%(30/33)、来源召回宏 97.8%/微 96.7% | `tests/eval_report.md:3,15,17-18` | 成立 |
| RAG Tool 只返回 content/score/source，不生成答案 | `src/rag_demo/agent/tools/rag.py:23-64` | 成立 |

- **问题列表**：未发现 P0/P1/P2 问题。§9 的验收清单是待执行项（`[ ]`），文章未声称已全部通过，不构成虚假状态。
- **未核验项**：未重跑 `tests/eval_report.md` 对应评测与 pytest；未实测延迟数字（引用的是代码注释/实验产物，不是本次运行结果）；文章外部链接未访问；§6“成本可控：usage 记录、无预算”按基线 `docs/agent.md` 与代码结构判断，未在运行中验证 usage 汇总。
- **一句话总评**：本批证据最扎实的一篇，链路、参数、数字、失败语义都能落到代码或实验产物，可作为其余 9 篇的写法基准。

---

## 2. `docs/handbook/04-data-knowledge/02-vector-database.md`

- **文件路径**：`docs/handbook/04-data-knowledge/02-vector-database.md`（220 行）
- **结论**：**条件通过**
- **实现状态声明是否成立**：正文 §8 的“已实现/部分实现/规划中”成立；但 frontmatter `implementation_status: 已实现` 与正文自述“部分实现（稀疏 HNSW 默认关闭、过滤与 ANN 组合未优化、无容量压测）/规划中（量化、多副本、分片、联邦检索）”不一致，属状态标注不成立。
- **证据核验结果**：

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| PostgreSQL 16 + pgvector/pgvector:pg16 | `docker-compose.dev.yml:18`；`docker-compose.yml:30` | 成立 |
| `vector(1024)`、HNSW、`vector_cosine_ops`；wiki 表含 dept/sensitivity/metadata/parent_key/parent_text | `src/rag_demo/db/schema.py:43-77,102-114` | 成立 |
| `sparsevec(250002)`；`ENABLE_SPARSE_HNSW = False` | `src/rag_demo/config.py:251`；`src/rag_demo/db/schema.py:216-267` | 成立 |
| 指纹 = COUNT + 内容摘要；fresh/stale/unknown；不能只比条数 | `src/rag_demo/db/schema.py:315-357,425-457` | 成立（公式表述有轻微偏差，见 P2-3） |
| 写入每批 50 条、commit 后回调进度；空输入不得走 TRUNCATE | `src/rag_demo/ingest_data.py:62,569,572-588,634-637` | 成立 |
| 只读查询后必须 `rollback()`，避免 idle in transaction 阻塞 DDL | `src/rag_demo/retrieval/hybrid_retriever.py:177,217-218,265` | 成立 |
| 按数据集独立物理库，漏切换明确报错 | `src/rag_demo/config.py:68-95`；`src/rag_demo/db/connection.py:63-86` | 成立 |
| 语料 8110 条画像 + 36 块 = 8146；BM25 18.3ms、稀疏 130.6ms（含约 80ms 前向） | `bug/10.11/2026-10-11_BM25对BGE-M3稀疏向量实验.md:35-37,56-60` | 成立 |
| 备份恢复“已实现（控制面脚本）” | `scripts/backup_control_plane.py:131`（备份含 `vec_db.dump`） | 成立（覆盖范围需注意，见未核验） |

- **问题列表**：

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | frontmatter:9 | `implementation_status: 已实现` | 与 §8“部分实现/规划中”矛盾；同批 01/03/06/07/10 用组合状态 | 改为“已实现 + 部分实现”，或按基线口径写明规划中项 |
| P2 | §7 末段、§6 表“规模”行 | “并保留‘精确扫描足够快时不建 HNSW’的开关” | 实际只有**稀疏** HNSW 开关（`ENABLE_SPARSE_HNSW`），稠密 HNSW 对两表无条件创建（`db/schema.py:102-114`） | 限定为“稀疏索引用 ENABLE_SPARSE_HNSW 控制” |
| P2 | §4 指纹公式 | “指纹 = COUNT + md5(按主键排序的 (id, md5(文本)) 拼接)” | 画像表实际按 `user_id` 排序（`db/schema.py:325-330`），文档表才按 `id`（`:334-339`）；“主键 id”对画像不准确 | 分画像/文档两表写口径，或写“按主键/业务键排序” |

- **未核验项**：未实跑 pgvector 查询/HNSW Recall@K；“ANN 召回率通常 95%~99%+”为通用经验值，未在本仓库实测；百万级未压测（文章已如实标注）；备份脚本对向量库的恢复流程未实际演练；文章外部链接未访问。
- **一句话总评**：表结构、参数与实验数字全部对得上，属于“原理 + 真实工程”结合较好的文章；扣分在状态元数据与稀疏/稠密 HNSW 开关的边界表述。

---

## 3. `docs/handbook/04-data-knowledge/03-hybrid-retrieval-reranking.md`

- **文件路径**：`docs/handbook/04-data-knowledge/03-hybrid-retrieval-reranking.md`（220 行）
- **结论**：**通过**
- **实现状态声明是否成立**：成立。§8 已实现项（BM25/稀疏/RRF/精排/分池/父块/trace/消融）均有代码或实验产物；部分实现/规划中边界清楚。
- **证据核验结果**：

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| RRF 只用量级无关名次；k 默认 60，可用 `RAG_RRF_K` 覆盖；`both` 两级 RRF 同 k | `src/rag_demo/config.py:191-201`；`src/rag_demo/retrieval/hybrid_retriever.py:290-378` | 成立 |
| BM25 从 `search_index` 读已落库分词结果（省约 6s） | `src/rag_demo/retrieval/hybrid_retriever.py:152-199,:157` | 成立 |
| 关键词模式 bm25/sparse/both，默认 bm25；稀疏缺失回退 BM25 | `src/rag_demo/config.py:238-249`；`hybrid_retriever.py:329-361` | 成立 |
| 文档池每路精排 Top3；画像池全局 Top3；阈值默认 0 | `src/rag_demo/config.py:185-189,285`；`src/rag_demo/retrieval/query_processor.py:411-474,541` | 成立 |
| 父块回填 mode=section/doc/off，默认 section；≤1600 字 | `src/rag_demo/config.py:300-302`；`src/rag_demo/retrieval/reranker.py:98-147`；`src/rag_demo/splitter.py:65` | 成立 |
| WIKI_MIN_SCORE 反例 DA-01=0.001 / OPT-02=0.010 | `src/rag_demo/config.py:277-285`（注释原文） | 成立 |
| 混合检索异常时 RAG Tool 降级关键词；精排失败不静默跳过 | `src/rag_demo/agent/tools/rag.py:26-32`；`query_processor.py:436-443` | 成立 |
| BM25 vs 稀疏 17 题：100% vs 94.1%、1.4 vs 1.0、18.3ms vs 130.6ms、15 题打平 | `bug/10.11/2026-10-11_BM25对BGE-M3稀疏向量实验.md:56-60,85` | 成立 |
| RRF k 消融 33 题（2026-10-30，k=10/30/60/100）：k∈[30,100] 不可区分、k=10 单题抖动、最终上下文 4 档逐题相同 | `tests/ablation_rrf_k/README.md:13-14`；`report.md:3-11` | 成立 |
| 精排串行、检索并行（contextvars 逐任务拷贝） | `query_processor.py:383-402` | 成立 |

- **问题列表**：

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §2 量纲说明 | “余弦相似度：0~1；BM25：0~几十；稀疏内积：可正可负” | 余弦相似度理论范围是 [-1,1]；BGE 归一化后通常落在 0~1，但直接写 0~1 不严谨 | 改为“余弦相似度理论 [-1,1]；本仓库归一化向量通常 0~1” |

- **未核验项**：未重跑 17 题对比与 RRF k 消融（只核对了落盘产物与报告）；RRF/模型卡/论文链接未访问；“更大规模候选策略、多语言/多模态检索”为规划项，未核验。
- **一句话总评**：参数、降级策略、实验数字都能对上，是混合检索章节里可复核性很强的一篇；仅有 1 处通用范围表述需精确化。

---

## 4. `docs/handbook/04-data-knowledge/04-knowledge-graph.md`

- **文件路径**：`docs/handbook/04-data-knowledge/04-knowledge-graph.md`（220 行）
- **结论**：**通过**
- **实现状态声明是否成立**：成立且克制。全篇明确“当前未实现（理论知识 + 规划中）”，没有把图谱能力写成已有；frontmatter 与正文一致。
- **证据核验结果**：

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| 代码中不存在 neo4j / networkx / 图谱相关模块 | 全仓库 `*.py` 检索 `import/from (neo4j|networkx|igraph)` 与 `neo4j./networkx.` 均 0 命中；`pyproject.toml` 无图数据库依赖 | 成立 |
| 无图数据库、无三元组存储、无实体关系抽取管线、无 GraphRAG | 同上；未发现相关模块/表（`entity_edge` 仅文章理论示例，代码中不存在） | 成立 |
| `docs/数据模型.md` 记录 demo 的 user_id 不是稳定实体键，同 ID 属性会冲突 | `docs/数据模型.md`（user_id 行“demo 中不是稳定实体键”；8,110 行由 21,000 条交易聚合） | 成立 |
| 现有能力只有关系型表、SQL、向量 + BM25 检索 | 与 01/02/03 核验结果一致 | 成立 |

- **问题列表**：

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §8 | “代码中不存在 neo4j / networkx / 图谱相关模块（已检索确认）” | 结论正确，但“已检索确认”未给出检索范围/命令，读者无法复核 | 补一行可复核证据（如 `rg "neo4j|networkx" src/ pyproject.toml` 返回空） |

- **未核验项**：Neo4j 文档、GraphRAG 论文链接未访问；“demo 数据上建图第一步无法可靠完成”是基于 `docs/数据模型.md` 的推理，未实际建图验证（文章已定性为判断，不是实测）。
- **一句话总评**：诚实交代“未实现”，并用数据前提解释为什么现在不该建图，是本批“状态标注”做得最规范的一篇。

---

## 5. `docs/handbook/04-data-knowledge/05-enterprise-data-governance.md`

- **文件路径**：`docs/handbook/04-data-knowledge/05-enterprise-data-governance.md`（220 行）
- **结论**：**条件通过**
- **实现状态声明是否成立**：大部分成立（物理分库、L1~L4 能力裁剪、SQL 四层、日志 PII 脱敏、画像卡牌脱敏、upload_owner、策略审计哈希链、构建历史均能落到代码）；但“回答中敏感字段只以脱敏形式进入上下文”不成立，属于把**局部脱敏**写成**全链路脱敏**。
- **证据核验结果**：

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| 物理分库：demo/user/test/ent_/mch_；登录账号推导 | `src/rag_demo/config.py:68-95,118-154`；`src/rag_demo/db/connection.py:63-86`；`src/rag_demo/api/main.py::_tenant_dataset` | 成立 |
| 角色→能力 L1~L4、统一 `render()`、guest 恒 L0、route==error 对所有人透出 | `src/rag_demo/permissions.py:19-22,54,172-190,290-293,620-664`；`src/rag_demo/cache.py:107-110` | 成立 |
| SQL 四层：正则预检、只读账号、fetchmany(100)、statement_timeout=10s；正则可被双引号绕过、真正边界是 DB 权限 | `src/rag_demo/tools/sql_tool.py:11-13,34-43,78-110,118-131`；`src/rag_demo/config.py:114`；`db/connection.py:250-364` | 成立 |
| 日志 PII 脱敏（手机号/邮箱/身份证）；画像卡牌不含 profile_text/embedding、姓名打码 | `src/rag_demo/logging_setup.py:51-81`；`src/rag_demo/profile_view.py:51-80` | 成立 |
| session 只存 token 哈希；upload_owner 防越权构建/查询 | `src/rag_demo/auth.py:220-241`；`src/rag_demo/mvp/app.py:195` 及 8 处 `_require_upload` 调用 | 成立 |
| 写作用域守卫 + 数据集锁（问答整段持锁） | `src/rag_demo/db/connection.py:137-208,370`；`src/rag_demo/mvp/app.py:1238-1245,1290-1300`（finally release） | 成立 |
| 构建历史、策略审计哈希链与校验接口 | `src/rag_demo/db/schema.py:82-93`；`src/rag_demo/control/schema_pg.sql:702-731`；`src/rag_demo/api/superagent.py:194` | 成立 |
| 数据目录未实现（仅文档） | 未发现元数据服务/目录 API（`catalog` 命中均为 C 端商品目录，非数据目录） | 成立 |

- **问题列表**：

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P1 | §4 “敏感信息与脱敏” | “回答中敏感字段只以脱敏形式进入上下文” | 代码中只有日志脱敏与画像卡牌展示脱敏；`build_profile_text` 生成的 `profile_text` 含 `user_name`（`ingest_data.py:269-300`），检索候选直接把 `profile_text` 作为 `text` 返回（`hybrid_retriever.py:212-240`），`pipeline.py:347` 把 candidates 传给 `generate()`，`generation/generator.py:101-176` 拼入上下文——主问答链路没有脱敏步骤；仅 `b_end/insights.py:746` 这一条旁路使用 `redact_profile_text` | 改为“日志层与画像卡牌展示已脱敏；进入生成上下文的 profile_text 尚未脱敏”，如需能力声明则先补代码或测试 |
| P2 | §3/§4/§8 | “demo 只读”“demo 永远不允许写” | 在线登录态通过路由规避（系统管理员写路径被导向 `test` 库，`config.py:123`、`mvp/app.py:147-172`；KB `can_write` 要求企业管理员，`api/kb.py:186-198`），但连接层没有“demo 禁写”硬校验，离线/无登录态时 `_scope_dataset` 直接返回请求值（`mvp/app.py:148-150`），“永远”表述过绝对 | 改为“登录态 API 不把 demo 作为写目标；离线脚本模式仍可指定 demo，需在连接/构建入口加硬校验” |
| P2 | §2 vs §4 | 数据分级“L1 公开/L2 内部/L3 敏感/L4 高度敏感”；权限模型“L1 基础…L4 完全” | 同一 L1~L4 记号先后表示数据密级与权限能力，读者容易混为同一套等级；实际 `sensitivity` 为 INT（默认 1），与权限 L1~L4 无映射关系 | 数据分级改用“公开/内部/敏感/高敏”文字，或明确标注两套编号互不对应 |

- **未核验项**：未运行权限配置、脱敏、SQL 只读的实测用例；未实测离线模式写 demo 的行为（仅代码路径推断）；“合规未实现（需企业侧评估）”属外部合规判断，未核验。
- **一句话总评**：治理能力的“硬约束”部分证据充分；但“上下文脱敏”这句话把局部能力扩大成全链路能力，是必须修正的 P1。

---

## 6. `docs/handbook/04-data-knowledge/06-data-ingestion-etl.md`

- **文件路径**：`docs/handbook/04-data-knowledge/06-data-ingestion-etl.md`（220 行）
- **结论**：**条件通过**
- **实现状态声明是否成立**：主体成立（CSV/Markdown/图片上传、编码归一、字段映射、全量/增量、sha256 清单、五阶段进度、构建锁、空输入保护、失败留痕、构建后刷新索引/缓存均能落到代码）；但“缓存键不含数据版本”不成立，且 §8 代码围栏未闭合导致结构不合格。
- **证据核验结果**：

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| 五阶段权重 22/18/24/16/20，和为 100 | `src/rag_demo/mvp/mock_data.py:156-165` | 成立 |
| 编码顺序 BOM → 严格 UTF-8 → GBK → 兜底；顺序不能反 | `src/rag_demo/mvp/uploads.py:116-139`（注释与实现一致） | 成立 |
| pandas `sep=None` + python 引擎嗅探；失败退回逗号 | `src/rag_demo/mvp/uploads.py:146-164` | 成立 |
| 字段映射精确优先、包含兜底、短词 <2 字符不参与；仅 user_id 必填 | `src/rag_demo/mvp/mock_data.py:30-118,124-170` | 成立 |
| 未映射会员等级记为 None、level_source="none"，不再按金额推导 | `src/rag_demo/ingest_data.py:74,526-546`；`src/rag_demo/mvp/builder.py:500,625` | 成立 |
| sha256 清单 `ingested_csv` / `ingested_docs`；增量按清单合并 | `src/rag_demo/db/schema.py:669-705`；`src/rag_demo/mvp/builder.py:15-18,227-269` | 成立 |
| 空输入直接报错，不能走到 TRUNCATE；失败也写 build_history(failed) | `src/rag_demo/ingest_data.py:572-588`；`src/rag_demo/mvp/builder.py:406-414` | 成立 |
| 构建后 reload_bm25、清空 answer_cache、写指纹 | `src/rag_demo/mvp/builder.py:388-394`（reload_bm25/answer_cache.clear）；指纹写入函数 `db/schema.py:372+` | 成立（缓存键说法除外，见 P2-1） |
| 图片上传（多文件/追加/删除）；仅 CSV/Markdown/图片 | `src/rag_demo/mvp/uploads.py:58-65,200,362`；`src/rag_demo/mvp/app.py:549,591,626-637` | 成立 |
| demo 8110“用户”是样本口径；order_count 是购买记录行数 | `docs/数据模型.md`（8,110 行由 21,000 条聚合；order_count 行数说明） | 成立 |

- **问题列表**：

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P1 | §8 结尾（约 176 行） | “…质量规则 DSL```” | 关闭围栏与正文同一行，全文围栏 15 个（奇数）；按 CommonMark 该行不构成合法关闭围栏，§9–§12 可能整段被当作代码块渲染，12 节结构在渲染层失效 | 把 ` ``` ` 单独成行，重跑 Markdown/文档站渲染检查 |
| P2 | §5 末段 | “`answer_cache.clear()` 清空问答缓存（缓存键不含数据版本）” | 与代码相反：缓存键已含 `data_version`（`src/rag_demo/cache.py:93-129`，由 `pipeline.py:108-112`、`api/main.py:1822-1825` 传入），且与 01 §5 自相矛盾 | 改为“缓存键已含数据版本，但 TTL/LRU 与显式 clear 仍需保留”，或解释为何仍需主动清空 |
| P2 | §5 | “目标数据集必须在白名单内（demo 永远不允许写）” | 在线登录态通过 `_scope_dataset` 把系统管理员导向 `test`（`mvp/app.py:147-172`、`config.py:123`），但离线模式直接返回请求 dataset（`app.py:148-150`），且连接层无 demo 禁写硬校验，“永远”过绝对 | 改为“登录态写路径不落 demo；离线/脚本模式仍可能指定 demo，建议补硬校验” |

- **未核验项**：未实际执行上传/构建，编码、分隔符嗅探、增量合并行为来自代码阅读；“历史版本按人均客单价分位推导会员等级”是历史叙述，当前代码无法核验；未跑构建失败/空输入/锁冲突用例。
- **一句话总评**：接入链路的工程细节与代码几乎一一对应，信息量足；但一个未闭合围栏加一句缓存键错误，使文章在“可发布”与“事实准确”上各留一个 P1/P2 待修。

---

## 7. `docs/handbook/04-data-knowledge/07-oltp-olap.md`

- **文件路径**：`docs/handbook/04-data-knowledge/07-oltp-olap.md`（220 行）
- **结论**：**条件通过**
- **实现状态声明是否成立**：成立（控制面/商家 schema、行锁、SKIP LOCKED 队列、只读 SQL 限制、Decimal+Asia/Shanghai 看板、分析视图均能落到代码）；但伪代码里出现不存在的具体方法名，队列 SQL 与“真实代码”字面不符，控制面/数据面“分离”易被读成独立数据库。
- **证据核验结果**：

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| 库存/订单先 `SELECT ... FOR UPDATE` 再判断 | `src/rag_demo/merchant/postgres_repository.py:1509,1820,1914,1994,2063,2170,2187,2313-2322` | 成立 |
| 队列 `FOR UPDATE SKIP LOCKED` 多 Worker 消费 | `src/rag_demo/control/job_queue.py:179-195`；`src/rag_demo/control/schema_pg.sql:649-695`（`sa_job`）；`src/rag_demo/superagent/queue_pg.py:19` | 成立（SQL 表达有偏差，见 P2-2） |
| `v_reco_funnel_main` 固化口径（排除探索/模拟/非 client） | `src/rag_demo/control/schema_pg.sql:873-888`（与文章节选一致，文章为简化引用） | 成立 |
| 控制面默认 schema `qianke_control`，支持 SQLite/PG 双后端 | `src/rag_demo/control/settings.py:21-29`；`QIANKE_CONTROL_BACKEND` | 成立 |
| `QIANKE_CONTROL_BACKEND` 双后端；控制面表 + 外键/唯一约束/索引 | `control/schema_pg.sql`；`control/settings.py`；`control/postgres_repository.py` | 成立 |
| 商家看板 `dashboard_metrics.py` 只做确定性计算、不访问 DB/LLM；Decimal + Asia/Shanghai | `src/rag_demo/merchant/dashboard_metrics.py:8-9,15-31,188-260` | 成立 |
| Agent SQL 只读 + timeout + LIMIT + fetch 截断 | `src/rag_demo/tools/sql_tool.py:78-131`；`config.py:114` | 成立 |
| 设计文档：V1.0 订单级单次退款，不支持多次退款累计；历史净额会因后续退款变化 | `docs/product/merchant-dashboard-v1-technical-design.md:6,13,21,864` | 成立 |

- **问题列表**：

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §5 商家看板数据流伪代码 | `repo.list_orders_by_paid_at(merchant_id, start, end)` | 仓库不存在该方法；实际为 `list_orders_paid_between`（`merchant/postgres_repository.py:1272`，`merchant/repository.py:128`） | 改成真实方法名，或明确标注“示意名” |
| P2 | §2 队列 SQL | “`SELECT * FROM sa_job WHERE status='PENDING' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED`（真实代码位于 control/job_queue.py）” | 实际实现是 `WITH candidate AS (... FOR UPDATE SKIP LOCKED LIMIT 1) UPDATE ... RETURNING`，并带 lease/死信/attempts 逻辑（`control/job_queue.py:179-195`）；文章 SQL 是大幅简化，与“真实代码”标签不符 | 标注“简化示意”，或直接引用代码块 |
| P2 | §4 标题与正文 | “控制面与数据面分离：控制面……集中在 `qianke_control` schema……数据面是向量与检索（`vec_db*`）” | `QIANKE_CONTROL_PG_DBNAME` 默认就是 `vec_db`（`control/settings.py:48-54`），商家 schema 默认 `merchant_v1` 也在 `vec_db`（`merchant/postgres_repository.py:24,98`）；实际是**同库不同 schema 的逻辑分离**，不是独立数据库 | 改为“schema 级逻辑分离；默认与控制面同库（vec_db）”，并说明何时才拆独立库 |

- **未核验项**：未跑并发扣库存、多 Worker 领取、SQLite/PG 契约测试；未实测看板 P95/SLO（文章已标“待核验”）；“历史周期净成交金额会因后续退款变化”依据代码逻辑与设计文档推断，未构造退款场景实测。
- **一句话总评**：OLTP/OLAP 的代码落点很准，是工程对照价值较高的一篇；扣分在伪代码混入真实 API 名、队列 SQL 与“真实代码”不一致、以及控制面/数据面分离的表述过强。

---

## 8. `docs/handbook/04-data-knowledge/08-metric-semantic-layer.md`

- **文件路径**：`docs/handbook/04-data-knowledge/08-metric-semantic-layer.md`（210 行）
- **结论**：**通过**
- **实现状态声明是否成立**：成立。看板指标、标签口径文档、RAG 期望来源、schema_facts、空值/退款归属口径均有代码或评测文件支撑；未把“统一指标注册表/语义层服务”写成已实现。
- **证据核验结果**：

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| 看板指标全部 Decimal、Asia/Shanghai、纯函数、可单测 | `src/rag_demo/merchant/dashboard_metrics.py:8-9,15-31,188-260`；`tests/test_dashboard_metrics.py` 存在 | 成立 |
| `net_revenue = gross_paid_amount - refund_amount_attributed`；`cash_refund_amount` 按 refunded_at 且不参与 net_revenue | `dashboard_metrics.py:206-260`；`docs/product/merchant-dashboard-v1-technical-design.md:126-167` | 成立 |
| paid_order_count=0 时客单价返回 null | `dashboard_metrics.py:215`（`if paid_order_count else None`）；设计文档 :456 | 成立 |
| 退款金额不得超过订单总额 | `dashboard_metrics.py:105-120`（`min(amount, total_amount)`） | 成立 |
| 标签口径文档可被 RAG 检索，且评测期望来源含 tag_definitions.md | `data/docs/tag_definitions.md` 存在；`src/rag_demo/tests/eval_questions.json:8,26,35` | 成立 |
| Text2SQL `db/schema_facts.py` 实时采集表结构、条数、枚举、时间覆盖、客单价分位 | `src/rag_demo/db/schema_facts.py:21,283-310,362-374` | 成立 |
| 看板指标名 `net_revenue/gross_paid_amount/refund_amount_attributed/cash_refund_amount/average_order_value/repeat_rate` | `dashboard_metrics.py:214,495` 及 `build_overview`/`build_customer_analysis` | 成立 |

- **问题列表**：

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §4 “唯一定义源” | “定义在代码库（如 `metrics.py` + 设计文档）” | 仓库没有 `metrics.py`，实际为 `src/rag_demo/merchant/dashboard_metrics.py`；“如 metrics.py”作为示例可以，但读者按名检索会落空 | 写实际路径，或明确“示例名” |

- **未核验项**：未运行 `tests/test_dashboard_metrics.py` 与看板接口；未验证“指标级可见性尚未实现”（只做了未发现指标级权限的检索，不构成穷尽证明）；外部 dbt/Looker/MetricFlow 链接未访问。
- **一句话总评**：把“代码即口径 / 文档即口径”的分工讲清楚了，且指标定义、边界与设计文档对得上；只需把示例文件名改为真实路径。

---

## 9. `docs/handbook/04-data-knowledge/09-data-lineage-quality.md`

- **文件路径**：`docs/handbook/04-data-knowledge/09-data-lineage-quality.md`（220 行）
- **结论**：**条件通过**
- **实现状态声明是否成立**：主体成立（sha256 清单、构建历史含失败、last_build/last_full_build、指纹 fresh/stale/unknown、索引缺失统计、answer_guard 均可落到代码）；但“清单丢失只能要求全量重建”与代码中的 last_build+mtime 引导路径不符，且格式与指纹表述有小问题。
- **证据核验结果**：

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| 指纹 = COUNT + 内容摘要；fresh/stale/unknown 三态，unknown≠stale | `src/rag_demo/db/schema.py:315-357,425-457` | 成立 |
| sha256 清单（ingested_csv/ingested_docs）兼做去重与血缘 | `src/rag_demo/db/schema.py:669-705`；`src/rag_demo/mvp/uploads.py:515-598`（清单判定契约） | 成立 |
| 构建历史字段 built_at/mode/elapsed_s/rows/profiles/status/error；失败也写 | `src/rag_demo/db/schema.py:82-93`；`src/rag_demo/mvp/builder.py:406-414,460-468` | 成立 |
| last_build 供一键重建；last_full_build 记全量规模/耗时 | `src/rag_demo/db/schema.py:592-719`；`src/rag_demo/api/kb.py:169-268` | 成立 |
| 概况接口返回 dataset/mode/ready/empty/can_write/totals/docs/built_at/freshness/last_source | `src/rag_demo/api/kb.py:169-268`；`src/rag_demo/kb_stats.py:50-192` | 成立 |
| 索引缺失统计（sparse/bm25 token 缺失计数） | `src/rag_demo/db/schema.py:274-310` | 成立 |
| answer_guard 拦截“未来断言 + 数字”的编造 | `src/rag_demo/answer_guard.py:29-31,110-142`；`src/rag_demo/pipeline.py:347-357` | 成立 |
| 接入期检查：编码、空文件、同名、必填、截断、类型容错 | `src/rag_demo/mvp/uploads.py:116-139,200-231`；`src/rag_demo/ingest_data.py:97,209-241,572` | 成立 |

- **问题列表**：

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §4 “增量清单” | “清单丢失或损坏时，系统无法判断‘哪些文件已入库’，只能要求全量重建” | `builder.py:15-18` 明确“manifest 为空时用 last_build + 文件 mtime 推导入库状态”，实现见 `builder.py:227-269`；系统具备**近似引导**路径，不是只能全量重建，只是可能误判 | 改为“有 last_build+mtime 的近似引导，但可能误判，必要时仍需全量重建” |
| P2 | §10 第 8 条与 §11 之间（约 204-205 行） | “8. 只关注当前状态：……” 紧接着 `## 11. 总结` | 列表项与 H2 标题之间缺空行，渲染/格式检查可能把标题并入列表上下文 | 补一个空行 |
| P2 | §4 指纹公式 | “指纹 = COUNT + md5(按主键排序的 (id, md5(文本)) 拼接)” | 画像表实际按 `user_id` 排序（`db/schema.py:325-330`），文档表按 `id`（`:334-339`）；统一写 `id` 不够准确（与 02 同源问题） | 分表写口径 |

- **未核验项**：未实际构造“清单丢失/损坏”“构建失败”“源表变更”场景验证 fresh/stale/unknown；未跑测试；“告警未实现（仅日志）”基于代码检索未见数据质量告警，未做穷尽证明。
- **一句话总评**：血缘与一致性的核心机制（清单/构建历史/指纹）讲得实，代码依据清楚；但“只能全量重建”低估了现有引导逻辑，需要按代码修正。

---

## 10. `docs/handbook/04-data-knowledge/10-enterprise-knowledge-base.md`

- **文件路径**：`docs/handbook/04-data-knowledge/10-enterprise-knowledge-base.md`（216 行）
- **结论**：**通过**
- **实现状态声明是否成立**：成立。租户物理分库、账号推导数据集、上传归属、KB 读接口、ready/empty/403 语义、doc_id 路径安全、原文回退、清空保留 last_build/ui/doc_source_dir、OSS key 不入签名 URL 均可落到代码；文档级 ACL 的表述略强（见 P2）。
- **证据核验结果**：

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| KB 接口：overview/profiles/documents/chunks/raw/history/clear，admin 接口 | `src/rag_demo/api/kb.py:169,293,348,393,457,536,628,760,813` | 成立（history 路径表述有偏差，见 P2-1） |
| `doc_id = sha1(doc_name)[:16]`；在当前数据集反查，找不到 404 | `src/rag_demo/api/kb.py:284-286,411-413,479-481` | 成立 |
| `ready=false` 用 200 + 引导构建，`empty=true`，无权限 403 | `src/rag_demo/api/kb.py:175-181,259-260,628-690`；清空 401→403→400→409 顺序见注释 | 成立 |
| 物理分库 + 账号推导数据集 + 前端不接受 dataset | `src/rag_demo/config.py:68-95`；`src/rag_demo/api/main.py::_tenant_dataset`；`api/kb.py` 各接口无 dataset 参数 | 成立 |
| 上传归属校验 upload_owner | `src/rag_demo/auth.py:232-241`；`src/rag_demo/mvp/app.py:195` 及多处 `_require_upload` | 成立 |
| 清空：TRUNCATE 源表/索引表，删数据类 meta，保留 last_build/ui_*/doc_source_dir；只 TRUNCATE 不 DROP | `src/rag_demo/db/schema.py:613-630,749-780`（docstring 明示保留项）；`src/rag_demo/api/kb.py:628-720` | 成立 |
| 原文回退：上传源 → 仓库 docs → 分块按顺序拼回并标记 | `src/rag_demo/api/kb.py:457-530`（`source=upload/repo_docs/chunks_reconstructed`） | 成立 |
| 图片存 `oss://` key/外链，不入签名 URL；检索时换临时地址 | `src/rag_demo/media.py:10,38,104-185`；`src/rag_demo/mvp/app.py:591-622` | 成立（运行时签名替换未验证） |
| 分块接口限制条数并标记截断（`_DOC_CHUNK_LIMIT=500`） | `src/rag_demo/api/kb.py:400,430-455` | 成立 |

- **问题列表**：

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §5 接口清单 | “`GET /api/kb/docs/{doc_id}/raw / history`” | history 实际路径是 `/api/kb/history`（`api/kb.py:536`），不是 `/api/kb/docs/{doc_id}/history`；当前写法会让读者误构造 URL | 拆成两行写清楚 |
| P2 | §6 表 / §8 | “文档级 ACL 只有 dept / sensitivity 粗粒度过滤” | KB 浏览接口 documents/chunks/raw 未按 dept/sensitivity 过滤（`api/kb.py:348-390,393-455,457-530` 均为整数据集读取）；检索侧只有 `sensitivity <=`（`hybrid_retriever.py:212-240`），且 wiki 明确“无 dept 过滤”（`:256-260`） | 精确写成“检索侧有 sensitivity 上限；知识库浏览接口无文档级 ACL；dept 过滤未对文档生效” |

- **未核验项**：未实际调用 KB API；商户操作者在 `/api/kb/*` 的数据集推导未端到端核验（`main._tenant_dataset` 只按 account.dataset/ent/demo 分支，未见 merchant 分支；商户路径可能依赖账号绑定 dataset，需运行验证）；OSS 预签名替换未运行验证。
- **一句话总评**：知识库作为“可治理数据空间”的接口、状态语义与清空/回退行为都能对上代码，是本批落地感最强的一篇；只需把接口路径与文档级 ACL 的边界写准。

---

## 附：审计未覆盖与限制

1. 本次**未运行任何测试、Eval、API、浏览器或性能压测**；所有“成立”均为静态核对（代码/文档/实验产物），不等于运行时验证。
2. 代码事实以**当前工作区**为准；仓库 HEAD 为 `32ad31bc2636`，但存在未提交修改，若后续提交/回滚，需以新快照复核。
3. 文章外部链接未逐一访问（arXiv、pgvector、Neo4j、DAMA、NIST、OWASP 等），统一视为未核验。
4. 本报告只做审计，未修改任何文章、配置或代码；除本文件外未写其他文件。
