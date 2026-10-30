# C 端自定义头像上传

> 功能：买家/伙伴头像支持自定义上传（PNG / JPEG / WebP，≤ 1MB），上传后立即预览；消息头像、顶部头像、会话列表头像优先显示图片，失败回退首字。
> 范围：C 端（`/c/app`）与 C 端 API；不改 Agent 权限、不改 Router、不改订单链路。

## 1. 文件与职责

| 文件 | 改动 |
|---|---|
| `src/rag_demo/c_end/store.py` | 头像校验/落盘/迁移/读取/恢复默认（唯一存储入口） |
| `src/rag_demo/api/c_end.py` | `POST/GET/DELETE /api/c/companion/avatar/{kind}` |
| `web/src/views/CApp.vue` | 点击头像 / 「更换」入口上传，即时预览、失败回退首字 |
| `tests/test_c_end_avatar.py` | 17 条测试：上传、拒绝、跨用户隔离、恢复默认、旧库迁移、HTTP 状态码 |
| `docs/c-end-avatar.md` | 本文档 |

## 2. 接口

所有接口都要求登录（`auth.current_account()`），并按登录账号隔离 owner；`kind` 只允许 `companion`（伙伴头像）或 `user`（我的头像）。

```text
POST   /api/c/companion/avatar/{kind}     multipart/form-data，字段名 file
GET    /api/c/companion/avatar/{kind}     返回图片字节（image/png | image/jpeg | image/webp）
DELETE /api/c/companion/avatar/{kind}     恢复默认头像（前端回退首字）
GET    /api/c/companion                   伙伴资料，含 avatar_url / user_avatar_url
```

`GET /api/c/companion` 新增字段：

```json
{
  "avatar_url": "/api/c/companion/avatar/companion?v=3f2a9c0d1e4b",
  "user_avatar_url": ""
}
```

- URL 由服务端拼接，带内容版本号（相对路径摘要前 12 位），换头像后浏览器缓存自动失效；
- 未设置时为空字符串，前端显示名字首字。

### 状态码与错误码

| HTTP | `detail.code` | 场景 |
|---:|---|---|
| 200 | — | 上传/读取/恢复默认成功（DELETE 返回完整伙伴资料） |
| 400 | `INVALID_AVATAR_TYPE` | MIME 不在 PNG / JPEG / WebP 白名单 |
| 400 | `INVALID_AVATAR_CONTENT` | 声明图片类型与文件魔数不一致（伪造后缀/MIME） |
| 400 | `EMPTY_AVATAR` | 空文件 |
| 400 | `INVALID_AVATAR_KIND` | kind 不是 companion / user |
| 401 | — | 未登录 |
| 404 | `AVATAR_NOT_FOUND` | 当前账号未设置该头像，或 DB 中路径非法/文件缺失 |
| 413 | `AVATAR_TOO_LARGE` | 超过 1MB |
| 500 | — | 落盘/DB 写失败（对照服务端日志排查） |

## 3. 安全边界

```text
校验：MIME 白名单 + 文件魔数 + 大小上限（1MB）三重校验（服务端）
命名：{owner_token}/{kind}_{uuid4.hex}.{png|jpg|webp}
      owner_token = sha256(owner_id)[:16]，用户无法控制文件名/路径
落盘：受控根目录 var/c_end_avatars/（QIANKE_C_END_AVATAR_DIR 可覆盖）
读取：只按「当前登录账号」查 c_companion 的相对路径，再校验
      - 路径必须匹配固定正则（无 ../、无绝对路径、无任意扩展名）
      - resolve 后必须仍在受控根目录内（is_relative_to）
      - 只读当前 owner 自己的记录，跨用户返回 404
缓存：Cache-Control: private, max-age=300（不写 public，避免代理缓存）
```

- 头像文件与业务库（订单/商品/优惠券）完全分离，写头像不触碰任何业务表；
- 上传只接受文件字节，不接收文件路径/URL 参数；
- DB 只保存**相对路径**，对外 URL 每次由服务端拼接。

## 4. 数据模型与旧库迁移

`c_companion` 增加两列（旧库自动迁移，不丢历史数据）：

```sql
ALTER TABLE c_companion ADD COLUMN avatar_path      TEXT NOT NULL DEFAULT '';
ALTER TABLE c_companion ADD COLUMN user_avatar_path TEXT NOT NULL DEFAULT '';
```

`init()` 中通过 `PRAGMA table_info(c_companion)` 判断列是否存在，旧库（无这两列）首次调用任意 store 函数时自动补齐；升级前写入的伙伴资料保持原样，头像默认空 = 回退首字。测试 `test_old_database_migrates_avatar_columns` 覆盖该路径。

## 5. 前端行为（CApp.vue，白色极简）

| 入口 | 行为 |
|---|---|
| 顶栏头像 / 会话头部头像 / 会话列表头像 / 消息头像 | 有图片显示图片；点击伙伴头像打开「伙伴头像」文件选择 |
| 自己的消息头像 | 点击打开「我的头像」文件选择 |
| 右侧概览「头像」区 | 「更换」按钮 + 已设置时「恢复默认」按钮；上传/失败提示为一行浅色文本 |
| 消息头像、顶部头像、会话列表头像 | `<img @error>` 失败时把该 URL 标记为坏图，回退首字 |

上传流程：

```text
选择文件 → 前端先校验 MIME/大小 → URL.createObjectURL 立即预览
→ POST multipart → 成功后用服务端 avatar_url 覆盖预览并释放 objectURL
→ 失败：撤销预览，回退上传前头像/首字，显示一行错误文案
```

保持白纸面/浅灰/细边框风格，只新增头像行与胶囊按钮，不新增营销式 UI。

## 6. 验证结果（2026-10-30，本机）

```text
$ .\.venv\Scripts\python.exe -m pytest tests/test_c_end_avatar.py -q
17 passed in 7.56s

$ .\.venv\Scripts\python.exe -m pytest tests/test_c_end_store.py tests/test_c_end_store_idempotency.py tests/test_c_end_idempotency.py -q
30 passed in 9.61s

$ .\.venv\Scripts\python.exe -m pytest tests/ -q
411 passed, 5 skipped, 1 warning in 33.37s
（当前全量套件，含头像、商家、幂等；5 skipped 为既有的真实模型/集成类用例）

$ cd web && npm run build
vite v6.4.4 building for production...
✓ 114 modules transformed.
dist/assets/index-*.js  1,043.71 kB │ gzip: 307.69 kB
✓ built in 4.37s
build_exit=0（仅既有的 chunk > 900kB 体积警告）
```

构建产物静态核对：`dist/assets/index-*.js` 中包含 `更换伙伴头像` 与 `/api/c/companion/avatar/` 字符串，说明本次前端改动已进入生产构建。

覆盖的测试点：

```text
上传成功（PNG / JPEG / WebP）+ 精确 1MB 边界
MIME 非白名单拒绝 / 伪造内容拒绝 / 超限拒绝
服务端生成路径（owner token 目录 + 固定正则）
替换头像时清理旧文件
恢复默认：URL 清空、文件删除、重复调用幂等
owner 隔离（store 层 + HTTP 层跨用户 404）
DB 相对路径含 ../ 或绝对路径时拒绝读取
旧库自动迁移 avatar_path / user_avatar_path
HTTP 200/401/400/404/413 与错误码
```

## 7. 未覆盖 / 限制

| 项 | 说明 |
|---|---|
| 浏览器 E2E | 已用 Playwright 真实后端验证：点击「更换伙伴头像」/「更换我的头像」→ 选择 PNG → 上传 200、`<img>` 加载成功；随后 DELETE 恢复默认并刷新，确认回退首字。测试用 1×1 透明测试图，未覆盖真实照片画质/EXIF |
| 图片内容解码 | 服务端只校验魔数与大小，不解码像素；畸形但魔数正确的图片仍会存储并在前端 `<img>` 失败时回退首字 |
| 图片压缩/裁剪 | 不做服务端缩放、裁切、EXIF 清理；大尺寸图片由前端 `object-fit: cover` 展示 |
| 旧头像物理清理 | 替换/删除时 best-effort 删除旧文件；删除失败只保留孤儿文件，不影响新头像 |
| 速率限制 / 恶意刷上传 | 未加限流；单文件 1MB 上限 + owner 目录隔离，生产环境建议在网关层加限流与审计 |
| 多实例部署 | 本地文件系统存储，多实例需共享挂载（或后续换对象存储）；当前定位 mock 阶段 |
| 头像内容审核 | 不做内容安全审核（与当前产品阶段一致） |

## 8. 回滚

- 代码回滚：还原 `store.py` / `c_end.py` / `CApp.vue` 三个文件即可；新增的两列对旧代码是未知列，不影响旧逻辑；
- 数据回滚：不需要删列（SQLite 删列代价高），旧代码读取时忽略即可；
- 文件回滚：`var/c_end_avatars/` 可整体删除，接口会按「未设置」处理。
