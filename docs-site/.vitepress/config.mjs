import { defineConfig } from "vitepress";
import { fileURLToPath } from "node:url";

const sections = [
  {
    text: "01 · Agent Architecture",
    items: [
      { text: "分类导读", link: "/agent-architecture/" },
      { text: "1. 企业级 Agent 架构设计", link: "/agent-architecture/01-enterprise-agent-architecture-v0.5.2" },
      { text: "2. 普通 Agent 与企业级 Agent", link: "/agent-architecture/02-agent-vs-enterprise-agent" },
      { text: "3. Agent Runtime", link: "/agent-architecture/03-agent-runtime" },
      { text: "4. Agent Orchestrator", link: "/agent-architecture/04-agent-orchestrator" },
      { text: "5. Multi-Agent 协作", link: "/agent-architecture/05-multi-agent-collaboration" },
      { text: "6. Agent State", link: "/agent-architecture/06-agent-state-management" },
      { text: "7. Agent Memory", link: "/agent-architecture/07-agent-memory" },
      { text: "8. 任务生命周期", link: "/agent-architecture/08-task-lifecycle-management" },
      { text: "9. 工具调用机制", link: "/agent-architecture/09-agent-tool-calling" },
      { text: "10. 执行与异常处理", link: "/agent-architecture/10-agent-execution-reliability" }
    ]
  },
  {
    text: "02 · Enterprise Governance",
    items: [
      { text: "分类导读", link: "/enterprise-governance/" },
      { text: "1. 身份认证与权限", link: "/enterprise-governance/01-identity-and-access-management" },
      { text: "2. RBAC 与 ABAC", link: "/enterprise-governance/02-rbac-abac" },
      { text: "3. 多租户隔离", link: "/enterprise-governance/03-multi-tenancy-isolation" },
      { text: "4. Agent 权限治理", link: "/enterprise-governance/04-agent-permission-governance" },
      { text: "5. Tool Gateway 安全", link: "/enterprise-governance/05-tool-gateway-security" },
      { text: "6. Human-in-the-loop", link: "/enterprise-governance/06-human-in-the-loop" },
      { text: "7. Prompt Injection 防护", link: "/enterprise-governance/07-prompt-injection-defense" },
      { text: "8. 数据隐私与脱敏", link: "/enterprise-governance/08-data-privacy-redaction" },
      { text: "9. 操作审计与追踪", link: "/enterprise-governance/09-operation-audit-tracing" },
      { text: "10. 企业级安全体系", link: "/enterprise-governance/10-enterprise-security-architecture" }
    ]
  },
  {
    text: "03 · System Architecture",
    items: [
      { text: "分类导读", link: "/system-architecture/" },
      { text: "1. 企业级系统设计方法", link: "/system-architecture/01-enterprise-system-design" },
      { text: "2. 单体与微服务", link: "/system-architecture/02-modular-monolith-vs-microservices" },
      { text: "3. API Gateway", link: "/system-architecture/03-api-gateway" },
      { text: "4. 服务间通信", link: "/system-architecture/04-service-communication" },
      { text: "5. 消息队列与事件驱动", link: "/system-architecture/05-message-queue-event-driven" },
      { text: "6. 分布式任务调度", link: "/system-architecture/06-distributed-task-scheduling" },
      { text: "7. 数据库架构", link: "/system-architecture/07-database-architecture" },
      { text: "8. 缓存系统", link: "/system-architecture/08-cache-system-design" },
      { text: "9. 分布式事务与一致性", link: "/system-architecture/09-distributed-transactions-consistency" },
      { text: "10. 系统扩展性", link: "/system-architecture/10-system-scalability" }
    ]
  },
  {
    text: "04 · Data & Knowledge",
    items: [
      { text: "分类导读", link: "/data-knowledge/" },
      { text: "1. RAG 系统架构", link: "/data-knowledge/01-rag-architecture" },
      { text: "2. 向量数据库", link: "/data-knowledge/02-vector-database" },
      { text: "3. 混合检索与重排序", link: "/data-knowledge/03-hybrid-retrieval-reranking" },
      { text: "4. Knowledge Graph", link: "/data-knowledge/04-knowledge-graph" },
      { text: "5. 企业数据治理", link: "/data-knowledge/05-enterprise-data-governance" },
      { text: "6. 数据接入与 ETL", link: "/data-knowledge/06-data-ingestion-etl" },
      { text: "7. OLTP 与 OLAP", link: "/data-knowledge/07-oltp-olap" },
      { text: "8. 指标语义层", link: "/data-knowledge/08-metric-semantic-layer" },
      { text: "9. 数据血缘与质量", link: "/data-knowledge/09-data-lineage-quality" },
      { text: "10. 企业级知识库", link: "/data-knowledge/10-enterprise-knowledge-base" }
    ]
  },
  {
    text: "05 · Reliability & Evaluation",
    items: [
      { text: "分类导读", link: "/reliability-evaluation/" },
      { text: "1. Agent Evaluation", link: "/reliability-evaluation/01-agent-evaluation" },
      { text: "2. Agent 自动化测试", link: "/reliability-evaluation/02-agent-automated-testing" },
      { text: "3. Regression Test", link: "/reliability-evaluation/03-agent-regression-test" },
      { text: "4. Benchmark", link: "/reliability-evaluation/04-agent-benchmark" },
      { text: "5. Agent Observability", link: "/reliability-evaluation/05-agent-observability" },
      { text: "6. 日志、指标与链路追踪", link: "/reliability-evaluation/06-logs-metrics-tracing" },
      { text: "7. SRE 与 SLO", link: "/reliability-evaluation/07-sre-slo" },
      { text: "8. 重试、熔断与降级", link: "/reliability-evaluation/08-retry-circuit-breaker-degradation" },
      { text: "9. 故障恢复与灾备", link: "/reliability-evaluation/09-failure-recovery-dr" },
      { text: "10. CI/CD 与灰度发布", link: "/reliability-evaluation/10-cicd-canary-release" }
    ]
  },
  {
    text: "06 · Architecture Practice",
    items: [
      { text: "分类导读", link: "/architecture-practice/" },
      { text: "1. 需求分析", link: "/architecture-practice/01-requirements-analysis" },
      { text: "2. 架构设计方法", link: "/architecture-practice/02-architecture-design-method" },
      { text: "3. 模块拆分", link: "/architecture-practice/03-module-decomposition" },
      { text: "4. 模块依赖", link: "/architecture-practice/04-module-dependencies" },
      { text: "5. 技术选型", link: "/architecture-practice/05-technology-selection" },
      { text: "6. ADR 决策记录", link: "/architecture-practice/06-architecture-decision-records" },
      { text: "7. 架构评审", link: "/architecture-practice/07-architecture-review" },
      { text: "8. 性能分析", link: "/architecture-practice/08-performance-analysis" },
      { text: "9. 技术债务治理", link: "/architecture-practice/09-technical-debt" },
      { text: "10. 企业架构案例", link: "/architecture-practice/10-enterprise-architecture-case" }
    ]
  }
];

export default defineConfig({
  vite: {
    resolve: {
      alias: [
        { find: "vue/server-renderer", replacement: fileURLToPath(new URL("../node_modules/vue/server-renderer", import.meta.url)) },
        { find: "vue", replacement: fileURLToPath(new URL("../node_modules/vue", import.meta.url)) }
      ]
    }
  },
  base: "/docs/",
  srcDir: "../docs/handbook",
  srcExclude: [
    "_meta/**",
    "README.md",
    "01-agent-architecture/01-enterprise-agent-architecture.md",
    "01-agent-architecture/01-enterprise-agent-architecture-v0.2.md",
    "01-agent-architecture/01-enterprise-agent-architecture-v0.3.md",
    "01-agent-architecture/01-enterprise-agent-architecture-v0.4.md",
    "01-agent-architecture/01-enterprise-agent-architecture-v0.5.md",
    "01-agent-architecture/01-enterprise-agent-architecture-v0.5.1.md"
  ],
  cleanUrls: true,
  title: "Qianke Engine Architecture Handbook",
  description: "企业级 Agent 与系统架构手册：Runtime、治理、系统设计、数据、可靠性与架构实践。",
  lang: "zh-CN",
  lastUpdated: true,
  head: [
    ["meta", { name: "theme-color", content: "#F7F7F5" }],
    ["meta", { property: "og:type", content: "website" }],
    ["meta", { property: "og:title", content: "Qianke Engine Architecture Handbook" }],
    ["meta", { property: "og:description", content: "企业级 Agent 与系统架构手册" }]
  ],
  rewrites: {
    "01-agent-architecture/index": "agent-architecture/index",
    "02-enterprise-governance/index": "enterprise-governance/index",
    "03-system-architecture/index": "system-architecture/index",
    "04-data-knowledge/index": "data-knowledge/index",
    "05-reliability-evaluation/index": "reliability-evaluation/index",
    "06-architecture-practice/index": "architecture-practice/index",
    "01-agent-architecture/:slug": "agent-architecture/:slug",
    "02-enterprise-governance/:slug": "enterprise-governance/:slug",
    "03-system-architecture/:slug": "system-architecture/:slug",
    "04-data-knowledge/:slug": "data-knowledge/:slug",
    "05-reliability-evaluation/:slug": "reliability-evaluation/:slug",
    "06-architecture-practice/:slug": "architecture-practice/:slug"
  },
  themeConfig: {
    logo: "/logo.png",
    siteTitle: "Qianke Architecture Handbook",
    nav: [
      { text: "官网", link: "https://qianke.qiankeagent.com/" },
      { text: "Agent Architecture", link: "/agent-architecture/01-enterprise-agent-architecture-v0.5.2" },
      { text: "GitHub", link: "https://github.com/Zorien-ai/qianke-engine" }
    ],
    sidebar: sections,
    outline: { level: [2, 3], label: "本页目录" },
    search: { provider: "local" },
    docFooter: { prev: "上一篇", next: "下一篇" },
    lastUpdatedText: "最后更新",
    returnToTopLabel: "回到顶部",
    sidebarMenuLabel: "目录",
    darkModeSwitchLabel: "主题",
    lightModeSwitchTitle: "切换到浅色",
    darkModeSwitchTitle: "切换到深色",
    socialLinks: [{ icon: "github", link: "https://github.com/Zorien-ai/qianke-engine" }],
    footer: {
      message: "以代码、测试和运行证据为准。规划能力不会写成已实现。",
      copyright: "© 2026 Qianke Engine · Apache-2.0"
    }
  }
});
