# data-knowledge 批次 · P1 修复复核审计（2026-11-23）

> **批次：** data-knowledge（`docs/handbook/04-data-knowledge/`）
> **本批 P1 任务：** P1-16、P1-17（来源：`_meta/reviews/2026-11-23-p1-fix-tasks.md`）
> **复核文件：** [05-enterprise-data-governance.md](../../04-data-knowledge/05-enterprise-data-governance.md)（220 行）、[06-data-ingestion-etl.md](../../04-data-knowledge/06-data-ingestion-etl.md)（221 行）
> **生效基线：** `docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md`（V0.5.2 基线错误码勘误）
> **历史冻结：** V0.5.1 保留在仓库、`docs-site` `srcExclude` 排除、不进入公开站
> **审计性质：** 只读。除本报告外未修改任何文章、配置或代码；**未运行 pytest / Eval / API / 浏览器 E2E**。
> **复核方式：** 当前文本逐条对照代码与构建产物；对照原审计报告引用的原文；以既有构建日志/产物核验渲染；文中“已核验”均指静态代码/文件核对，不等于运行时验证。
> **最终结论：** **条件通过**（两个 P1 均真正修复；但同文件残留高优先 P2 事实错误与少量旧 P2 未处理，见第 3、6 节）。

---

## 1. 批次、范围、基线、代码快照

### 1.1 批次与范围

| 项 | 内容 |
|---|---|
| 批次 | data-knowledge（04 · Data & Knowledge） |
| 本批 P1 | P1-16 修正回答上下文脱敏结论（05 篇 §4 L110） |
| | P1-17 修复 ETL 代码围栏（06 篇 §8 L168–177） |
| 复核文件 | 05（220 行）、06（221 行） |
| 关联证据 | `src/rag_demo/{ingest_data,profile_view,logging_setup,cache,pipeline}.py`、`retrieval/hybrid_retriever.py`、`generation/generator.py`、`b_end/insights.py`、`mvp/{app,builder,mock_data,uploads}.py`、`db/connection.py`、`api/{kb,main}.py` |
| 关联文章 | 04/01 RAG（缓存键）、02/08 数据隐私与脱敏（脱敏口径）、02/03 多租户隔离（隔离状态）、04/09 血缘、04/10 知识库 |

### 1.2 基线 V0.5.2 核对（本批复核前提）

| 检查项 | 结果 | 证据 |
|---|---|---|
| V0.5.2 已发布且版本头更新 | 通过 | `v0.5.2:33-36`（`版本：V0.5.2 · 基线错误码勘误`，声明 V0.5.1 冻结保留、不进公开站） |
| §4.1 错误码示例勘误 | 通过 | `v0.5.2:656` `SQL_VALIDATION_ERROR`；V0.5.1 旧示例仍保留在 `v0.5.1:655` |
| V0.5.2 不再出现旧错误码 | 通过（大小写敏感检索 0 命中；全文仅剩指标名 `sql_read_only_violations`，非错误码） | `Select-String -CaseSensitive "READ_ONLY_VIOLATION"` = 0 |
| V0.5.1 保留不变 | 通过（内容签名：仍含 `version: 0.5.1` 与旧错误码/旧 retry 行，mtime 14:53:21 早于修复时段） | `v0.5.1:33,655-656,1356` |
| 公开站入口指向 V0.5.2 | 通过 | `docs-site/.vitepress/config.mjs:9,154`；`srcExclude` 含 `...v0.5.1.md`（`config.mjs:114-123`）；`docs/handbook/index.md:11`；`README.md:5,59,73,88,107` |
| V0.5.1/V0.5.2 行数与差异 | 1751 → 1752 行、54,765 → 55,004 字节；`git diff --no-index` = 8 insertions / 7 deletions | 仅版本头 3→4 行、错误码示例 2 行、§8.3 retry 1 行 |

**基线流程偏差（记录性，不计入本批）：** V0.5.2 版本说明写“只处理……错误码示例”，但 diff 同时修改了 §8.3 attempt 级 retry 一行（`v0.5.1:1356` → `v0.5.2:1357`）。该改动与 P1-03 口径和代码一致（内容正确），但与 M1-01“只改错误码示例”的验收表述不符。同类问题已在同目录 `enterprise-governance.md`（P2-15）登记，本报告不复计。

### 1.3 代码快照

| 项 | 值 |
|---|---|
| Git HEAD | `32ad31bc26365e8d0cefe503e6c09cfcd2876eaa`（`32ad31bc2636`），分支 `b-end-2.0-p0` |
| 工作区 | 含未提交修改（`git status --short`：AGENTS.md、`docs/career/*`、package.json、`api/{main,b_workbench}.py`、`static/login.*`、`web/*` 等） |
| 本批引用的代码文件 | `pipeline.py`、`generation/`、`retrieval/`、`logging_setup.py`、`profile_view.py`、`mvp/`、`ingest_data.py`、`b_end/`、`permissions.py`、`cache.py`、`db/connection.py` — `git status` 均为空（相对 HEAD 未修改） |
| 唯一相关未提交文件 | `src/rag_demo/api/main.py`（未提交改动，`git diff` 中无 `redact|脱敏|mask|sensitive|profile_text` 命中，不影响脱敏结论） |
| handbook 版本控制状态 | `git ls-files docs/handbook` = 0，整个目录未跟踪 → **无法取得文章修复前后 git diff** |
| 文档修复时间线 | 05/06 mtime = `2026-11-23 17:50:29`；同批其余 8 篇 = `15:40:25`；基线 V0.5.2 = `17:50:06`；V0.5.1 = `14:53:21` |
| 构建时间线 | `var/m1-docs-build.log` = 17:46:28 **失败**（4 个 `v0.5.1` dead link）；`var/m1-docs-build2.log` = 17:48:07 `build complete in 83.57s`；**`var/m2-docs-build.log` = 17:52:55 `build complete in 83.20s`**（晚于 05/06 修复）；`dist` 产物 = 17:52:55，68 个 HTML 页面 + localSearchIndex |

**核验限制：** 因 `docs/handbook/` 未入 Git，本报告用“当前文本 ↔ 代码/构建产物一致 + 原审计原文已消失 + mtime/行数未漂移”三类替代证据判断修复；不能替代严格 diff。

### 1.4 判定口径

本批两个 P1 均为**文档侧修复**（P1-16 改结论使其与代码一致；P1-17 修 Markdown 结构），不要求新增代码能力。因此“真正修复”的判据是：

1. 修改后文本与代码/构建产物逐条一致，不是只换措辞；
2. 原审计点名的错误结论/结构问题在文中与渲染产物中均已不存在；
3. 验收项可复核（含 docs-site 构建证据）；
4. 未把“局部能力”改写成“全链路能力”，也未把缺口写成已实现。

---

## 2. P1 任务逐项结论表

| 任务编号 | 位置 | 结论 | 证据（摘要） |
|---|---|---|---|
| P1-16 修正回答上下文脱敏结论 | 05 篇 §4 L110 | **已修复（真正修复）** | 原文“回答中敏感字段只以脱敏形式进入上下文”已消失；现文明确“日志层与画像卡牌展示已脱敏；进入生成上下文的 `profile_text` 尚未脱敏”，与代码链路逐条一致 |
| P1-17 修复 ETL 代码围栏 | 06 篇 §8 L168–177 | **已修复（真正修复）** | 关闭围栏 ` ``` ` 已单独成行（L177）；全文 16 个围栏（偶数）、12 个 H2；渲染产物 12 个 `<h2>` + 8 个 `<pre>`，`## 9`–`## 12` 在代码块外；`m2` 构建 `build complete` |

### 2.1 P1-16 复核细节

**当前文本（05 L110）：**

> **敏感信息与脱敏。** 日志层统一脱敏手机号/邮箱/身份证（`logging_setup.PiiRedactionFilter`）；画像卡牌不返回 `profile_text` / `embedding`，姓名按规则打码（`profile_view`）；日志层与画像卡牌展示已脱敏；进入生成上下文的 `profile_text` 尚未脱敏。

**代码证据链（主链路确实未脱敏）：**

| 环节 | 证据 |
|---|---|
| `profile_text` 由确定性代码生成，含姓名 | `ingest_data.py:269` `build_profile_text`；`ingest_data.py:283-284` `head = f"用户{row['user_id']}"` + 有姓名时拼 `（{row['user_name']}）` |
| 检索把 `profile_text` 原样作为候选 `text` 返回 | `retrieval/hybrid_retriever.py:228`（`SELECT id, user_id, profile_text, ...`）、`:244-248`（`"text": row[2]`） |
| 候选直接进生成 | `pipeline.py:347` `candidates = plan.candidates`；`:354` `generate(question, candidates, ...)`；`:356` 仅 `load_user_cards`（卡片展示层） |
| 生成上下文原样拼接候选文本 | `generation/generator.py:101` `build_context`；`:133` `lines.append(f"{head}\n{c['text']}")`；`:154-172` sources 也是原文截断，无脱敏 |
| 主链路无脱敏调用 | 全仓 `redact|脱敏|mask_pii|PiiRedaction` 的**执行逻辑**只集中在 `logging_setup.py`、`profile_view.py`、`b_end/insights.py`、`b_end/user_pool.py`（另 `prompts.py` 仅提示词文案、`memory_context.py:48` 仅文档字符串、`api/kb.py:273` 仅复用注释）；`pipeline/`、`generation/`、`retrieval/` 0 命中 |
| 旁路脱敏确实存在 | `b_end/insights.py:736-746` `_redact_result`（生成后对 answer/sources 替换姓名，调用点 `:562,593,693`）；`profile_view.py:42-48,51-76`（卡牌姓名打码、不返回 `profile_text`） |
| 日志脱敏确实存在 | `logging_setup.py:41-46` 手机号/邮箱/身份证正则；`:50-81` `redact_pii` + `PiiRedactionFilter` 挂 handler |

**验收对照（任务书 P1-16）：**

| 验收项 | 结果 |
|---|---|
| 不声称主链路上下文脱敏 | 通过：§4 现文明确写出缺口；全文检索无“上下文…脱敏”类旧结论（原句仅存于 `_meta` 审计/任务文档） |
| 关联文章无同源旧结论 | 通过：04/01、04/09、04/10、02/08 均未再出现“回答中敏感字段只以脱敏形式进入上下文” |
| 如要宣称需补代码/测试 | 未宣称，无需补 |

**残留（P2，见 3.2）：** 修复只落在 §4；frontmatter `description`（L3）与 §11 总结（L209）仍以不加限定的“脱敏”概括，且 §4 新句与前一分句存在重复（“画像卡牌不返回……姓名打码”与“日志层与画像卡牌展示已脱敏”语义重叠）。

### 2.2 P1-17 复核细节

**源文件结构（06 篇）：**

| 检查 | 结果 |
|---|---|
| 围栏位置（全部独立成行） | 44/56、72/94、108/112、116/119、127/136、**168/177**、183/192、208/214 |
| 围栏总数 | 16（偶数；原审计为 15、奇数） |
| H2 数量 | 12（`## 1.`–`## 12.`） |
| 行数 | 221（原审计 220；+1 行即关闭围栏独立成行） |
| 关闭围栏与正文分离 | L176 以“质量规则 DSL”结束、L177 为独立 ` ``` ` |

**渲染产物（`docs-site/.vitepress/dist`，17:52:55 构建）：**

- `assets/data-knowledge_06-data-ingestion-etl.md.BlRhDodH.js`：12 个 `<h2 id="_…">`（含 `_9-评估-验收`…`_12-延伸阅读`）、8 个 `<pre>`；§8 代码块在 `质量规则 DSL` 后立即 `</code></pre></div><p>已知限制…</p><h2 id="_9-评估-验收">`，未把 §9–§12 吞进代码块。
- 构建日志：`var/m2-docs-build.log`（mtime 17:52:55，晚于 17:50:29 的文章修复）“`build complete in 83.20s`”；此前 `m1-docs-build2.log`（17:48:07）亦通过。
- `dist` 共 68 个 HTML（60 篇正文 + 6 个分类 index + 根 index + 404），localSearchIndex 已生成。

**验收对照（任务书 P1-17）：**

| 验收项 | 结果 |
|---|---|
| 围栏数量为偶数 | 通过：16 |
| `## 9`–`## 12` 不在代码块内 | 通过：源码与渲染产物双重核对 |
| docs-site 构建通过 | 通过（以既有日志/产物为凭，本次未复跑构建命令，未取得进程退出码） |

---

## 3. 新发现问题（P0 / P1 / P2）

### 3.1 P0 / P1

- **P0：无。**
- **P1：无本批新增。** P1-16、P1-17 均通过；两文件未发现新的 P1 级事实错误或结构问题。
- **说明：** 同目录其他批次报告已登记的全局问题（V0.5.1 旧引用、V0.5.2 版本说明偏差）不计入本批，见 §4.3。

### 3.2 P2（按“是否本批文件”分层）

| 编号 | 级别 | 位置 | 问题（含是否为 P1 范围外） | 证据 | 建议 |
|---|---|---|---|---|---|
| DK-P2-01 | P2（高优先，**修复不完整**） | 06 篇 §5 L140 | “缓存键不含数据版本”与代码相反，且与 04/01 篇 §5 L121 直接矛盾；主审计 §5 已列为“P1 修复后应同批处理”的高优先 P2，本轮未修 | `cache.py:125-129`（`raw` 拼 `data_version`）；`pipeline.py:108-115`（`data_version=dataset_data_version(dataset)`）；`api/main.py:1822-1825`；04/01 篇 L121“缓存键包含……数据版本” | 改为“缓存键已含数据版本；仍需在构建后显式 clear”并同步 01/06 两篇口径 |
| DK-P2-02 | P2（P1-16 残留） | 05 篇 L3（description）、L209（§11）；L110 句内 | 摘要层仍以“脱敏”无限定概括，读者可能读成全链路脱敏；§4 新句与前一分句语义重复（机械插入痕迹） | 05:3“已实现的多租户隔离、权限裁剪、只读账号与脱敏能力”；05:209“脱敏与部分审计”；05:110 两个分句重复“画像卡牌…已脱敏” | 摘要补“日志/卡牌展示已脱敏，主链路上下文未脱敏”；§4 合并重复分句 |
| DK-P2-03 | P2（旧 P2，未修） | 05 篇 L165；06 篇 L138 | “demo 只读”“demo 永远不允许写”表述过绝对；代码只在登录态路由层把写路径导向 `test`，连接层未禁止显式声明 `demo` 写入 | `mvp/app.py:147-151`（无登录态直接返回 requested）；`config.py:122-123`（`ADMIN_DEBUG_DATASET="test"`）；`db/connection.py:188-205`（`require_write_scope` 只要求显式声明，未禁 demo） | 改为“登录态 API 不把 demo 作为写目标；离线/脚本模式仍可显式指定，需在入口补硬校验” |
| DK-P2-04 | P2（旧 P2，未修） | 05 篇 §2 L60 vs §4 L99-104 | 同一 L1~L4 记号先表示数据密级、后表示权限能力，易混为同一套等级 | 05:60（L1 公开…L4 高度敏感）vs 05:99-104（L1 基础…L4 完全）；代码 `sensitivity INT` 与权限 L1~L4 无映射 | 数据分级改文字表述，或显式标注两套编号不对应 |
| DK-P2-05 | P2（低，描述口径） | 06 篇 L3 vs §6 L150 / §8 L169 | description 写“当前只支持 CSV/Markdown”，正文写“仅 CSV / Markdown / 图片”“CSV/Markdown/图片上传”，两处口径不一致 | 06:3；06:150；06:169 | description 补“图片”或限定为“结构化数据源仅 CSV/Markdown” |
| DK-P2-06 | P2（跨篇新暴露） | 04/01 L136、04/05 L143、04/06 L149、04/10 L142 vs 02/03 L153 | 数据知识 4 篇仍写“租户隔离/企业间数据不可见：已实现（物理分库）”；Enterprise 03 经 P1-08 修复后改为“部分实现（队列/Webhook/单应用单商家缺口）”，同一主题出现“已实现 vs 部分实现”并列 | 01:136、05:143、10:142“已实现（物理分库）”；06:149“已实现（分库 + 锁）”；02/03:153“部分实现（…队列/Webhook/单应用单商家缺口见 §4.6）”（mtime 17:50:06，P1-08 已生效） | 4 篇统一加“数据面/物理库”限定，或按 Enterprise 03 口径降级为“部分实现（数据面已隔离；队列/Webhook 见专题）” |

> 说明：DK-P2-01 是本批最需要处理的问题——它既是事实错误、又与 01 篇矛盾，且被主审计明确列为“应同批处理”。它不改变 P1-16/P1-17 的修复结论，但使本批不能判“通过”。

---

## 4. 跨篇一致性检查

### 4.1 本批两篇的关联检查

| 关联对 | 检查点 | 结果 |
|---|---|---|
| 05 ↔ 02/08 数据隐私与脱敏 | 脱敏结论是否一致 | **一致**：Enterprise 08 只称“画像姓名脱敏/日志脱敏/b_end 旁路替换”，未宣称主问答上下文脱敏（08:86,119,183）；与 05 修正后结论相容。风险点：08 §2 mermaid（08:44-55）把“画像姓名脱敏 profile_view”画到“LLM 上下文”，属解读偏差，建议 enterprise-governance 批次复核（他批，不计入本批） |
| 05 ↔ 04/10 知识库 | 画像卡接口是否返回 `profile_text` | **一致**：10:65“画像（分页卡片，不返回 `profile_text`/`embedding`）”；05:110 同口径 |
| 06 ↔ 04/01 RAG | 问答缓存键是否含数据版本 | **不一致（DK-P2-01）**：01:121 写“包含……数据版本”，06:140 写“不含数据版本”；代码支持 01 |
| 06 ↔ 04/09 血缘 | sha256 清单 / 构建历史 / 指纹 | **一致**：09:89,102-108,172 与 06:114-121,140 对清单、构建历史、指纹的描述一致 |
| 05/06 ↔ code（demo 写保护） | demo 是否“永远不可写” | 两篇相互一致，但均过绝对（DK-P2-03） |
| 05/06 ↔ 基线 V0.5.2 | 是否引用旧版本/旧审计 | **无问题**：05/06 未引用 V0.5.1 或 `audit-2026-11-23` 旧审计报告（0 命中）；05/06 无旧错误码 `READ_ONLY_VIOLATION`/`LIMIT_REQUIRED`/`TENANT_SCOPE` |
| 05/06 ↔ 各自 frontmatter | 实现状态标注 | 基本一致：05 `部分实现 + 已设计`、06 `已实现 + 部分实现`，与正文 §8 相符 |

### 4.2 批内其他文章（不在本批复核范围，仅交叉影响）

| 项 | 结果 |
|---|---|
| 01/03/04/08/10 | 本轮未改动（mtime 15:40:25）；未发现被 05/06 修复波及的新矛盾 |
| 02/07/09 | 本轮未改动；与 05/06 的缓存键/血缘口径问题见 4.1 |
| 其余 16 项批内 P2 | 不在 P1 修复范围，本轮未逐项复核（见 §5） |

### 4.3 全局旧基线引用（跨批，已由同目录其他报告登记，本批不复计）

- `06-architecture-practice/02:157`、`09:112,159,211`、`10:210`、`02-enterprise-governance/07:48` 仍引用 `01-enterprise-agent-architecture-v0.5.1.md` 路径/版本；V0.5.1 已被 `srcExclude` 排除出公开站。
- `01-agent-architecture/02:518,616`、`02:689`、`03:419,475`、`04:325` 仍以“V0.5.1”作链接文字/正文称谓，但 href 已指向 v0.5.2。
- `var/m1-docs-build.log`（17:46:28）显示 M1-01 发布后首次构建因 4 个 `v0.5.1` dead link 失败，随后 `m1-docs-build2.log` 通过（说明链接已重定向，但标签未同步）。
- 上述问题已在 `agent-architecture.md`（P2-1）与 `enterprise-governance.md`（P2-10、P2-13、P2-15）登记；**本批 05/06 无此类残留**，故不计入本批结论，仅提示全站发布前需统一收尾。

---

## 5. 未核验项

1. **pytest：未运行。** 未取得任何新的测试结果。相关测试文件存在但未执行：`tests/test_logging_pii.py`、`tests/test_incremental.py`、`tests/test_build_search_index.py`、`tests/test_ingest_text_limits.py`。
2. **运行时行为：未运行。** 未验证 `logging_setup.PiiRedactionFilter` 的真实输出、KB 画像卡接口响应、RAG 生成上下文的实际内容；P1-16 结论为静态代码链路核对，不等于端到端 PII 注入测试通过。
3. **docs-site 构建：未复跑。** 以既有日志/产物为凭（`var/m2-docs-build.log` 17:52:55 `build complete`、`dist` 68 页与 localSearchIndex）；未取得该次构建进程退出码，未逐条验证 68 条路由可访问。
4. **上传/构建链路：未实际执行。** 06 篇的编码归一、分隔符嗅探、增量合并、空输入保护、失败留痕、构建锁等均为代码静态核对；`tests/` 中未检索到直接覆盖 GBK/分隔符嗅探的用例（关键词检索 0 命中），不排除间接覆盖。
5. **修复前后逐行 diff：无法取得。** `docs/handbook/` 未入 Git（`git ls-files`=0）；修改范围以 mtime、行数、原审计原文对照推定。
6. **P1 相关代码未改动（符合任务边界）。** 本批“修复”仅指文档结论/结构与代码、构建产物一致，不是新增脱敏或结构校验代码。
7. **未复核**批内其余 16 项 P2（非本批 P1 范围，依赖 2026-11-23 审计报告）；未访问文章外部链接（DAMA/NIST/pgvector 等）；未核验生产 PostgreSQL、真实部署与浏览器交互。

---

## 6. 批次结论

### 6.1 文章结论

| 文章 | 原审计结论 | 本批 P1 | 复核后结论 | 遗留 P2 |
|---|---|---|---|---|
| 05 企业数据治理 | 条件通过（P1×1） | P1-16 | **通过（P1 已修复）** | DK-P2-02/03/04（3 项） |
| 06 数据接入与 ETL | 条件通过（P1×1） | P1-17 | **通过（P1 已修复）** | DK-P2-01/03/05（3 项，与 05 去重后共 2 项独立） |
| 合计 | 条件通过 2 / 通过 0 | 2 | **通过 2 / 不通过 0** | 5 项（去重） |

### 6.2 批次裁决

**条件通过。**

依据：

1. **P1-16、P1-17 均为真正修复**：P1-16 新结论与“`profile_text` 生成 → 检索候选 → `generate()` → `build_context` 拼接”的完整代码链路一致，不是只换措辞，且不再宣称主链路上下文脱敏；P1-17 围栏结构与渲染产物（12 H2 / 8 代码块 / `## 9` 起在代码块外）双重核对通过，构建日志显示修复后构建完成。
2. **本批未发现新增 P0/P1**；两个 P1 修复之间及与 05/06 其余章节无互相矛盾。
3. **判“条件通过”而非“通过”的原因**：
   - **DK-P2-01**（06:140 缓存键）是事实错误且与 01 篇矛盾，并被 2026-11-23 主审计明确列为“P1 修复后应同批处理”的高优先 P2，本轮未处理；
   - **DK-P2-02/03/04** 属批内已登记 P2（P1 范围外）或 P1-16 的摘要层残留，均未修；
   - **DK-P2-06** 为跨篇新暴露的口径矛盾（数据知识 4 篇 vs Enterprise 03 的 P1-08 修复结果），需下一轮对齐；
   - 全局 V0.5.1 残留引用（§4.3）不影响本批两文件的事实结论，但会影响“全站可发布”判断。

### 6.3 放行条件（建议）

1. 修 DK-P2-01：06:140 改为“缓存键已含数据版本”，与 01:121 及代码（`cache.py:125-129`、`pipeline.py:108-115`）对齐；
2. 修 DK-P2-02：05 摘要层（L3、L209）补主链路缺口限定，合并 L110 重复分句；
3. 修 DK-P2-03：05:165 / 06:138 的“demo 永远不可写”改为“登录态写路径不落 demo + 离线模式需硬校验”；
4. 修 DK-P2-06：数据知识 4 篇租户隔离状态与 Enterprise 03 口径对齐（加“数据面”限定或降级为部分实现）；
5. 全局收尾：按 §4.3 清理 V0.5.1 残留引用与 V0.5.2 版本说明偏差（转 M1/对应批次）；
6. 上述修改后重跑 `docs-site` 构建并做人工渲染抽查（本报告未复跑构建）。

---

## 附录 A · 关键证据索引

| 结论 | 文件:行 |
|---|---|
| 05 脱敏新结论 | `04-data-knowledge/05-enterprise-data-governance.md:110` |
| 05 demo/租户/摘要残留 | `05:3,143,165,209` |
| 06 围栏修复 | `04-data-knowledge/06-data-ingestion-etl.md:168,176,177` |
| 06 缓存键错误 | `06:140`；对照 `04-data-knowledge/01-rag-architecture.md:121` |
| `profile_text` 含姓名 | `src/rag_demo/ingest_data.py:269,283-284` |
| 检索返回原文 | `src/rag_demo/retrieval/hybrid_retriever.py:228,244-248` |
| 候选进生成 | `src/rag_demo/pipeline.py:347,354` |
| 上下文拼接 | `src/rag_demo/generation/generator.py:101,133` |
| 旁路脱敏 | `src/rag_demo/b_end/insights.py:736-746`；`src/rag_demo/profile_view.py:42-76` |
| 日志脱敏 | `src/rag_demo/logging_setup.py:41-46,50-81` |
| 缓存键含 data_version | `src/rag_demo/cache.py:125-129`；`src/rag_demo/pipeline.py:108-115`；`src/rag_demo/api/main.py:1822-1825` |
| demo 写保护边界 | `src/rag_demo/mvp/app.py:147-151`；`src/rag_demo/config.py:122-123`；`src/rag_demo/db/connection.py:188-205` |
| 构建日志（失败/成功） | `var/m1-docs-build.log`；`var/m1-docs-build2.log`；`var/m2-docs-build.log` |
| 站点入口/排除 V0.5.1 | `docs-site/.vitepress/config.mjs:9,114-123,154` |
| V0.5.2 勘误/retry 行 | `01-enterprise-agent-architecture-v0.5.2.md:33-36,656,1357`；对照 `v0.5.1:33,655-656,1356` |

## 附录 B · 本次执行的只读检查

```text
git rev-parse HEAD / git branch --show-current / git status --short
git diff --no-index v0.5.1 v0.5.2
Get-ChildItem（mtime/尺寸）/ Get-Content（构建日志、dist chunk）
围栏计数与 H2 计数（PowerShell 逐行匹配）
grep/Select-String（脱敏、profile_text、缓存键、V0.5.x、旧错误码、旧审计引用）
读取源码：ingest_data / hybrid_retriever / pipeline / generator / profile_view /
           logging_setup / cache / insights / mvp.app / config / db.connection / api.main
```

> 未执行：pytest、Eval、API 调用、浏览器 E2E、docs-site 重构建、上传/构建实测。
