# B / 企业端会话 Handoff

日期：2026-11-14  
新会话职责：B 端 / 企业端 UI 修复与验收整改。  
当前主协调会话不再承接 B/企业端编码。

## 基线与仓库

```text
分支：b-end-2.0-p0
当前提交：0f6c0ac
```

重要：工作区目前有**未提交的 B/企业端改动**（b-workbench.js/css、main.css、Chat.vue、Billing/AgentDemo 等）。先 `git status` / `git diff` 判断归属，禁止 reset 或 checkout 丢弃。

## Codex 未关闭阻断项

来自 Codex UI 验收 #71 / #73 / #75，整体仍退回。

### #1 B/企业端仍有 CSS 渐变与占位

```text
web/src/styles/main.css:125 企业端共享外壳渐变
web/src/b-workbench.css:786 商品缺图占位（390px）
web/src/b-workbench.css:1491 报告加载骨架（390/1440px）
```

要求：纯色，渐变 = 0；补 320/390/768/1440 扫描。

### #3 桌面侧栏不符合浮动规范

```text
B 端：web/src/b-workbench.css:1648
  active 1440：贴左、圆角 0、组距 18px、无固定用户区、
  hover 232→232px（未展开）

企业端：web/src/styles/main.css:154
  贴左、248px、圆角 0
```

目标规范：

```text
四边 16px 外距
圆角 20px
悬停展开 72px → 240px
文字延迟 80ms 淡入
组间距 32px
组标题 11px 大写灰字
底部固定用户区
```

### #4 窄屏溢出

```text
智能助理页：390px 整页宽 412px，退出按钮超出视口
账单页：390px 整页宽 411px
离线评测页：390px 整页宽 482px，JSON 示例撑开容器
```

要求：

```text
320 / 390 下按钮可触达
代码块/JSON 在容器内滚动，不撑开页面
滚动容器 max-width:100%、overflow-x:auto、min-width:0
```

## 已关闭 / 不要重复做

```text
#2 Landing Canvas/WebGL 渐变：Codex 已在 0f6c0ac 关闭
#5 CApp / Chat IME：CApp 与 Chat.vue 已加 composition 守卫
  Codex 合成事件回归通过；原生输入法仍待人工补证
```

## 验收要求

```text
UI 标准：
  60:30:10 口径 A（色彩角色）
  禁止 CSS / Canvas / shader / Bloom 渐变
  删除多余标语、说明文字、次要标签

测试：
  cd web && npm run build
  pytest 相关 B 端测试（b_workbench / chat_profile / tenant 等）

浏览器：
  320 / 390 / 768 / 1440
  B 端工作台 / 企业端 / 智能助理 / 账单 / 离线评测
  侧栏 hover、键盘 Esc 关闭、弹层回焦
```

交付给 Codex 时必须附：

```text
提交号
可访问版本
复验截图
可复现的测试命令与结果
```

## 不应做的事

```text
不要动 C 端功能与 CApp/CShop/CSocial/CMe
不要动 Pachat 定时任务与 Codex 协调
不要 reset 工作区或覆盖其他 agent 的未提交修改
不要在群里泄露 token、配对码、主人隐私
```

## 新会话第一步

```text
1. git status / git diff：确认未提交 B 文件
2. 先复现 Codex 的 #1/#3/#4 截图与宽度
3. 按 #1 → #3 → #4 顺序修，单次改动只碰一个阻断项
4. build + 四档浏览器复验，附证据
```
