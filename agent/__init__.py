"""千客引擎多智能体电商运营系统（LangGraph）。

本包只负责 Agent 编排与工具封装，不复制千客引擎的检索/ SQL 实现：
- `agent.tools`：把现有 FastAPI / RAG 能力封装成 LangChain Tool
- `agent.graph_smoke`：LangGraph 框架冒烟图（本阶段只验证框架与工具链路）
"""
