# C 端可交互头像：GrokBot 引擎原型

日期：2026-11-11

参考仓库：

- [ArvinYin1/grokbot-animation-anatomy](https://github.com/ArvinYin1/grokbot-animation-anatomy)

## 结论

**技术上可以用，已经接入 C App 原型。**

这个仓库不是视频 / GIF / Lottie，而是一个零依赖的程序化 SVG 动画引擎：

```text
createGrokBot(container, {
  size, state, seed, follow, theme
})
```

支持：

```text
setState("idle" | "thinking" | "streaming" | "happy" ...)
setExpression(...)
blink()
poke("bounce" | "nod" | "spin")
setGaze(...) / follow: true
destroy()
```

所以它适合做“有生命感”的头像，而不只是一个会眨眼的图片。

## 已接入方式

新增：

```text
web/src/vendor/grokbot/grok-player.js
web/src/vendor/grokbot/grok-recipes.json
web/src/components/CompanionAvatar.vue
```

`CompanionAvatar.vue`：

```text
动态 import 播放器 + recipes
→ createGrokBot()
→ 根据 state watch 切换状态
→ 点击 poke("bounce") + blink()
→ follow: true 让眼睛跟随鼠标
→ 组件卸载 destroy()
```

播放器和动画数据按需加载，不进入首屏主 bundle；没有新增 npm 依赖。

## 状态映射

当前 C App：

```text
idle      默认
thinking  Agent 正在回复
waiting   有订单草稿待确认
happy     订单已创建
```

点击头像：

```text
poke("bounce") + blink()
```

后续可以再接：

```text
listening  用户输入聚焦
streaming  Agent 流式输出
sleeping   长时间无操作
finished   操作完成
```

## 接入位置

- C App 聊天头部：40px 可交互头像
- C App 顶栏：34px 小头像
- 如果用户上传了自定义伙伴头像，则继续显示自定义图片，不覆盖

截图：

![C App 可交互头像](c-app-grokbot-avatar.png)

![点击后的头像](c-app-grokbot-poke.png)

## 许可证与来源边界

仓库 README 标注 MIT，但仓库中**没有 LICENSE 文件**；同时 README 明确说明：

```text
动画数据来自 Grok Bot macOS App 的 app.asar 静态分析
代码是重写移植
设计与数据归原始权利人所有
仅供研究，收到要求会下架
```

因此当前接入只能算：

```text
本地原型 / 技术验证
```

商用前必须二选一：

1. 用这套引擎，但换成千客自己的角色形状、表情和动画数据；
2. 取得原权利人的明确授权。

`web/src/vendor/grokbot/README.md` 已记录这个边界，不能把提取的 recipes 当独立素材包分发。

## 性能与已知限制

```text
播放器约 95KB
recipes 约 127KB（构建后 gzip 约 16KB）
按需加载
两个实例（聊天头部 + 顶栏）
无 npm 依赖
```

限制：

- 非 sphere 身体（clover/cloud）未移植，会回退 sphere。
- 动画数据是 GrokBot 角色，不是千客原创角色。
- 当前只映射 4 个状态，未接流式输出和输入聚焦。
- 小屏 34px 头像能看，但交互最好保持 40px 以上。
