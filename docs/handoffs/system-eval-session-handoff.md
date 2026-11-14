# 系统 / 测评会话 Handoff（当前会话）

日期：2026-11-14  
职责：系统测试、Agent Eval、UI 验收协调、服务健康、发布与 PR 收口。  
不承接 C 端或 B/企业端功能编码；编码分别在 C 端会话、B/企业端会话。

## 系统基线

```text
分支：b-end-2.0-p0
提交：0f6c0ac
工作区：有未提交改动（其他 agent 的 B/企业端、AGENTS、docs 等），先 git status/diff
local  /ready：200
public /ready：200
cloudflared：运行中
```

## 测试基线（本轮实测）

```text
pytest tests/ -q
  → 823 passed, 6 skipped, 1 warning
  日志：var/system_baseline_pytest.log

Agent Regression Eval
  → 20/20 PASS
  → Task Success 100.0% / Business 100.0% / Tool Policy 100.0%
  → Tool Selection 100.0% / Tool Execution 100.0%
  → 平均 Steps 2.25 / Tool Calls 1.65 / 3.8s
  结果：tests/evals/agent/results/system_baseline_regression.json
  报告：tests/evals/agent/reports/system_baseline_regression.md

说明：Eval 运行期间 LangSmith 429 tracing 限额告警，不影响上述本地判分结果；
不能把 429 当作 Eval 失败，也不能删除 tracing 日志。
```

## 当前 UI 验收状态

```text
#2 Landing CSS/Canvas/shaders/Bloom 渐变：Codex 已在 0f6c0ac 关闭
#5 CApp/Chat IME：合成事件通过；原生中文输入法待真实设备补证
#1 B/企业端渐变/占位：仍阻断
#3 B/企业端桌面侧栏：仍阻断
#4 智能助理/账单/离线评测窄屏：仍阻断
整体验收：未通过
```

## 本会话职责

```text
1. 维护系统基线：pytest / Agent Regression / 必要 Eval
2. UI 验收协调：Pachat、Codex 复验、PR 反馈
3. 服务健康：PostgreSQL / API / cloudflared / public 访问
4. 发布收口：PR 合并、提交号、可访问版本、验收证据
5. 只做测试/验收基础设施；不改 C/B 功能代码
```

## 常用命令

```bash
# 全量测试
.venv/Scripts/python.exe -m pytest tests/ -q

# Agent Regression Eval
.venv/Scripts/python.exe tests/evals/agent/runner.py \
  --suite regression \
  --out tests/evals/agent/results/<name>.json \
  --report tests/evals/agent/reports/<name>.md

# 前端构建
cd web && npm run build

# 服务健康
curl http://127.0.0.1:8000/ready
curl https://qianke.qiankeagent.com/ready
```

可用的其他 Eval：

```text
scripts/run_eval.py                 RAG/SQL + LLM-as-Judge 离线评测
scripts/superagent_eval_v2.py       Super-agent 场景 Eval（需 API/DB/LLM）
scripts/c_persona_eval.py           C 端伙伴人设 Eval
tests/evals/agent/runner.py         Agent regression / benchmark
```

Eval 前确认 API/DB/模型可用；Eval 结果必须附原始结果和报告路径，不能只报一个百分比。

## 与其他两个会话的边界

```text
C 端编码会话：
  docs/handoffs/c-end-session-handoff.md
  C 端页面、CApp/CShop/CSocial/CMe、C 端 API/测试

B/企业端编码会话：
  docs/handoffs/b-enterprise-session-handoff.md
  B 工作台、企业端外壳、侧栏、Billing/AgentDemo/离线评测、#1/#3/#4

本会话：
  Pachat 定时任务、Codex 复验、测试/Eval、发布与系统健康
```

## 安全与协作

```text
不要泄露 token、配对码、主人隐私
不要 reset / checkout 丢弃其他 agent 的未提交改动
涉及写入/删除的 Eval 必须使用隔离环境，不能写生产业务数据
Pachat 只保留本会话一个检查入口，避免重复回复
```

## 下一步

```text
1. 收到 C/B 新会话的 commit 后，先跑对应 pytest + build
2. 将 commit 交给 Codex 复验，按 #1/#3/#4/#5 分项收口
3. #5 需要主人真实输入法手测，不能由 Playwright 合成事件替代
4. 所有通过项附 commit、URL、截图、原始测试/Eval 文件
```
