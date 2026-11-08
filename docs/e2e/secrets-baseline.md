# 密钥基线与轮换

> 日期：2026-11-09 · 状态：**已通过**（默认凭据已轮换，API docs 已关闭）

## 检查命令

```bash
python scripts/security_secrets_check.py
python scripts/security_secrets_check.py --json
```

脚本只输出 `set / len / weak`，不打印密钥值。

## 当前结果

```text
PASS RAG_ADMIN_PASSWORD        已改为随机强密码
PASS RAG_PG_PASSWORD           已改为随机强密码
PASS RAG_SQL_READONLY_PASSWORD 已改为随机强密码
PASS RAG_AUTH_ENABLED
PASS RAG_ALLOW_HEADER_AUTH     未允许自报身份
PASS RAG_ENABLE_API_DOCS       已关闭
PASS .env_not_tracked          .env 未入库
OVERALL PASS
```

## 已执行的轮换

```text
1. postgres / sql_reader 角色密码
2. .env 中 RAG_PG_PASSWORD / RAG_AUTH_PG_PASSWORD /
   RAG_SQL_READONLY_PASSWORD / RAG_ADMIN_PASSWORD
3. 管理员密码哈希 + 删除该账号全部 session
4. RAG_ENABLE_API_DOCS=0
5. 重启 API / Worker / cloudflared
```

验证：

```text
新管理员密码登录 → 200
旧默认密码登录   → 401
/docs            → 404
readonly 连接    → SELECT 1 OK
/ready           → 200
外部域名 /ready   → 200
```

## 凭据文件

新凭据只保存在本机：

```text
var/credential-rotation-final.txt
```

请登录后立即改成自己的密码，然后删除该文件与 `var/credential-recovery-pg.txt`。

## 事故与修复（2026-11-09）

轮换脚本在改完 PG 角色密码后、连接 auth 库时用了旧密码，导致脚本失败；随后通过容器内本地 socket 重置 `postgres` / `sql_reader` 密码并恢复。

同时修复了根因：

```text
auth.py 在 config 加载 .env 前缓存 PG 密码
→ _current_pg_config() 延迟读取
→ _ensure_database() 改用动态配置
→ auth 不再依赖启动命令显式注入密码
```

## 说明

```text
未把任何密码写入 Git 或文档
.env 仍在 .gitignore 中
轮换后的管理员新密码请尽快改成个人密码
```
