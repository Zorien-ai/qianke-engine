# B 端用户画像卡片网格

日期：2026-11-14

## 结构

```text
.b-profile-grid：桌面 auto-fill minmax(420px, 1fr)；手机单列
每张画像独立卡片：
  买家标识 / 商家 / 会话用户 / 置信度
  标签（来自 needs + preferences 去重）
  目标与需求
  偏好
  顾虑与边界
  当前阶段
  待确认问题
  基本属性（budget / sizes，存在才渲染）
  版本 / 来源消息 / 更新时间
  展开 JSON
```

## 字段规则

```text
仅使用 profile.profile 已有字段
缺失字段不渲染；不编造姓名、角色、痛点、行为
needs/preferences 同时用于标签
长文本 JS 截断 + CSS line-clamp / ellipsis
```

## 验证

```text
桌面 1440：2 列候选，单卡片宽 569px
手机 390：单列，卡片宽 347px
无横向溢出
当前真实画像 1 条；标签 5 个；结构化区块 5 组
```

## 截图

```text
docs/design/b-end-profile-cards.png
docs/design/b-end-profile-cards-mobile.png
```
