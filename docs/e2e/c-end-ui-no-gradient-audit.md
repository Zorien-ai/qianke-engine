# C 端 UI 验收：去渐变与 60:30:10

日期：2026-11-14

## 标准

```text
禁止 CSS 渐变（linear-gradient / radial-gradient / repeating-gradient）
60:30:10 色彩角色：
  60% 主背景/纸面
  30% 次级表面/边框/文字层级
  10% 强调色
删除重复标题、多余标语和无关标签
```

## 去渐变处理

| 页面 | 处理 |
|---|---|
| CHome | Hero radial-gradient → 纯色 surface |
| CApp | 商品缩略图 linear-gradient → 纯色 |
| CShop | 商品占位/详情艺术图 20+ 处渐变 → 纯色语义色 |
| CMe | Hero radial-gradient → 纯色；骨架 shimmer linear-gradient → 透明度 pulse |
| CSocial | 无渐变；删除“消息”重复标题，搜索框内移入添加按钮 |
| CLogin | 背景双 radial-gradient → 纯色 paper |
| Landing 官方站 | Hero/玻璃卡/按钮/遮罩/星空渐变全部改纯色（CSS 渐变 = 0） |

## 浏览器实测

登录 C 账号后逐页扫描全部元素及 `::before`/`::after` 的 `background-image`：

```text
/c/home    gradients = 0
/c         gradients = 0
/c/app     gradients = 0
/c/orders  gradients = 0
/c/social  gradients = 0
/c/me      gradients = 0
/c/login   gradients = 0
/v2/#/home gradients = 0（含切主题/移动端）
```

商品详情弹层额外扫描：gradients = 0。

响应式：

```text
320 / 390 / 768 / 1440：scrollWidth = clientWidth
```

## 色彩角色

```text
60% 主背景：#f7f3ea / #fffdf8
30% 次级：  #efe7da / #e4dccd / #6b6258 / #8a7f72
10% 强调：  #d95f3b / #f6e3da
```

强调色只用于主按钮、选中 Tab、未读角标、关键价格/状态，不铺满页面。

## 视觉层级

```text
页面标题 23px
区块标题 19-20px
正文/会话名 13-14px
辅助文字/时间 11-12px
头像 42-64px，操作按钮 28-38px
```

## 交互 / 体验

```text
CSocial：删除好友二次确认、隐藏会话可恢复、错误可重试、操作 toast
CMe：昵称保存 toast、偏好开关即时反馈、加载骨架/错误态/空态
全局：底部 6 Tab 统一，返回路径明确
```

## 保留项与已知限制

```text
60:30:10 按“色彩角色”验收；截图像素面积仍以浅色背景为主，
若按像素面积严格量化，需要再做一轮产品级视觉调色。
官方 Landing 已同步去渐变（桌面/移动端均 0 渐变），但不做 60:30:10 像素比例承诺。
C 端仍有 9-11px 辅助标签，后续可统一提升到 11-12px 下限。
```

截图：

```text
docs/design/c-end-audit-home.png
docs/design/c-end-audit-shop.png
docs/design/c-end-audit-app.png
docs/design/c-end-audit-orders.png
docs/design/c-end-audit-social.png
docs/design/c-end-audit-me.png
docs/design/c-end-audit-login.png
docs/design/landing-no-gradient-desktop.png
docs/design/landing-no-gradient-mobile.png
```
