# M5 全站一致性检查与最终质量验收报告（2026-11-23）

> 验收对象：Qianke Engine Architecture Handbook 60 篇公开文章  
> 质量基线：`docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md`  
> 公开地址：https://qianke.qiankeagent.com/docs/  
> 审计边界：本轮完成 M1–M4 的内容修复与一致性收口；不等于全量 pytest、全量 Eval、生产 SLO 或 60 页浏览器交互验收

## 1. 最终结论

**条件通过，可作为发布候选。**

```text
P0：0
P1：22/22 已修复并复核
M4 高优先 P2：已收口
剩余 P2：仍有，未全量清零
完整生产验收：未完成
```

结论含义：

- 22 个 P1 已按任务清单修复，并有代码/文档证据；
- M3 六分类复核完成；
- M4 高优先 P2 已修复；
- 剩余 P2 不影响本轮 P1 验收，但不宣称“全站内容零问题”；
- 不能把本报告等同于完整生产发布验收。

## 2. M1–M4 结果

| 阶段 | 结果 | 产物 |
|---|---|---|
| M1 修正基线 | V0.5.2 已发布；V0.5.1 保留且不进入公开站 | [V0.5.2](<../01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md>) |
| M2 修复 22 个 P1 | 22/22 完成 | [P1 任务清单](2026-11-23-p1-fix-tasks.md) |
| M3 批次复核 | 6 个分类复核报告完成 | [M3 汇总](remediation-2026-11-23/README.md) |
| M4 高优先 P2 | 高优先 P2 已收口 | [P2 修复记录](2026-11-23-p2-remediation.md) |

## 3. 关键修复

```text
错误码：READ_ONLY_VIOLATION → SQL_VALIDATION_ERROR
retry：函数默认 1 / API 默认 0 / 上限 3
状态：RUNNING 移出终态
多租户：隔离强度改为“部分实现”
事务：跨存储非原子，两个仓储、两个提交点
连接池：控制面/商家仓储已实现，数据集层未做池
控制面表数：28 → 63
WebSocket：补全 /api/c/ws 前缀，披露 Nginx Upgrade 缺口
CI/Eval：v2 门禁未接入 CI；frozen 分支未实现；私有 holdout 已实现
数据：上下文脱敏边界收紧；ETL 围栏修复
实践：M0 ACCEPTED；旧行数改为当前总行数
```

## 4. 验证结果

### 4.1 构建与路由

```text
docs-site npm run build       exit 0
dead link                     无
公开文章                       60/60
本地 /docs 路由               60/60 HTTP 200
公网 /docs 路由               60/60 HTTP 200
V0.5.1 历史文件               保留
V0.5.2 旧错误码              0
```

### 4.2 内容结构

```text
frontmatter 必填字段          60/60 存在
公开文章数                    6 分类 × 10 = 60
V0.5.1 公开路由               已由 srcExclude 排除
V0.5.2 公开入口               200
```

### 4.3 测试

```text
python -m pytest tests/test_agent_execution_safety.py tests/test_agent_checkpoint.py tests/test_agent_architecture.py -q
结果：34 passed, 1 warning
Git HEAD：32ad31bc2636
```

### 4.4 浏览器

```text
Mermaid 图渲染                已验证
搜索                          已验证有结果
移动端 390px                  无整页横向滚动
Chrome DevTools                console error 0；资源请求 200
```

## 5. 剩余问题

### 5.1 未全量清除的 P2

```text
- HITL 状态在不同文章中的口径仍有差异
- Prompt Injection / Tool Gateway 状态表述仍有跨篇差异
- Data 多租户“物理分库已实现”与 Enterprise “部分实现”的措辞差异
- docs/agent.md 等历史内部文档仍存在旧错误码/旧 Tool 数量描述
- 部分外部链接未逐一访问
```

### 5.2 未执行的验收

```text
- 全量 pytest（700+）
- Regression / Benchmark / 真实 LLM Eval
- 生产并发、SLO、成本看板
- 60 页逐页浏览器交互
- 生产 PostgreSQL、企业微信真实投递、备份恢复实测
- 外部链接自动死链检查
```

## 6. 发布建议

```text
可以继续作为公开文档站发布；
不能宣称“全站内容已完整验收”；
后续按 P2 清单继续迭代，不再批量生成新文章。
```

## 7. 边界声明

本报告记录的是本轮实际执行的构建、路由、测试和浏览器检查结果。  
未执行的测试/Eval/生产验收均明确标为“未执行”，不以审计推断替代运行证据。
