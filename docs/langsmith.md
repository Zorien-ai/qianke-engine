# LangSmith 接入

当前项目使用 LangChain / LangGraph，LangSmith tracing 走官方自动集成。

## 1. 填 API Key

编辑项目根目录 `.env`：

```bash
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxx
LANGSMITH_PROJECT=qianke-agent
```

要求：

- key 以 `lsv2_pt_` 开头
- 不要提交 `.env`
- 不要把 key 作为命令行参数传给 `langsmith` CLI

`src/rag_demo/config.py` 会读取 `.env`，并且只在 `LANGSMITH_API_KEY` 非空时自动打开 tracing。

## 2. 重启服务

```bash
uv run uvicorn rag_demo.api.main:app --reload
```

重启后，一次 Agent 运行会自动产生：

```text
agent graph
├── chatbot (chain)
│   └── ChatOpenAI (llm)
├── tools (chain)
│   └── execute_sql / rag_search / calculator (tool)
└── 最终回答
```

## 3. 验证

如果已安装 LangSmith CLI：

```bash
langsmith project list
langsmith trace list --project qianke-agent --limit 5
```

如果没有 CLI，也可以直接在 https://smith.langchain.com 的 `qianke-agent` 项目里查看。

## 4. 当前自定义 trace 的关系

本项目的 `TraceCallbackHandler` 仍然保留：

```text
request_id
execution_id
parent_execution_id
event_trace
```

它负责把执行身份和轻量事件带回 API / Eval；LangSmith 负责完整的 LLM / Tool IO 与服务端 trace。

## 5. 安全

- `.env` 已被 `.gitignore`
- API Key 只从环境变量读取
- 不在代码、日志、CLI 参数里写 key
- 生产环境建议通过容器 secret / 系统环境变量注入
