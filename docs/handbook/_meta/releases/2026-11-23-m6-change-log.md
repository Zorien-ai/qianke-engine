# M6 增量变更记录（2026-11-23）

> 基线：M5 发布候选冻结  
> 规则：每条变更记录文件、原因、验证和 SHA256 变化  
> 说明：SHA256 用于证明增量变更相对于冻结 manifest 的具体范围

## 1. 变更范围

### M6.1 内容一致性

| 文件 | 冻结 SHA256 前 12 位 | 当前 SHA256 前 12 位 | 原因 |
|---|---|---|---|
| `docs/handbook/01-agent-architecture/02-agent-vs-enterprise-agent.md` | `cab63b79a562` | `36c2848da235` | 限定 HITL 为 B 端主链路，补充 C 端/ Super-agent 状态 |
| `docs/handbook/01-agent-architecture/09-agent-tool-calling.md` | `94299a0caf87` | `3f67cb909b0e` | 明确“独立 Prompt Injection 运行时防护” |
| `docs/handbook/02-enterprise-governance/05-tool-gateway-security.md` | `21cf06249cfe` | `ff90728f6f68` | 参数校验覆盖、SQL merchant_id、写路径三类 |
| `docs/handbook/02-enterprise-governance/06-human-in-the-loop.md` | `d85814586d63` | `ee21eb1812c8` | HITL 从两条链路改为三条 |

### M6.2 文档工程化

| 文件 | 状态 | 原因 |
|---|---|---|
| `docs-site/scripts/check-content.mjs` | 新增 | 60 篇/结构/状态/链接/产物检查 |
| `.github/workflows/handbook-docs.yml` | 新增 | 构建 + content check CI |

## 2. 验证

```text
docs-site build              exit 0
content check                60 articles, 0 errors, 1 warning
公开路由                     60/60 本地 200、公网 200
```

## 3. 未变范围

```text
- 其余 56 篇正文未修改；
- 未全量清理 P2；
- 未执行全量 pytest/Eval/生产验收；
- GitHub Actions 尚未远端运行。
```

## 4. 回滚

```text
内容回滚：按冻结 manifest 对应文件 SHA256 恢复；
工程化回滚：删除新增 script/workflow 即可，不影响现有部署；
不影响 V0.5.1 历史文件和 M5 冻结记录。
```
