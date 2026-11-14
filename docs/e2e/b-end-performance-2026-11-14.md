# B 端性能测试报告

日期：2026-11-14  
测试对象：B 端商家工作台 `/v2/b.html`  
账号：test_b_image（山雾茶业）  
环境：本地 FastAPI + PostgreSQL，Edge/Chromium 实测，Chrome DevTools trace + Playwright  
基线提交：95798b7（B 端工作结束后的当前代码）

## 结论

```text
页面加载：通过
  FCP / LCP / CLS / long task 均在可接受范围
  DOM 181-192，无长任务

接口：部分不通过
  售后列表严重偏慢：p50 726ms / p95 870ms / 并发 p95 2.1s
  根因确认：29 条售后全量扫描 + 逐条 get_order 的 N+1
  商品列表并发 p95 862ms，需要关注
```

## 页面加载

### 桌面 1440×1000

```text
TTFB            19ms
FCP             564ms
LCP             958ms（Chrome trace；render delay 941ms / 98.2%）
CLS             0
Long tasks      0
DOM             181-192 节点
资源            9 个 / 195,152 bytes
  JS            123,458 bytes
  CSS           51,574 bytes
```

![桌面 B 端](docs/design/b-perf-workbench-desktop.png)

### 移动 390×844

```text
FCP             84ms
LCP             1000ms（size 14,564 px）
CLS             0
DOMContentLoaded 78ms
资源            9 个 / 195,152 bytes
横向溢出         无（scrollWidth=375，clientWidth=375）
```

![移动 B 端](docs/design/b-perf-workbench-mobile.png)

LCP 主要耗时在 render delay，不是网络；没有 long task，说明不是单点 JS 卡死，更像首屏数据/渲染等待。当前不构成阻断，但可优化。

## 关键接口延迟

本地同机、B 账号、20 次顺序请求 + 5 并发 × 50 次：

| 接口 | p50 | p95 | max | 并发 5 p95 | 字节 | 状态 |
|---|---:|---:|---:|---:|---:|---|
| `/me` | 32ms | 37ms | 37ms | 176ms | 447 | 200 |
| `/products` | 173ms | 202ms | 208ms | 862ms | 8,958 | 200 |
| `/orders?limit=100` | 35ms | 41ms | 42ms | 122ms | 7,443 | 200 |
| `/after-sales?limit=100` | **726ms** | **870ms** | **872ms** | **2,139ms** | 40 | 200 |
| `/inventory/alerts` | 25ms | 27ms | 27ms | 104ms | 58 | 200 |
| `/reports/completion` | 28ms | 32ms | 37ms | 78ms | 475 | 200 |
| `/chat-profiles` | 26ms | 32ms | 35ms | 107ms | 51 | 200 |
| `/profiles` | 51ms | 90ms | 128ms | 139ms | 296 | 200 |
| `/profile-sources` | 52ms | 87ms | 101ms | 146ms | 494 | 200 |

原始数据：`var/b_perf_api.json`

## 售后列表根因

```text
workbench_after_sales：
  store.list_after_sales(limit=100) 返回全局 29 条工单
  对每条工单逐条 store.get_order()
  再对每条订单调用商家仓库 get_order() 做租户过滤
  ↓
29 次 C 端订单查询 + 29 次商家订单查询
```

实测：

```text
list_after_sales 预热后：239-245ms
get_order × 29：1,247ms（avg 43ms/条）
合计：约 1.5s
API p50 726ms，空结果仍返回 40 bytes
```

优化建议：

```text
按 merchant_id 在 DB 层过滤售后工单
或先批量取 order_ids → 一次 join/IN 查询商家订单
避免“全量工单 + 逐条订单 + 逐条商家校验”
```

## 性能门禁建议

```text
页面：
  LCP ≤ 2.5s        通过（958/1000ms）
  CLS ≤ 0.1         通过（0）
  TTFB ≤ 0.8s       通过（19ms）
  long task >50ms   通过（0）

接口：
  p95 ≤ 500ms       大部分通过
  并发 p95 ≤ 1s     商品/售后不通过
```

## 结论与下一步

```text
B 端页面加载性能通过。
B 端接口性能不通过，阻断点是售后列表 N+1。
商品列表在 5 并发下 p95 862ms，需观察是否 DB 连接池/查询竞争。
```

修复归属：

```text
B/企业端会话负责售后接口 N+1 与商品并发优化
本会话（系统/测评）负责复测、门禁与验收记录
```
