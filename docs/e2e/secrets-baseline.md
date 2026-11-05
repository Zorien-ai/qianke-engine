# 密钥基线与轮换

> 日期：2026-11-05 · 状态：**未通过**，需要人工确认后轮换

## 检查命令

```bash
python scripts/security_secrets_check.py
python scripts/security_secrets_check.py --json
```

脚本只输出 `set / len / weak`，不打印密钥值。

## 当前结果

```text
FAIL RAG_ADMIN_PASSWORD       默认/弱口令
FAIL RAG_PG_PASSWORD          默认/弱口令
FAIL RAG_SQL_READONLY_PASSWORD 默认/弱口令
PASS RAG_AUTH_ENABLED
PASS RAG_ALLOW_HEADER_AUTH    未允许自报身份
FAIL RAG_ENABLE_API_DOCS      仍开启
PASS .env_not_tracked         .env 未入库
```

## 上线前必须处理

1. **管理员密码**
   - `RAG_ADMIN_PASSWORD` 只在首次创建管理员时使用；
   - 已有管理员需要走系统内改密流程，不能只改 `.env`；
   - 改完确认旧密码不能登录。

2. **PostgreSQL 应用密码**
   - `ALTER ROLE postgres PASSWORD '<new>'`；
   - 更新 `.env` 的 `RAG_PG_PASSWORD`；
   - 重启 API / Worker，确认 `/ready` 四项全绿。

3. **只读账号密码**
   - `ALTER ROLE sql_reader PASSWORD '<new>'`；
   - 更新 `.env` 的 `RAG_SQL_READONLY_PASSWORD`；
   - 跑一次 SQL Tool 读路径。

4. **关闭 API 文档**
   - `RAG_ENABLE_API_DOCS=0`；
   - 或仅在内网/鉴权网关后开放。

## 验收

```text
python scripts/security_secrets_check.py  → OVERALL PASS
python scripts/production_preflight.py    → OVERALL PASS
```

## 说明

```text
本次只做审计，未修改任何密码或 .env
凭据轮换属于高风险变更，需要用户确认后执行
```
