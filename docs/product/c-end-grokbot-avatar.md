# C 端可交互头像：千客小鱼角色 v1

日期：2026-11-11

参考引擎：

- [ArvinYin1/grokbot-animation-anatomy](https://github.com/ArvinYin1/grokbot-animation-anatomy)

## 结论

技术上可用，已接入 C App，并换成千客自己的状态配方：

```text
引擎：程序化 SVG，零依赖
角色数据：qianke-recipes.json
状态：idle / listening / thinking / streaming / waiting / happy / fed / petted / sleeping / waking
```

## 已实现

### 1. 状态机

```text
默认              idle
输入框聚焦        listening
Agent 回复中      thinking
收到回复后        streaming（1.4 秒）
有订单草稿        waiting
订单完成          happy
喂食              fed（1.6 秒）
摸摸              petted（1.6 秒）
90 秒无操作       sleeping
睡觉时被唤醒      waking
```

### 2. 点击头像菜单

```text
喂食    → fed + 弹跳 + “小鱼吃饱了”
摸摸    → petted + 点头 + “小鱼蹭了蹭你”
换表情  → happy / surprised / sleepy / squinted / confused / neutral 循环
```

菜单是移动端可用的轻量弹出层，点击遮罩关闭。

### 3. 千客自己的 recipes

`web/src/vendor/grokbot/qianke-recipes.json`：

```text
只保留 9 个聊天生命周期 clip
10 个千客状态
角色主色改为暖墨绿 + 柿子高光
移除了 Grok 的 53 状态全集和品牌状态
```

播放器引擎不变，角色状态集和配色已经切到千客。

### 4. 语音口型 / 情绪

暂未接，属于下一阶段：

```text
语音输入口型
流式 token 节奏映射
更细的情绪状态
```

## 位置

- C App 聊天头部：44px 可交互头像
- C App 顶栏：34px 小头像
- 用户上传自定义伙伴头像时，仍优先显示上传图片

## 效果

![千客可交互头像](c-app-qianke-avatar.png)

![头像互动菜单](c-app-qianke-avatar-menu.png)

![头像特写](qianke-avatar-closeup.png)

## 验证

```text
frontend build: success
头像状态：listening / thinking / streaming / fed / petted 已实际验证
点击头像：菜单弹出
喂食：state=fed，提示“小鱼吃饱了”
摸摸：state=petted，提示“小鱼蹭了蹭你”
换表情：提示“换了个表情”
console error: 0
```

## 版权边界

引擎代码来自开源仓库，README 标注 MIT 但仓库没有 LICENSE 文件；基础形状/表情数据源自 Grok Bot App，原 README 写明仅供研究。

当前 `qianke-recipes.json` 是在该数据结构上做的千客状态集和配色，不是完全原创几何。商用前需要：

```text
1. 自研角色形状 / 表情数据；或
2. 取得原权利人的明确授权。
```

`web/src/vendor/grokbot/README.md` 已记录该边界。

## 性能

```text
grok-player 约 56KB（构建后）
qianke-recipes 约 39KB
按需加载
两个实例
无新增 npm 依赖
```
