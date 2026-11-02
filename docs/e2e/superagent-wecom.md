# 企业微信原生回调接入 Super-agent

> 日期：2026-11-02 · 状态：真实 HTTP + 合成加密消息 E2E 通过

## 1. 能力

```text
企业微信应用回调
→ 验签
→ AES 解密
→ XML 解析
→ MsgId 去重
→ Super-agent Trigger
→ Router / Worker
```

不再依赖通用 Webhook 或中转服务。

## 2. 配置

企业微信管理后台 → 应用 → 接收消息：

```text
URL: https://<公网域名>/api/superagent/wecom/callback
Token: <企业微信后台 Token>
EncodingAESKey: <企业微信后台 EncodingAESKey>
企业 ID: <corpId>
```

`.env`：

```dotenv
QIANKE_WECOM_TOKEN=<token>
QIANKE_WECOM_AES_KEY=<encoding-aes-key>
QIANKE_WECOM_CORP_ID=<corpId>
```

`QIANKE_SUPERAGENT_AUTO_TRIGGER=1` 时，文本消息会自动进入 Router。

## 3. 协议

```text
GET  /api/superagent/wecom/callback
     ?msg_signature=&timestamp=&nonce=&echostr=
     → 验签 + 解密 echostr，原样返回

POST /api/superagent/wecom/callback
     ?msg_signature=&timestamp=&nonce=
     body: <xml><Encrypt>...</Encrypt></xml>
     → 验签 + 解密 + 解析 + 去重 + 触发
     → "success"
```

签名：

```text
sha1(sort(token, timestamp, nonce, encrypt))
```

AES：

```text
Base64Decode(EncodingAESKey + "=")
CBC / IV=key[:16]
明文 = random(16) + msg_len(4) + msg + receive_id
PKCS#7 block size 32
```

## 4. 真实 E2E

本地使用合成密钥 + 合成企业微信消息：

```text
GET  URL 验证 → 200 wecom-echo-123
POST 文本消息 → 200 success
POST 同一 MsgId → 200 success（去重，不重复建工作项）
```

生成：

```text
work_item: saw_d6eac56591e3435e
status: RUNNING
title: 订单 order_5695476eb1c8441e 买家要退款，麻烦处理售后
thread: wecom:user_e2e
```

说明：本地测试使用的是**协议层合成消息**，不是企业微信服务器真实投递；公网回调需要在企业微信后台配置真实 URL。

## 5. 安全

```text
先验签再解密
receive_id 校验 corpId
MsgId 去重，避免企业微信重试导致重复工作项
Token/AESKey 只从环境变量读取
不记录明文密钥
非文本消息忽略
```

## 6. 已知限制

```text
只支持企业微信应用「接收消息」回调，不是群机器人 Webhook
只处理文本消息；图片/文件/事件暂不进入 Super-agent
MsgId 去重是进程内内存，重启后去重集清空
公网 URL 必须 HTTPS 且企业微信服务器可达
本地回调测试是协议层合成，不是企业微信真实投递
```

## 7. 测试

```bash
pytest tests/test_superagent_wecom.py -q
# 6 passed
```

覆盖：

```text
签名通过/失败
AES 加密解密
错误 corpId 拒绝
文本消息解析
非文本消息忽略
环境变量读取
```
