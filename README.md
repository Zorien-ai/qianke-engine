# 用户画像 RAG Demo

基于 pgvector + bge-m3 + bge-reranker-v2-m3 的用户画像问答：
多路检索 + RRF 融合 + Cross-Encoder 精排，意图路由分流 Text2SQL。

## 启动

### 1. 起数据库（PostgreSQL + pgvector）

```bash
docker compose up -d
docker compose ps          # 状态显示 (healthy) 才算真的好了
```

数据库参数（库名 `vec_db` / 用户 `postgres` / 端口 `5432`）写在 `docker-compose.yml`，
与 `src/rag_demo/config.py::DB_CONFIG` 严格对齐——**改一边要改另一边**。

首次使用需要导入数据：

```bash
uv run python src/rag_demo/ingest_data.py                  # 用户画像 8110 条
uv run python src/rag_demo/ingest_docs.py                  # 知识库文档分块
uv run python src/rag_demo/tools/build_search_index.py     # BM25 分词 + 稀疏权重落库
```

> ⚠️ 前两步跑完后**必须**重跑 `build_search_index.py`，否则检索会静默使用旧索引。
> 验证：`uv run python src/rag_demo/tools/check_search_index.py`

### 2. 起应用

```bash
$env:DEEPSEEK_API_KEY="sk-你的key"
uv run uvicorn rag_demo.api.main:app --reload --port 8000
```

访问 <http://127.0.0.1:8000>（交互页面） / `/docs`（API 文档）

### 排错

**数据库没起来时，表现是「所有问题都答『根据现有资料无法确定』」**——
那不是知识库缺内容，而是检索没有可用数据源。先 `docker compose ps` 确认状态。

（这种情况现在会明确报「检索服务暂时不可用」，见
`bug/10.14/2026-10-14_数据库故障被伪装成资料缺失.md`）

## 能力清单

### 1. 运营 / 市场侧

| 业务需求 | 示例问法 | 依赖能力 |
|---|---|---|
| 人群圈选 | 高客单、喜欢美妆的女性用户有哪些 | 组合条件 + 语义检索 |
| 人群画像速览 | 深圳的钻石会员都是什么特征 | 画像检索 + 聚合 |
| 标签口径查询 | 高价值用户怎么定义的 | Wiki 检索 |
| 营销策略推荐 | 给流失预警用户推荐召回方案 | SOP + 营销手册检索 |
| 人群对比（受限） | 高客单用户和普通用户的偏好差异 | 多路检索 + SQL 对比 |
| 地域/年龄分布洞察 | 母婴偏好用户在哪些城市集中 | 画像检索 + LLM 归纳 |

### 2. 销售 / 客服侧

| 业务需求 | 示例问法 | 依赖能力 |
|---|---|---|
| 客服话术推荐 | 用户投诉物流延迟怎么回复 | cs_sop.md 检索 |
| SOP 查询 | 退换货流程是什么 | SOP 检索 |
| 客户速览（受限） | U2765 是什么用户 | 单用户画像检索 |
| 会员权益咨询 | 钻石会员有什么权益 | Wiki 检索 |
| 优惠券问题处理 | 用户说优惠券过期了怎么办 | SOP 检索 |

### 3. 数据分析师 / 产品侧

| 业务需求 | 示例问法 | 依赖能力 |
|---|---|---|
| 标签使用查询 | 哪些标签跟美妆相关 | 标签库检索 |
| 分群策略检索 | 高价值沉默客怎么运营 | segmentation.md 检索 |
| 报告模板查询 | 用户分析报告有哪些板块 | 模板检索 |
| 品类偏好分析 | 美妆用户的客单价分布 | 画像检索 + SQL 归纳 |

### 4. 管理层

| 业务需求 | 示例问法 | 依赖能力 |
|---|---|---|
| 经营快问快答 | 本周高价值用户规模有多少 | 画像聚合（SQL 计数） |
| 业务规则查询 | 流失预警的判定标准 | 标签库检索 |
