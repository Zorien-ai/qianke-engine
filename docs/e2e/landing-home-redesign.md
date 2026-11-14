# 官网首页改版：首屏 B 端叙事

日期：2026-11-14

## 问题

```text
原首屏文案要等约 6 秒动画结束才出现
首屏卖的是“AI 用户画像助理”，不是当前 B 端商家工作台
商家工作台入口层级过低
B 端区块在旧产品区之后，信息顺序倒置
```

## 改动

```text
首屏标题立即可见，不再等 6 秒
标题改为：把店铺经营，交给听得懂人话的工作台
副标题：订单、库存、经营报告 · 一个 B 端工作台
主 CTA：进入商家工作台
次 CTA：体验 C 端 Demo / 查看文档
B 端商家工作台区块移到 Hero 之后
保留星云动画作为右侧氛围，不再阻塞左侧信息
PWA 缓存版本 v23 → v24
```

## 验证

```text
地址：http://127.0.0.1:8000/v2/#/home
首屏 700–900ms：
  标题、副标题、三个 CTA 均可见
section 顺序：
  hero → b-workbench → product → pain → security
1440 视口无横向溢出
390 视口：scrollWidth = clientWidth = 380
控制台无新增错误
```

## 截图

```text
docs/design/landing-home-redesign-first.png
docs/design/landing-home-redesign-b.png
```
