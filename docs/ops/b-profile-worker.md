# B 端会话画像 worker 生产化

## 目标

每 60 秒扫描一次 C 买家 ↔ 商家店宠会话，30 分钟无新消息后抽取画像。

## 本地

```bash
python scripts/b_profile_worker.py --interval 60
```

单次：

```bash
python scripts/b_profile_extract.py
python scripts/b_profile_extract.py --owner buyer_112
```

日志：

```text
logs/b_profile_worker.log
```

## Linux systemd

复制：

```bash
sudo cp deploy/systemd/qianke-b-profile-worker.service /etc/systemd/system/
```

按实际路径修改：

```text
WorkingDirectory=/opt/qianke
ExecStart=/opt/qianke/.venv/bin/python scripts/b_profile_worker.py --interval 60
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now qianke-b-profile-worker
sudo journalctl -u qianke-b-profile-worker -f
```

## cron 替代

```cron
* * * * * cd /opt/qianke && .venv/bin/python scripts/b_profile_extract.py >> logs/b_profile_cron.log 2>&1
```

## 商家映射

店宠 friend_id 必须绑定真实商家，否则扫描器不会处理。

C 端买家入口：

```text
C 端 -> 消息 -> 好友 -> 发现店宠
```

管理端页面：

```text
/v2/#/admin/merchant-store-friends
```

API：

```text
GET  /api/c/admin/merchant-store-friends
POST /api/c/admin/merchant-store-friends
     {"merchant_id": "m_tea_001", "friend_id": "store_tea"}
```

只有系统管理员可以调用。

查看已生成画像：

```text
GET /api/b/workbench/chat-profiles
GET /api/c/admin/chat-profiles
```

## 失败处理

- 抽取失败：不写画像，不阻塞其它商家。
- embedding 失败：画像正文仍保存，语义搜索退回文本匹配。
- worker 单轮异常：记录日志后下一轮继续。
- LLM/模型不可用：跳过，不删除已有画像。
