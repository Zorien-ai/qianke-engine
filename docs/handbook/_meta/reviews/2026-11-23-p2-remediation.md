# M4 高优先 P2 修复记录（2026-11-23）

> 前置：M1 V0.5.2 基线勘误、M2 22 个 P1、M3 六分类复核  
> 范围：审计主报告列出的高优先 P2，以及 M3 复核暴露的跨篇矛盾  
> 边界：不回写全部 115 个 P2；剩余 P2 保留在 M5 已知限制

## 1. 已修复项

| ID | 文件 | 修复内容 |
|---|---|---|
| M4-01 | `03-system-architecture/03-api-gateway.md` | `/docs` 与 `/openapi.json` 路由更新为 `/api/docs`、`/api/openapi.json`；补充 `/ready`；明确 `/docs` 是公开 Handbook |
| M4-02 | `06-architecture-practice/05-technology-selection.md` | VitePress 状态从“已选型/待核验”更新为“已构建、FastAPI `/docs` 已挂载、公网已访问” |
| M4-03 | `04-data-knowledge/06-data-ingestion-etl.md` | 修正“缓存键不含数据版本”，改为“缓存键已含数据版本，仍需显式清理” |
| M4-04 | `05-reliability-evaluation/06/07/09/10` | 生产预检统一为“10 项成功路径 + 1 个 PostgreSQL 异常兜底” |
| M4-05 | `05-reliability-evaluation/02/04`、`06-architecture-practice/10` | 测试文件计数统一为“顶层 126 个，含子目录 130 个” |
| M4-06 | `02-enterprise-governance/08-data-privacy-redaction.md` | 身份证脱敏示例改为真实输出 `110101********4`；删除“递归处理 list”错误表述 |
| M4-07 | `06-architecture-practice/10-enterprise-architecture-case.md` | “两套链路”改为三条链路；删除无出处的 1.0 时间线；2.1–2.29 改为 2.1–2.30 |
| M4-08 | `06-architecture-practice/06-architecture-decision-records.md` | “16 项待确认决策”改为 12 项；补 M0 closure 证据 |
| M4-09 | `03-system-architecture/07-database-architecture.md` | 连接池口径细化为 auth.py 1..8、control repository 1..4、merchant 1..8 |
| M4-10 | 多篇公开文章 | `V0.5.1` 旧引用统一改为 `V0.5.2`；保留 V0.5.1 历史文件 |
| M4-11 | `03-system-architecture/04-service-communication.md` | 通用 Webhook 从“HMAC 报文比较”改为“共享密钥头 + `hmac.compare_digest`” |
| M4-12 | `02-enterprise-governance/10-enterprise-security-architecture.md` | API 文档边界改为生产关闭 `/api/docs` 与 `/api/openapi.json`，`/docs` 为公开 Handbook |
| M4-13 | `README.md`、V0.5.2 注释 | 更新第一篇路径/状态；说明 V0.5.2 同时修正 retry 默认值表述 |

## 2. 验证

```text
docs-site npm run build       exit 0；无 dead link 报告
60 篇公开路由                本地 200；公网 200
V0.5.2 旧错误码             0
V0.5.1 历史文件              保留
V0.5.1 不再进入公开站        srcExclude 已排除
```

## 3. 未纳入项

```text
- 仍存在的 HITL 状态口径差异
- Prompt Injection / Tool Gateway 跨篇状态差异
- Data 多租户“物理分库已实现”与 Enterprise “部分实现”的措辞差异
- docs/agent.md 等旧内部文档的历史漂移
- 外部链接可达性
- 全量 pytest / Regression / Benchmark / 生产 SLO
```

这些属于剩余 P2 或未核验范围，不阻塞 22 个 P1 的修复验收，但不能据此宣称全站零问题。
