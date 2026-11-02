# 企业微信内审批命令

> 日期：2026-11-02 · 状态：真实回调 + 真实执行 E2E 通过

## 1. 命令

```text
同意 <工作项短码> 仅退款
同意 <工作项短码> 退货退款
同意 <工作项短码> 发货 <运单号> [承运商]
同意 <工作项短码>
驳回 <工作项短码>
```

短码是 WorkItem ID 最后 6 位，例如：

```text
work_item: saw_2d0daccfa27f4e9d
短码:      7f4e9d
命令:      同意 7f4e9d 仅退款
```

## 2. 权限

```text
必须是企业微信签名回调
只接受该 WorkItem 的发起人 from_user
或在 QIANKE_WECOM_APPROVERS 白名单内
```

不允许：

```text
其他企业微信用户审批
通过模糊自然语言触发写操作
```

## 3. 动作参数

```text
CREATE_AFTER_SALE → 必须带 仅退款 / 退货退款
SHIP_ORDER       → 必须带运单号
CANCEL_ORDER / COMPLETE_ORDER → 无额外参数
```

## 4. 流程

```text
企业微信发命令
→ 验签/AES 解密
→ 命令解析
→ 权限校验
→ update_approval_action
→ decide_approval（EXECUTING）
→ ACTION Job 入队
→ 执行
→ 企业微信应用消息回写结果
```

## 5. 真实 E2E

准备：

```text
work_item: saw_2d0daccfa27f4e9d
order:     order_0155bacf59b34763
short:     7f4e9d
command:   同意 7f4e9d 仅退款
```

企业微信回调：

```text
200 success
```

执行结果：

```text
status: DONE
execution_status: EXECUTED
ticket: as_82a649fe6ecc48e2
type: REFUND_ONLY
ACTION Job: saj_5712d81f38c94b84 / DONE
```

企业微信应用结果回写：

```text
企业微信应用结果回写成功
```

## 6. 安全

```text
命令文本精确匹配，不解析模糊自然语言
发起人/授权人校验
重复命令：WorkItem 已不是 WAITING_APPROVAL → 拒绝执行
驳回不执行
执行仍走白名单 Action 执行器
所有审批记录 note = "企业微信审批 by <from_user>"
```

## 7. 测试

```bash
pytest tests/test_superagent_wecom_approval.py -q
# 4 passed
```

覆盖：

```text
命令解析
售后参数
越权拒绝
驳回
```

## 8. 已知限制

```text
只支持文本命令
短码匹配限制在最近 200 个工作项
短码重复时需要发完整 WorkItem ID
审批人白名单目前是环境变量，没有管理页面
消息重试去重仍是进程内 MsgId 集合
```
