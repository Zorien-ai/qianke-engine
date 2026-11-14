# C 端性能测试报告

日期：2026-11-14  
对象：C 端首页 `/c/home`、市集 `/c`、CApp `/c/app`、订单、消息、我的  
环境：本地 FastAPI + PostgreSQL，Playwright（桌面/移动/冷启动/Fast 3G）+ Chrome DevTools trace  
测试账号：13900005678  
代码基线：B 端工作结束后的 `95798b7`

## 结论

```text
C 端页面本地交互指标基本通过：
  FCP/LCP 低、无 long task（首页仅 2 个 59ms 内长任务）
  CApp / 订单 / 消息 / 我的 CLS = 0

两个性能阻断：
1. CShop CLS 超标：实测 0.17-0.58（阈值 0.1）
2. 首屏冷启动资源过大：1.59MB 未压缩；Fast 3G 下 LCP 约 8.0s

接口：
  顺序请求基本都 <35ms
  /api/c/merchant/products p50 172ms；5 并发 p95 870ms，需关注
```

## 页面加载（桌面 1440）

| 页面 | TTFB | FCP | LCP | CLS | Long tasks | DOM |
|---|---:|---:|---:|---:|---:|---:|
| /c/home | 21ms | 196ms | 312ms | 0.052 | 2（max 59ms） | 176 |
| /c | 21ms | 148ms | 284ms | **0.17-0.53** | 0 | 313 |
| /c/app | 20ms | 124ms | 172ms | 0.009 | 0 | 325 |
| /c/orders | 19ms | 156ms | 208ms | 0 | 0 | 75 |
| /c/social | 26ms | 96ms | 416ms | 0 | 0 | 123 |
| /c/me | 24ms | 96ms | 212ms | 0 | 0 | 164 |

桌面 CShop 截图：

![CShop 桌面](docs/design/c-perf-shop-desktop.png)

## 页面加载（移动 390，冷启动）

| 页面 | FCP | LCP | CLS | 首屏传输 |
|---|---:|---:|---:|---:|
| /c/home | 236ms | 368ms | 0.087 | 1,586,543 B |
| /c | 188ms | 288ms | **0.576** | 6,691 B（模块已缓存） |
| /c/app | 120ms | 372ms | 0 | 8,804 B（模块已缓存） |

移动 CShop 截图：

![CShop 移动](docs/design/c-perf-shop-mobile.png)

## 首屏体积与慢网

冷启动主资源：

```text
main-*.js   1,203,788 bytes
main-*.css    308,539 bytes
Content-Encoding：无（未启用 gzip/brotli）
首屏总传输：约 1.59 MB
```

Fast 3G（150ms RTT / 1.6Mbps）+ 冷缓存：

```text
CApp DCL    7,725ms
FCP         7,752ms
LCP         8,004ms
传输        1,553,320 B
CLS         0
```

Chrome DevTools CShop trace：

```text
LCP         503ms
TTFB        17ms
render delay 486ms
CLS         0.17
```

## CLS 根因

Chrome trace 的最坏布局偏移簇：

```text
459ms - 1,560ms，score 0.1723
移动元素：
  SECTION.shared-cart
  SECTION.shop-grid
  DIV.assistant-panel
```

CShop 初始先渲染头部，商品数据返回后才插入今日手记/购物车等内容，
把 shared-cart、shop-grid 整体向下推；移动端冷启动实测 0.576。

修复建议：

```text
为今日手记/购物车预留稳定高度（骨架或 min-height）
或把今日手记移到商品网格下方，不在已有内容上方插入
商品图使用固定 aspect-ratio / width / height
```

## C 端接口延迟

20 次顺序 + 5 并发 × 50 次：

| 接口 | p50 | p95 | 并发 5 p95 | 字节 |
|---|---:|---:|---:|---:|
| `/api/c/products` | 17ms | 19ms | 55ms | 1,226 |
| `/api/c/merchant/products` | **172ms** | **187ms** | **870ms** | 4,083 |
| `/api/c/companion` | 19ms | 23ms | 109ms | 260 |
| `/api/c/friends` | 20ms | 24ms | 140ms | 373 |
| `/api/c/groups` | 19ms | 21ms | 158ms | 311 |
| `/api/c/threads/unread` | 31ms | 37ms | 231ms | 86 |
| `/api/c/friends/.../messages` | 20ms | 21ms | 161ms | 15 |
| `/api/c/groups/.../messages` | 20ms | 22ms | 77ms | 15 |
| `/api/c/app/messages` | 17ms | 22ms | 74ms | 431 |
| `/api/c/orders` | 18ms | 20ms | 62ms | 13 |

主要慢点是商家商品库：`/api/c/merchant/products` 与 B 端 `/products` 共用商家仓库链路，
5 并发 p95 约 870ms。CShop 首屏依赖该接口时，弱网/并发场景会放大等待。

## 性能门禁建议

```text
页面：
  CLS ≤ 0.1         CShop 不通过（0.17-0.58）
  LCP ≤ 2.5s        本地通过（<=503ms）
  TTFB ≤ 0.8s       通过（<=26ms）
  首屏传输 ≤ 500KB  C 端不通过（1.59MB 未压缩）

接口：
  顺序 p95 ≤ 500ms  通过
  并发 5 p95 ≤ 1s   商家商品 870ms 接近上限，需持续观察
```

## 修复优先级

```text
P0  CShop CLS：预留今日手记/购物车高度，商品图固定尺寸
P0  首屏资源：路由级代码分割 + gzip/brotli（或 CDN 压缩）
P1  商家商品接口 5 并发 p95 870ms：检查 DB 连接池/查询缓存
P2  首页 2 个 <60ms 长任务：可接受，暂不阻断
```

## 归属

```text
C 端会话：CShop CLS 与代码分割
系统/测评会话：复测、门禁、体积与慢网基线
B/企业端会话：商家商品接口并发优化（与 B 端共用）
```

---

# 修复后复测（2026-11-14 20:30，C 端会话）

## 结论

两个 P0 阻断均已消除：

```text
CShop CLS      1440：0.17 → 0.03；390：0.576 → 0.00（阈值 0.1）
首屏传输       1.59MB → 约 104KB（gzip 生效后，冷启动 /c）
CApp 慢网 LCP  Fast 3G：8,004ms → 870ms
```

提交：`e40b704 perf(c): stabilize CShop CLS, split routes and enable gzip`
（同批 UI 修复 `60c1bf4`）

## 改动清单（工作区未提交）

```text
web/src/views/CShop.vue   今日手记改为常驻同高结构（骨架占位 + h3 单行 + 正文 2 行 clamp）
web/src/router.js         26 个视图全部改为路由级动态 import（首屏不再打包全部 B/C/A 视图）
src/rag_demo/api/main.py  app.add_middleware(GZipMiddleware, minimum_size=1024)
```

`main.py` 只加压缩中间件，未改任何业务逻辑；加完重启了本地 uvicorn 才生效（当前 PID 17592，日志 `var/system_api.log`）。

## CLS 前后对比

| 页面 / 宽度 | 修复前 | 修复后 | 阈值 |
|---|---:|---:|---|
| /c 1440（冷启动） | 0.17 | **0.03** | ≤0.1 |
| /c 390（冷启动） | 0.576 | **0.00** | ≤0.1 |
| /c/app Fast 3G + 4× CPU | 0 | 0.00 | ≤0.1 |

1440 残留 0.03 的布局偏移来自 `assistant-panel` + `count`（商品渲染后行高变化），已低于门禁，未继续处理。

CLS 根因与修法：

```text
根因：featuredProduct 为空时今日手记不渲染；商品接口返回后 section 插入到
      已有「购物车 + 商品网格」上方，把它们整体向下推（trace 命中 0.169 的位移簇）。
修法：今日手记常驻渲染，加载中显示同结构骨架；h3 单行省略、正文固定两行
      （min-height 34px + line-clamp 2），加载前后高度一致，不再插入/撑开。
```

## 首屏体积前后对比

冷启动主资源：

| 资源 | 修复前 | 修复后（raw） | 修复后（gzip） |
|---|---:|---:|---:|
| main JS | 1,203.79 KB | **192.90 KB** | **74.86 KB** |
| main CSS | 308.54 KB | **75.75 KB** | **14.01 KB** |
| 路由块 CShop | 无（打在主包） | 34.11 KB | 11.68 KB |
| 路由块 CApp | 无（打在主包） | 92.00 KB | 28.21 KB |
| 首屏总传输 /c | 约 1.59 MB | — | **约 104 KB** |

分块效果（`web/dist/assets`）：

```text
main        192.9 KB (gzip 74.9)
CApp         92.0 KB (gzip 28.2)   ← /c/app 才加载
Landing     556.8 KB (gzip 147.5)  ← 官网，C 端不加载
CShop        34.1 KB (gzip 11.7)
CSocial      26.1 KB / COrders 18.0 KB / CMe 10.5 KB / CHome 4.0 KB
```

压缩验证（curl，`Accept-Encoding: gzip`）：

```text
main-*.js   192,903 B → 74,858 B（39%），Content-Encoding: gzip
main-*.css   75,746 B → 14,011 B（18%），Content-Encoding: gzip
```

## 慢网前后对比（CApp，Fast 3G + 冷缓存）

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| LCP（CPU 1×） | 8,004 ms | **870 ms** |
| LCP（CPU 4×） | — | 1,671 ms |
| CLS | 0 | 0.00 |
| 传输 | 1,553,320 B | 约 104 KB |

LCP 修复后主要耗时变成 Render delay（CPU 执行），不再是网络下载。

## 构建与测试

```text
cd web && npm run build     → ✓ built in 5.99s
pytest tests/ -q            → 823 passed, 6 skipped（与基线一致，无回归）
C 端子集                    → 30 passed
```

## 复验截图

`docs/design/c-end-perf/c-perf-after-shop-desktop.png`（1440）
`docs/design/c-end-perf/c-perf-after-shop-mobile.png`（390）

## 已知边界

```text
1. 首次冷启动实测 /c 传输 88KB 时，CShop 路由块已被同会话缓存（transferSize 0）；
   104KB 为按 dist 产物 + curl gzip 尺寸计算的冷缓存值。
2. brotli 未做：本地 uvicorn 只有 GZipMiddleware；上线若有 nginx/CDN 可再叠 br。
3. 首屏仍需一次 main + 一次路由块的串行下载；如需再压，可对 C 端路由做
   modulepreload 预取（本次未做，避免与 B 端打包策略冲突）。
4. 商家商品接口 5 并发 p95 870ms 未处理（归属 B 端会话）。
```

