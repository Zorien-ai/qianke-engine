# 凭据轮换记录

> 日期：2026-11-09 · 状态：完成并验证

## 背景

2026-11-05 密钥审计发现：

```text
RAG_ADMIN_PASSWORD            默认
RAG_PG_PASSWORD               默认
RAG_SQL_READONLY_PASSWORD     默认
RAG_ENABLE_API_DOCS           开启
```

用户确认在维护窗口轮换全部。

## 执行

```text
1. 停 API / Worker
2. 备份 .env → var/env-backup-before-rotation-*.env
3. 轮换 postgres / sql_reader 角色密码
4. 更新 .env：PG / auth / readonly / admin / docs
5. 更新管理员 password_hash，删除其全部 session
6. 重启 API / Worker / cloudflared
7. 启动观察脚本
```

## 验证

```text
新管理员登录 → 200
旧默认密码   → 401
/docs        → 404
readonly     → SELECT 1 OK
本地 /ready  → 200
外部 /ready  → 200
密钥检查     → OVERALL PASS
```

## 故障与恢复

第一次轮换脚本在角色密码改完后、连接 `rag_auth` 时仍用旧密码，导致失败。已通过容器内本地 socket 重置角色密码恢复。

根因修复：

```text
auth._current_pg_config() 延迟到连接池创建时读环境变量
auth._ensure_database()   使用动态配置
```

## 回滚

```text
旧 .env 备份：var/env-backup-before-rotation-*.env
旧角色密码仅在该备份中
回滚时先恢复 .env，再用容器内 psql 重置角色密码，最后重启 API/Worker
```

## 未完成

```text
管理员新密码需要用户登录后自行改成个人密码
凭据文件 var/credential-rotation-final.txt 使用后删除
```

## 观察

轮换前连续观察在 2026-11-05 18:02 因运行环境中断；恢复后已重新启动：

```text
logs/control_pg_observation_post_recovery.jsonl
```
