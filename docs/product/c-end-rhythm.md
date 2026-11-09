# C 端关系节奏（P2-A）

> 日期：2026-11-09 · 状态：已实现 · 范围：仅 C 端站内消息；不接 Push / 短信 / 邮件

## 目标

在不打扰、不推销的前提下，让伙伴有一点连续感：

```text
默认关闭，用户显式开启
只在用户打开 C App 时检查
购后回访、长期未活跃回归
免打扰、频率上限、暂停一周
无商品推荐、无优惠券、无催单
```

## 数据模型

```text
c_companion_rhythm
  owner_id / enabled / timezone
  quiet_start / quiet_end
  last_active_at / last_checkin_at / pause_until
  unanswered_count

c_companion_checkin
  checkin_id / owner_id / kind
  ref_id / content / due_at
  delivered_at / status
```

SQLite 与 PostgreSQL 双 schema 已同步。

## 规则

```text
默认 enabled=0
开启后才可能投递
免打扰默认 22:00–09:00
每天最多 1 条，每周最多 3 条
暂停一周
订单确认后 48h 生成一次购后回访，一单一回
超过 14 天未投递的回访自动 SKIPPED
连续 14 天无活跃才生成一次回归问候
订单已取消/状态不对 -> 回访 SKIPPED
```

## 投递方式

```text
POST /api/c/companion/checkin
```

C App 打开时调用一次；后端领取到期回访并写入 `c_app_message`。

这不是推送：用户没打开 App 就不会产生任何外部通知。

## API

```text
GET   /api/c/companion/rhythm
PATCH /api/c/companion/rhythm
POST  /api/c/companion/checkin
```

`PATCH` 支持：

```json
{"enabled": true}
{"enabled": true, "quiet_start": "22:00", "quiet_end": "09:00"}
{"pause_hours": 168}
```

## UI

右侧上下文面板新增「关系节奏」：

```text
[ ] 允许小鱼偶尔主动问候
仅站内消息，不免打扰 22:00–09:00；每天最多 1 条，每周最多 3 条。
暂停一周
```

截图：

![关系节奏](c-end-rhythm.png)

## 验证

```text
694 passed, 5 skipped
```

引擎测试覆盖：

```text
默认关闭
开启后购后回访只投递一次
免打扰时间阻止投递
暂停阻止投递
免打扰时间格式校验
```

真实 API：

```text
GET  rhythm -> enabled=False, 22:00–09:00
PATCH enabled=True -> True
POST checkin -> {"checkin": null}（无到期回访）
PATCH pause_hours=168 -> pause_until 有值
PATCH enabled=False -> False
```

浏览器：

```text
C App -> 小鱼 -> 关系节奏
点击开关 -> 显示「已开启」
无 console error
```

## 已知限制

- 只有站内回访，没有真正的 Push / IM 外呼。
- 免打扰时间后端可配置，但当前 UI 只展示默认时间，未提供时间编辑控件。
- `unanswered_count` 已预留，但“连续未回复自动停”尚未接入回复统计；当前靠频率上限和暂停兜底。
- 购后回访只基于订单确认时间，不检查物流签收；后续可接订单状态。
- 不做营销触达，避免陪伴变成销售漏斗。
