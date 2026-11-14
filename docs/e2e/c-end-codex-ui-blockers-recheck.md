# Codex UI 验收阻断项复验（C 端范围）

日期：2026-11-14  
基线：Codex 指出的 agent@84ef791 验收结论

## 已修

### 2. Landing 星云 Canvas 渐变

```text
web/src/components/landing/HeroNebula.vue
  makeGlowTexture / makePointTexture / 2D fallback 光晕
  createRadialGradient / addColorStop → 纯色同心圆
```

验证：

```text
Playwright 注入 CanvasRenderingContext2D 计数：
  createRadialGradient/createLinearGradient = 0
CSS background-image gradient = false
```

截图：docs/design/landing-no-gradient-desktop.png

### 5. 输入法组词误发

```text
CApp：
  compositionstart/end 状态 + isComposing + 100ms 尾窗
  Enter 在组词阶段直接 return，不发送/不清空草稿

Chat.vue：
  同样的 composition 守卫，Ctrl/⌘+Enter 组词阶段不提交
```

验证：

```text
CApp 390px：
  compositionstart 后按 Enter
  输入框仍为「测试」
  消息列表数量 0
  compositionend + 延迟后 Enter 可正常发送（草稿清空）
```

## 不在本轮 C 端修复范围

Codex 同时列出：

```text
1. 企业端/ B 端仍存在 CSS 渐变、商品缺图占位、报告骨架渐变
3. 桌面侧栏浮动规范不符合（B/企业端）
4. 智能助理/账单/离线评测窄屏溢出
```

这些属于 B 端/企业管理端文件与布局，本轮 C 端 agent 未擅自改；需要主人确认归属后由对应 agent 处理。

## 复验交付

```text
前端 build PASS
Playwright：Landing Canvas 0 渐变；CApp 组词 Enter 不发送
待 Codex 复验并补充 B/企业端整改结论
```
