# 修改密码

> 日期：2026-11-09 · 状态：新增登录后改密接口

## 接口

```text
POST /auth/change-password
需要登录 Cookie
```

请求：

```json
{
  "current_password": "当前密码",
  "new_password": "至少 10 位的新密码"
}
```

成功：

```json
{"status": "ok", "message": "密码已修改，请重新登录"}
```

行为：

```text
校验当前密码
新密码至少 10 位
新旧密码不能相同
写入 Argon2id 哈希
删除该账号全部 session
清除当前 Cookie
```

演示账号返回 403。

## 页面\n\n登录后打开：\n\n```text\nhttps://qianke.qiankeagent.com/password\n```\n\n填写当前密码、新密码、确认新密码即可。\n\n## 浏览器控制台

登录后打开：

```text
https://qianke.qiankeagent.com/v2/
```

F12 Console 执行：

```js
await fetch('/auth/change-password', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    current_password: '当前密码',
    new_password: '你的新密码至少10位'
  })
}).then(r => r.json())
```

成功后页面会退出登录，用新密码重新登录。

## curl

```bash
curl -c cookies.txt -X POST https://qianke.qiankeagent.com/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"account":"admin","password":"当前密码"}'

curl -b cookies.txt -X POST https://qianke.qiankeagent.com/auth/change-password \
  -H 'Content-Type: application/json' \
  -d '{"current_password":"当前密码","new_password":"新密码至少10位"}'
```

## 测试

```text
tests/test_password_change.py
```

覆盖：

```text
错误旧密码
弱新密码
新旧相同
改密后旧会话失效
```

