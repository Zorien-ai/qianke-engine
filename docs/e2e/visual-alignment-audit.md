# 视觉对齐审计（2026-11-14）

## 审计范围

```text
首页 /home               1440 / 390
B 端工作首页             1440 / 390
B 端订单                 1440
B 端经营报告             1440 / 390
C 端 /c/app              1440 / 390
```

## 结论

```text
所有页面无横向溢出
首页 390：380 / 380
B 端 390：375 / 375
C 端 390：390 / 390
```

## 发现并修复

### 1. 经营报告指标卡未成网格

- 桌面 5 张指标卡原本纵向堆叠
- 原因：报告页用了未定义的 `b-metric-grid`
- 修复：改为 `b-report-metrics`，桌面 5 列，≤1180 三列，≤700 单列

### 2. B 端工作首页报告卡文案过期

- 仍写“经营报告待接入 / 暂不绘制经营趋势”
- 修复：改为“已接入”，按钮进入经营报告页

### 3. 手机端 B 端标题拆词

- “经营报告”被拆成“经营报 / 告”
- 修复：手机端标题字号收紧 + `word-break: keep-all`

## 截图

```text
docs/design/b-end-2.0-p0-prod-completion-report.png
docs/design/b-end-2.0-p0-prod-completion-report-mobile.png
docs/design/landing-home-redesign-mobile.png
```

## 剩余非阻断项

```text
C 端历史会话仍保留旧版“图片发不过去”的回复，新消息才走当前链路
B 端手机工作首页低库存卡在首屏底部被截断，可滚动
```
