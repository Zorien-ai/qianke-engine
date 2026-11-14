# C App 输入框聚焦后空白问题修复

日期：2026-11-14

## 现象

```text
手机点输入框弹出键盘
页面被整体滚动
输入框跑到上方，中间出现大块空白，消息区消失
```

## 原因

```text
CApp 移动端外壳只改了 --c-vh 高度，没有把外壳固定到 visualViewport
iOS 键盘弹起时浏览器仍可滚动 body
输入框聚焦 + visualViewport resize 把页面推出原位
```

## 修复

```text
移动端 .c-app 固定到 visualViewport:
  position: fixed
  top: var(--c-vh-offset, 0)
  height: var(--c-vh)
  overflow: hidden
进入 CApp 时锁 body overflow，卸载恢复
syncViewportHeight 同时记录 visualViewport.height / offsetTop
键盘关闭时强制回落到 window.innerHeight，offsetTop 归零
增加 window resize 监听和 blur 后延迟复位
```

## 验证

```text
键盘打开：跟随 visualViewport 高度 / offsetTop
键盘关闭：app height 回到 window.innerHeight
390x844 -> 390x500 -> 390x844
app height 844
offsetTop 0
window.scrollY = 0
宽度 390 / 390，无横向溢出
```

截图：docs/design/c-app-keyboard-fixed.png
