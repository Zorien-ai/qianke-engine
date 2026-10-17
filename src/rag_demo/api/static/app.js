/* 用户画像 RAG 智能问答 —— 前端交互 */

/* 示例问句：只给**问法**，不写具体取值（城市名 / 等级名 / 品类名）。
 *
 * 演示页的数据是固定的，但取值不属于系统规则：写死「深圳的钻石会员」，
 * 换一份数据（或用户从向导进来复用这套问法）就是让他点一个查不到东西的问题。
 * 具体取值由画面对应的数据决定——首页的数据概况、向导页的 /examples 都是动态的。
 */
const EXAMPLE_QUESTIONS = [
  "高价值用户怎么定义的",
  "流失预警的判定标准",
  "用户说优惠券过期了怎么办",
  "客单价最高的用户有什么共同点",
  "用户主要分布在哪些城市",
  "各会员等级的用户分别有多少",
];

const el = (id) => document.getElementById(id);

/* ---------- 身份与权限 ----------
 * 身份来自登录态（M3）：后端从 Cookie 会话解析，页面不再自选角色。
 * 能力清单仍来自 /whoami，前端**不硬编码权限表**——两份真源必然改漏一处。
 *
 * ⚠ 前端隐藏面板只是"不设计入口"，不是权限。真正的拦截在后端
 *   （直接 curl 接口绕不过去）。这里隐藏是因为"用不了的功能不该出现"，
 *   而不是因为"藏起来就安全"。
 */
let currentRole = null;
let currentUser = "";
let ACCOUNT = null;      // 当前登录账号（含企业信息）
let CAPS = {};
let CURRENT_LEVEL = "";
let TOPK_RANGE = { min: 1, max: 30 };

/* 所有请求都走这里：401 = 未登录/会话过期 → 直接回登录页。
 * 让每个调用点自己判断 401 必然漏，漏掉的那处会表现为"点了没反应"。 */
async function apiFetch(url, options = {}) {
  const res = await fetch(url, { ...options, headers: { ...(options.headers || {}) } });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("未登录");
  }
  return res;
}

async function loadWhoami() {
  const mine = await (await apiFetch("/whoami")).json();
  if (!mine.authenticated) {
    window.location.href = "/login";
    return mine;
  }
  ACCOUNT = mine.account || null;
  currentRole = mine.role || "";
  currentUser = mine.username || "";
  CAPS = mine.can || {};
  CURRENT_LEVEL = mine.level || "";
  TOPK_RANGE = mine.topk_range || TOPK_RANGE;

  // 等级徽章：管理员改完配置后，账号能直接看到自己现在是哪一级。
  // 「人员授权」优先于角色默认，所以这里按账号说明，而不是按角色。
  const badge = el("level-badge");
  if (CURRENT_LEVEL) {
    badge.hidden = false;
    badge.textContent = mine.level_label || CURRENT_LEVEL;
    badge.title = "账号的有效等级（人员授权优先于角色默认）";
  } else {
    badge.hidden = true;
  }

  renderAccount(mine);
  el("role-note").textContent = mine.note || "";
  applyCapabilities();

  // 权限面板的数据单独拉：必须 await，否则调用方（保存/授权后）写提示文案时
  // 会被后面异步完成的 renderPermissions 清空——表现为"保存成功了但提示是空的"
  if (CAPS.ops) await loadPermissions();
  if (canManageAccounts()) await loadAccounts();

  el("stats-panel").hidden = !CAPS.stats;
  if (CAPS.stats) loadStats();
  return mine;
}

function canManageAccounts() {
  return !!(ACCOUNT && (ACCOUNT.is_system_admin || ACCOUNT.is_enterprise_admin));
}

function renderAccount(mine) {
  const bar = el("account-bar");
  bar.hidden = false;
  const acct = ACCOUNT || {};
  const who = acct.display_name || acct.username || "未知账号";
  el("account-name").textContent =
    `${who}（${acct.account_type_label || "-"} · ${acct.role_label || acct.role || "-"}）`;
  const ent = acct.enterprise;
  const entEl = el("account-ent");
  if (ent) {
    entEl.hidden = false;
    entEl.textContent = `企业：${ent.name}`;
  } else {
    entEl.hidden = true;
  }
  // 待审核/停用：把原因直接说在提问框上方，而不是让他点一次才发现没反应
  if (acct.status && acct.status !== "active") {
    el("ask-hint").textContent = `账号${acct.status_label || "待审核"}：通过后即可使用`;
  }
}

function applyCapabilities() {
  // 权限管理：没有「运维 / 权限管理」能力就连面板都不渲染（默认只有管理员）。
  // 面板数据由 loadWhoami 里 await loadPermissions() 负责，这里只管显隐。
  el("perm-panel").hidden = !CAPS.ops;

  // 账号管理：系统管理员看全部，企业管理员只看本企业员工
  el("accounts-panel").hidden = !canManageAccounts();

  // 数据概况：无权限直接不渲染
  if (!CAPS.stats) el("stats-grid").innerHTML = "";

  // 召回对比（/search）是最敏感的接口：无权限连入口都不出现
  el("compare-btn").hidden = !CAPS.raw_search;
  if (!CAPS.raw_search) el("compare-panel").hidden = true;

  // 返回多少个用户：运营及以上才出现
  el("topk-bar").hidden = !CAPS.topk;
  if (CAPS.topk) {
    const input = el("topk-input");
    input.min = String(TOPK_RANGE.min);
    input.max = String(TOPK_RANGE.max);
    input.placeholder = `默认（上限 ${TOPK_RANGE.max}）`;
    el("topk-range").textContent = `范围 ${TOPK_RANGE.min}~${TOPK_RANGE.max}`;
  }

  // 融合与精排 / SQL 原文与结果：管理员专属。
  // 换身份时旧 DOM 还留在面板里，只 hidden 不够——内容也要清掉，
  // 否则下次切回有权限的身份、某个子块没被重写，就会看到上一个身份的数据。
  if (!CAPS.trace_flow) {
    el("trace-flow-section").hidden = true;
    el("trace-flow").innerHTML = "";
  }
  if (!CAPS.sql) {
    el("trace-sql-section").hidden = true;
    el("sql-body").textContent = "";
    el("trace-sql-note").textContent = "";
    el("trace-sql-rows").innerHTML = "";
  }

  // 看不到来源列表的身份：来源整节隐藏（否则换身份后会留下上一份来源）
  if (!CAPS.sources) el("detail-sources-section").hidden = true;

  // 看不到任何过程信息时，把上一身份留下的面板清掉，避免残留
  if (!CAPS.sources && !CAPS.sql && !CAPS.internals) el("detail-panel").hidden = true;

  el("ask-btn").disabled = !CAPS.ask;
  el("ask-hint").textContent = CAPS.ask
    ? "按 Ctrl / Cmd + Enter 快速提交"
    : ACCOUNT && ACCOUNT.status && ACCOUNT.status !== "active"
      ? `账号${ACCOUNT.status_label || "待审核"}：通过后即可使用`
      : "当前账号无权提问";
}

/* ---------- 数据概况 ---------- */
async function loadStats() {
  const grid = el("stats-grid");
  const status = el("stats-status");
  try {
    const res = await apiFetch("/stats");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const levels = data.member_levels || {};
    const levelText = Object.entries(levels)
      .map(([k, v]) => `${k} ${v}`)
      .join(" · ");

    // 占比卡片跟着数据走：取人数最多的那一档（后端已按条数降序），
    // 不再写死「钻石」——用户的等级可能叫黑卡 / 金卡 / VIP3
    const topLevel = Object.entries(levels)[0];
    const topRatio = topLevel ? (data.level_ratio || {})[topLevel[0]] : null;

    const cards = [
      { value: data.users.toLocaleString(), label: "用户画像", extra: `共 ${data.profiles_columns} 个结构化字段` },
      { value: data.docs, label: "知识库文档", extra: `切分为 ${data.chunks} 个分块` },
      { value: data.cities, label: "覆盖城市", extra: `品类 ${data.categories} 类` },
      { value: topRatio || "—", label: topLevel ? `${topLevel[0]}占比` : "等级占比", extra: levelText || "—" },
    ];

    grid.innerHTML = cards
      .map(
        (c) => `
        <div class="stat-card">
          <div class="stat-value">${c.value}</div>
          <div class="stat-label">${c.label}</div>
          <div class="stat-extra">${c.extra}</div>
        </div>`
      )
      .join("");
    status.textContent = "实时读取";
  } catch (err) {
    grid.innerHTML = `<div class="stat-card"><div class="stat-label">加载失败：${err.message}</div></div>`;
    status.textContent = "不可用";
  }
}

/* ---------- 示例问题 ---------- */
function renderExamples() {
  el("examples-list").innerHTML = EXAMPLE_QUESTIONS.map(
    (q) => `<button type="button" class="chip">${q}</button>`
  ).join("");
  el("examples-list").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    el("question-input").value = chip.textContent;
    el("question-input").focus();
  });
}

/* ---------- 渲染答案（高亮 [来源N]） ---------- */
function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/* 答案正文统一走 markdown（见 /static/markdown.js）。
 *
 * 改前这里是「转义 + 只包一层 [来源N]」：模型输出 `**北京 722 人**`、`- 列表`、
 * 表格、代码块，全部原样显示成一堆星号和竖线。
 *
 * [来源N] 的处理保持原语义：
 *   有来源列表 -> 可点击的小标签；看不到来源的身份 -> 直接去掉（指向看不见的东西更糟）。
 * 流式路径必须在这里处理——服务端按 delta 分片做正则会被切片边界漏掉。
 */
function formatAnswer(text) {
  return window.renderMarkdown(text, {
    cite: (n) => (CAPS.sources ? `<span class="cite">[来源${n}]</span>` : null),
  });
}

/* ---------- 思维链（仅开启深度思考时出现） ---------- */
/* 每轮都重置：上一条问题的推理留在页面上，会被当成这次的结果 */
function resetReasoning() {
  const box = el("reasoning-box");
  box.hidden = true;
  box.open = false;
  el("reasoning-body").textContent = "";
  el("reasoning-meta").textContent = "";
}

/* ---------- 提交提问（流式）---------- */
async function ask(question) {
  const btn = el("ask-btn");
  const spinner = btn.querySelector(".spinner");
  const btnText = btn.querySelector(".btn-text");

  el("result-panel").hidden = true;
  // 溯源面板是独立 section，不跟着 result-panel 一起隐藏：
  // 新一轮提问必须立刻把它收掉，否则请求失败/中途无 delta 时，
  // 屏幕上会一直挂着上一题的来源（看起来就是「溯源不刷新」）。
  el("detail-panel").hidden = true;
  el("error-panel").hidden = true;
  resetReasoning();
  btn.disabled = true;
  spinner.hidden = false;
  btnText.textContent = "检索中…";

  const t0 = performance.now();
  let firstCharAt = null;

  try {
    const payload = { question, retriever: currentRetriever };
    // 返回多少个用户：仅运营及以上身份能调，且留空表示用系统默认
    if (CAPS.topk) {
      const v = parseInt(el("topk-input").value, 10);
      if (!Number.isNaN(v)) payload.top_k = v;
    }
    // 深度思考：所有身份都能开。只影响最后一个生成调用，
    // 但首字要等 20~45s（推理不通过 delta 下发到回答里），所以文案要跟着变
    if (el("think-input").checked) payload.deep_thinking = true;
    const res = await apiFetch("/qa/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`HTTP ${res.status} — ${detail.slice(0, 200)}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let answer = "";
    let route = "rag";
    /* 流式重渲染节流：每来一个 delta 就整段重解析 markdown 没必要，
     * 80ms 一次足够跟手，也避免长答案把主线程压住（表格/代码块重建更贵）。 */
    let renderTimer = null;
    const scheduleRender = () => {
      if (renderTimer) return;
      renderTimer = setTimeout(() => {
        renderTimer = null;
        el("answer-body").innerHTML = formatAnswer(answer);
      }, 80);
    };
    let sources = [];
    let sqlText = "";
    let rowsCount = null;
    let sqlRows = [];
    let sqlError = null;
    let trace = null;
    let cached = false;
    let resultShown = false;
    let reasoning = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE 以空行分隔消息
      const parts = buffer.split("\n\n");
      buffer = parts.pop();

      for (const part of parts) {
        let event = "message";
        let dataStr = "";
        for (const line of part.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
        }
        if (!dataStr) continue;

        let data = {};
        try { data = JSON.parse(dataStr); } catch { continue; }

        if (event === "stage") {
          btnText.textContent = data.stage === "generating" ? "生成中…" : "检索中…";
        } else if (event === "meta") {
          route = data.route || "rag";
          sources = data.sources || [];
          sqlText = data.sql || "";
          rowsCount = data.rows_count ?? null;
          sqlRows = data.sql_rows || [];
          sqlError = data.sql_error || null;
          trace = data.trace || null;
          cached = !!data.cached;
          if (data.cached) btnText.textContent = "命中缓存";
        } else if (event === "reasoning") {
          // 思维链先于答案到达（开启深度思考时才有）。它单独一条通道，
          // 不拼进 answer——否则推理里的 [来源N] 会被当成引用、污染事实/推断的呈现。
          if (!resultShown) {
            renderStreamShell({
              route, sources, sqlText, rowsCount,
              sqlRows, sqlError, trace, cached, question,
            });
            resultShown = true;
          }
          const box = el("reasoning-box");
          if (box.hidden) {
            // 推理阶段就展开：这是 20~45s 等待里唯一在动的东西，
            // 收起来用户只会看到界面卡住
            box.hidden = false;
            box.open = true;
          }
          reasoning += data.delta;
          el("reasoning-body").textContent = reasoning;
          el("reasoning-meta").textContent = `${reasoning.length} 字`;
          btnText.textContent = "深度思考中…";
        } else if (event === "delta") {
          if (!resultShown) {
            // 首个片段到达——此刻才让结果区出现，避免空白面板闪一下
            renderStreamShell({
              route, sources, sqlText, rowsCount,
              sqlRows, sqlError, trace, cached, question,
            });
            resultShown = true;
          }
          if (firstCharAt === null) {
            firstCharAt = performance.now();
            btnText.textContent = "生成中…";
            // 答案开始到达：把思维链收起来，否则它会一直把正文顶在视口外
            if (reasoning && el("reasoning-box").open) el("reasoning-box").open = false;
          }
          answer += data.delta;
          scheduleRender();
        } else if (event === "error") {
          // 把错误类型带到外层 catch，由它统一决定显示什么文案
          // （LLM 故障用人话，其他错误照实但截断）
          const err = new Error(data.message || "服务端错误");
          err.kind = data.kind || "";
          throw err;
        }
      }
    }

    if (resultShown) {
      // 收尾：把节流里还没落地的一段立刻渲染出来，再画图表
      if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; }
      el("answer-body").innerHTML = formatAnswer(answer);
      window.hydrateMermaid(el("answer-body"));
      finishStreamShell((performance.now() - t0) / 1000,
                        firstCharAt ? (firstCharAt - t0) / 1000 : null);
    } else {
      throw new Error("未收到任何内容");
    }
  } catch (err) {
    el("error-panel").hidden = false;
    // LLM 接口故障：固定文案 + 说明检索是正常的，
    // 别把 APITimeoutError 直接甩给用户（2026-10-15 改）
    el("error-text").textContent =
      err.kind === "llm_unavailable"
        ? "模型服务暂时不可用（LLM 接口调用失败），请稍后重试。检索是正常的——你的问题和资料都没问题。"
        : `请求失败：${err.message}`;
  } finally {
    btn.disabled = false;
    spinner.hidden = true;
    btnText.textContent = "提问";
  }
}

/* 流式结果区：回答区只放正文，过程信息统一交给下一个面板 */
function renderStreamShell({ route, sources, sqlText, rowsCount, sqlRows, sqlError, trace, cached, question }) {
  const badges = [
    `<span class="badge ${route}">${String(route).toUpperCase()}</span>`,
    `<span class="badge time" id="elapsed-badge">生成中…</span>`,
  ];
  if (cached) badges.push(`<span class="badge time">缓存命中</span>`);
  el("result-badges").innerHTML = badges.join("");

  el("answer-body").innerHTML = "";
  // 思维链与回答同一个生命周期：新一轮提问不该看到上一轮的推理
  resetReasoning();

  // cached 必须往下传：命中缓存时 trace 是上一次检索的留痕，
  // 不传的话溯源面板会把它当成「本次过程」照常展示（2026-10-17 实测反馈）
  renderDetail({ sources, sqlText, rowsCount, sqlRows, sqlError, trace, cached, question });

  el("result-panel").hidden = false;
  el("result-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- 数据来源与检索过程（独立面板） ---------- */
function renderDetail({ sources, sqlText, rowsCount, sqlRows, sqlError, trace, cached, question }) {
  const panel = el("detail-panel");

  // 闲聊：没有来源、没有查询结果、没有留痕，这个过程区没有意义
  if (!sources.length && !sqlText && !sqlRows.length && !trace) {
    panel.hidden = true;
    // 只 hidden 不清内容的话，下一次面板重新出现时若某个子块没被重写，
    // 旧 DOM 会留在那儿——表现就是「溯源不刷新」。
    el("detail-question").textContent = "";
    const note = el("detail-cache-note");
    note.hidden = true;
    note.textContent = "";
    el("trace-plan").innerHTML = "";
    el("trace-variants").innerHTML = "";
    el("trace-flow").innerHTML = "";
    el("detail-sources").innerHTML = "";
    el("trace-sql-rows").innerHTML = "";
    return;
  }
  panel.hidden = false;
  el("detail-body").hidden = false;
  el("detail-fold").textContent = "收起";

  // trace 为空有两种完全不同的原因，不能都写成「缓存」：
  //   · 当前身份没有 internals 权限 -> trace 被 permissions.render 整键裁掉
  //   · 本次真的没产生留痕（例如缓存里没存 / 走了兜底）
  // 混着写的话，用户会以为「换了身份还在用旧缓存」（2026-10-17 实测反馈）。
  const canInternals = !!CAPS.internals;
  // 「融合与精排」是管理员专属：无权时整个区块（含标题）不出现
  const canFlow = !!CAPS.trace_flow;
  el("trace-flow-section").hidden = !canFlow;
  const hasTrace = !!trace;

  // 1) 原问题
  el("detail-question").textContent =
    (trace && trace.question) || question || "（本次请求未留痕）";

  // 1.1) 命中缓存声明：秒回保留，但过程数据必须标明是上一次的，
  //      不能让用户以为这是本次重新检索跑出来的（2026-10-17 实测反馈）
  const cacheNote = el("detail-cache-note");
  if (cached) {
    cacheNote.hidden = false;
    // 声明里只提这个身份**真能看到**的东西，否则等于告诉他「有东西没给你看」
    cacheNote.textContent = canInternals
      ? "本次命中缓存、未重新检索：以下来源与检索过程均为缓存中的上一次结果。"
      : CAPS.sources
        ? "本次命中缓存、未重新检索：以下来源为缓存中的上一次结果。"
        : "本次命中缓存、未重新检索：以下查询结果为缓存中的上一次结果。";
  } else {
    cacheNote.hidden = true;
    cacheNote.textContent = "";
  }

  // 2) 走的路径 + 改写的路径
  const variants = (trace && trace.variants) || [];
  if (!canInternals) {
    // 无 internals 权限时 trace 被整键裁掉。这里**不再画空壳**——
    // 「检索路 0 条」+「（无）」会被读成「本次一条都没召回」，
    // 而事实是「没让你看」。只留一句明确的无权提示。
    el("trace-plan").innerHTML =
      `<span class="tp-chip is-warn">当前身份无权查看检索过程（检索式与召回条数需更高权限）</span>`;
    el("trace-variants").innerHTML = "";
  } else {
    const chips = [`<span class="tp-chip">检索路 <b>${variants.length}</b> 条</span>`];
    if (hasTrace) {
      chips.push(
        trace.need_sql
          ? `<span class="tp-chip is-sql">LLM 判定：需要 SQL</span>`
          : `<span class="tp-chip">LLM 判定：不需要 SQL</span>`
      );
    } else {
      chips.push(`<span class="tp-chip is-warn">本次未产生检索过程数据</span>`);
    }
    el("trace-plan").innerHTML = chips.join("");

    el("trace-variants").innerHTML =
      variants
        .map(
          (v) => `
      <div class="tp-variant">
        <div class="tp-variant-head">
          <span class="tp-strategy">${escapeHtml(v.strategy || "-")}</span>
          <span class="tp-count">召回 ${v.hit_count ?? 0} 条 · 画像入池 ${v.profile_candidates ?? 0} · 文档留 ${v.kept_count ?? 0} 条</span>
        </div>
        <div class="tp-query-block">
          <span class="tp-qlabel">检索式</span>
          <span class="tp-query">${escapeHtml(v.query || "")}</span>
        </div>
        <div class="tp-src-list">${
          (v.sources || []).map((s) => `<span class="tp-src">${escapeHtml(s)}</span>`).join("") ||
          `<span class="tp-src is-empty">无命中</span>`
        }</div>
        ${v.error ? `<div class="tp-err">${escapeHtml(v.error)}</div>` : ""}
      </div>`
        )
        .join("") || `<div class="tp-empty">（无）</div>`;
  }

  // 3) 收敛链路：各路并行召回 → 画像池统一精排 + 文档池每路精排 → 合并去重 → 入上下文
  //    两个池的名额口径不同（画像全局、文档每路），必须分开显示：
  //    并成一个"精排 画像3+文档2"会让人以为画像也是每路各取 3 个
  const totalHits = variants.reduce((n, v) => n + (v.hit_count ?? 0), 0);
  const merged = (trace && trace.fused_count) ?? 0;
  const limits = (trace && trace.limits) || {};
  const poolCount = (trace && trace.profile_pool_count) ?? 0;
  const profileText =
    limits.profile_pool != null
      ? `画像池统一精排 ${poolCount}→<b>${limits.profile_pool}</b>`
      : "画像池统一精排";
  const wikiText =
    limits.wiki_per_route != null
      ? `文档池每路 <b>${limits.wiki_per_route}</b>`
      : "文档池每路";
  // 没有 trace 时不能画这条链路：totalHits/merged 都会是 0，
  // 看起来像「一条都没召回却入了 5 条上下文」——那是权限裁剪造成的假象，不是事实
  el("trace-flow").innerHTML = !canFlow
    ? ""
    : hasTrace
      ? `
    <span class="tp-node">各路并行召回 <b>${totalHits}</b></span>
    <span class="tp-arrow">→</span>
    <span class="tp-node">${profileText} · ${wikiText}</span>
    <span class="tp-arrow">→</span>
    <span class="tp-node">合并去重 <b>${merged}</b></span>
    <span class="tp-arrow">→</span>
    <span class="tp-node is-final">入上下文 <b>${sources.length}</b></span>`
      : `<span class="tp-empty">本次未产生检索链路数据</span>`;

  // 4) 数据来源（名称 + 分数 + 命中它的检索式 + 内容）
  //    看不到来源列表的身份（cs）这里要整节隐藏：只留「（无）」会被读成
  //    「一条都没召回」，而事实是没让他看。现在 cs 也能看到查询结果，
  //    这个过程面板对他可见，所以不能再留空壳。
  el("detail-sources-section").hidden = !CAPS.sources;
  el("detail-sources").innerHTML =
    sources
      .map((s) => {
        const name = s.source || "unknown";
        let cls = "is-lib";
        if (name.endsWith(".md")) cls = "is-wiki";
        else if (name === "user_profile") cls = "is-profile";
        return `
      <div class="ds-item ${cls}">
        <div class="ds-head">
          <span class="ds-idx">[来源${s.index}]</span>
          <span class="ds-name">${escapeHtml(name)}</span>
          <span class="tp-score">${
            typeof s.rerank_score === "number" ? s.rerank_score.toFixed(4) : "-"
          }</span>
          ${s.expanded ? `<span class="tp-tag is-expand">全文扩展</span>` : ""}
          ${(s.strategies || [])
            .map((x) => `<span class="tp-tag">${escapeHtml(x)}</span>`)
            .join("")}
        </div>
        ${
          s.from_query
            ? `<div class="ds-from">命中检索式：${escapeHtml(String(s.from_query))}</div>`
            : ""
        }
        ${s.text ? `<div class="ds-text">${escapeHtml(s.text)}</div>` : ""}
      </div>`;
      })
      .join("") || `<div class="tp-empty">（无）</div>`;

  // 5) SQL 原文（管理员）与查询结果（所有人）
  //    查询结果是业务事实——和回答里的数字同源，藏起来只会让人无法核对；
  //    SQL 原文才是实现细节。两者分开判断，不捆在一起。
  const sqlSec = el("trace-sql-section");
  const showSqlText = !!CAPS.sql && !!sqlText;
  const hasRows = sqlRows.length > 0;
  const showSqlSec = showSqlText || hasRows || (!!CAPS.sql && !!sqlError);
  el("sql-text-block").hidden = !showSqlText;
  // 有 SQL 原文时「查询结果」是二级标题，没有时它就是这一节的主标题
  el("sql-rows-title").classList.toggle("is-sub", showSqlText);
  if (showSqlSec) {
    sqlSec.hidden = false;
    el("sql-body").textContent = showSqlText ? sqlText : "";
    // 总行数用后端的 rows_count（真实行数），不能用 sqlRows.length——
    // 后者是回传数组，已被 brief_rows 截到 20 行，>20 行时会显示成「共 20 行」，
    // 与顶部徽章的「返回 N 行」自相矛盾。
    const sqlTotal = typeof rowsCount === "number" ? rowsCount : sqlRows.length;
    el("trace-sql-note").textContent =
      CAPS.sql && sqlError
        ? `执行失败：${sqlError}`
        : sqlTotal > sqlRows.length
          ? `共 ${sqlTotal} 行，下列前 ${sqlRows.length} 行`
          : `共 ${sqlTotal} 行`;
    el("trace-sql-rows").innerHTML = sqlRows.length
      ? `<table class="tp-table">${sqlRows
          .map((r) => `<tr>${r.map((c) => `<td>${escapeHtml(String(c))}</td>`).join("")}</tr>`)
          .join("")}</table>`
      : `<div class="tp-empty">${CAPS.sql && sqlError ? escapeHtml(sqlError) : "（空结果）"}</div>`;
  } else {
    sqlSec.hidden = true;
    el("sql-body").textContent = "";
  }
}

/* 收尾：把「生成中…」换成实测耗时，并标出首字延迟 */
function finishStreamShell(elapsed, firstChar) {
  const badge = el("elapsed-badge");
  if (!badge) return;
  const first = firstChar !== null ? `首字 ${firstChar.toFixed(1)}s · ` : "";
  badge.textContent = `${first}总计 ${elapsed.toFixed(1)}s`;
}

function renderResult(data, elapsed) {
  const route = data.route || "unknown";

  // 徽章
  const badges = [
    `<span class="badge ${route}">${route.toUpperCase()}</span>`,
    `<span class="badge time">耗时 ${elapsed.toFixed(1)}s</span>`,
  ];
  if (typeof data.rows_count === "number") {
    badges.push(`<span class="badge time">返回 ${data.rows_count} 行</span>`);
  }
  el("result-badges").innerHTML = badges.join("");

  // 答案
  resetReasoning();
  el("answer-body").innerHTML = formatAnswer(data.answer || "（无内容）");
  window.hydrateMermaid(el("answer-body"));

  // 过程信息统一走 renderDetail（与流式路径共用，避免两处逻辑分叉）
  const sources = data.sources || [];
  renderDetail({
    sources,
    sqlText: data.sql,
    rowsCount: data.rows_count,
    sqlRows: data.sql_rows || [],
    sqlError: data.sql_error,
    trace: data.trace,
    cached: !!data.cached,
  });

  el("result-panel").hidden = false;
  el("result-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- 关键词策略选择 ---------- */
let currentRetriever = "bm25";

function initRetriever() {
  el("retriever-options").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-mode]");
    if (!btn) return;
    currentRetriever = btn.dataset.mode;
    [...el("retriever-options").children].forEach((b) =>
      b.classList.toggle("active", b === btn)
    );
  });
}

/* ---------- 召回对比：BM25 vs BGE-M3 稀疏向量 ---------- */
async function compareRecall() {
  const question = el("question-input").value.trim();
  if (!question) {
    el("question-input").focus();
    return;
  }

  const btn = el("compare-btn");
  btn.disabled = true;
  btn.textContent = "对比中…";

  try {
    const res = await apiFetch("/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, top_k: 10 }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    renderCompare(await res.json());
  } catch (err) {
    el("compare-panel").hidden = false;
    el("compare-note").textContent = "失败";
    el("compare-summary").textContent = `对比请求失败：${err.message}`;
    el("compare-bm25").innerHTML = "";
    el("compare-sparse").innerHTML = "";
  } finally {
    btn.disabled = false;
    btn.textContent = "对比召回";
  }
}

function renderCompareRow(r, uniqueList) {
  const cls = uniqueList.includes(r.source) ? "is-unique" : "";
  return `<div class="compare-row ${cls}">
      <span class="rk">#${r.rank}</span>
      <span class="src">${escapeHtml(r.source)}</span>
      <span class="sc">${r.score}</span>
      <div class="tx">${escapeHtml(r.text)}</div>
    </div>`;
}

function renderCompare(data) {
  el("compare-note").textContent = data.sparse_note || "同一问题，两条通路并排";

  el("compare-summary").innerHTML =
    `共同召回 <b>${(data.both_hit || []).length}</b> 个来源 · ` +
    `仅 BM25 找到 <b>${(data.only_bm25 || []).length}</b> 个 · ` +
    `仅稀疏向量找到 <b>${(data.only_sparse || []).length}</b> 个`;

  const empty = `<div class="compare-row">（无结果）</div>`;
  el("compare-bm25").innerHTML =
    (data.bm25 || []).map((r) => renderCompareRow(r, data.only_bm25 || [])).join("") || empty;
  el("compare-sparse").innerHTML =
    (data.sparse || []).map((r) => renderCompareRow(r, data.only_sparse || [])).join("") || empty;

  el("compare-panel").hidden = false;
  el("compare-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- 账号管理（系统管理员 / 企业管理员） ----------
 * 待审核账号列表 + 角色分配 + 停用/启用。
 * 企业管理员只能看到本企业的人；企业账号本身只有系统管理员能审核。
 * 这些限制在后端也各有一份（前端只是不给他点，后端才是拦住）。
 */
let ACCOUNTS = null;

async function loadAccounts() {
  try {
    const res = await apiFetch("/admin/users");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    ACCOUNTS = await res.json();
    renderAccounts();
  } catch (e) {
    el("accounts-status").textContent = `账号列表加载失败：${e.message}`;
  }
}

function renderAccounts() {
  if (!ACCOUNTS) return;
  const users = ACCOUNTS.users || [];
  const roles = ACCOUNTS.roles || [];
  const enterprises = ACCOUNTS.enterprises || [];
  const me = ACCOUNTS.me || {};
  const isSys = !!me.is_system_admin;
  const entMap = {};
  enterprises.forEach((e) => { entMap[e.id] = e; });

  // 同一个面板，两种管辖范围：系统管理员管全部，企业管理员管本企业成员。
  // 标题跟着范围变，避免企业管理员以为自己能看到别家企业的人。
  el("accounts-title").textContent = isSys ? "账号管理" : "本企业成员";
  el("accounts-intro").textContent = isSys
    ? "企业账号审核通过后创建企业库并生成邀请码；员工账号由所属企业管理员审核并分配角色。角色决定默认等级 → 决定能看到什么。"
    : "本企业员工由你审核并分配角色；把邀请码发给同事，他们注册时填写。企业账号的审核由系统管理员负责。";

  el("accounts-status").textContent =
    ACCOUNTS.scope === "all" ? `全部账号 ${users.length} 个` : `本企业账号 ${users.length} 个`;

  const myEnt = me.enterprise_id ? entMap[me.enterprise_id] : null;
  const box = el("enterprise-box");
  if (myEnt && myEnt.invite_code) {
    box.hidden = false;
    el("ent-name").textContent = myEnt.name;
    el("ent-code").textContent = myEnt.invite_code;
  } else {
    box.hidden = true;
  }

  const roleOptions = (current) =>
    roles
      .map(
        (r) =>
          `<option value="${r.value}" ${r.value === current ? "selected" : ""}>${escapeHtml(r.label)}（${r.level}）</option>`
      )
      .join("");

  el("accounts-list").innerHTML = users.length
    ? users
        .map((u) => {
          const ent = u.enterprise_id ? entMap[u.enterprise_id] : null;
          const pending = u.status === "pending";
          const statusCls =
            pending ? "is-warn" : u.status === "disabled" ? "is-danger" : "";
          return `<div class="account-row">
            <div class="acc-main">
              <span class="acc-name">${escapeHtml(u.display_name || u.username)}</span>
              <span class="acc-username">@${escapeHtml(u.username)}</span>
              <span class="pu-level">${escapeHtml(u.account_type_label || "")}</span>
              <span class="acc-status ${statusCls}">${escapeHtml(u.status_label || u.status)}</span>
              ${ent ? `<span class="pu-meta">${escapeHtml(ent.name)}</span>` : ""}
            </div>
            <div class="acc-actions">
              ${
                pending
                  ? u.account_type === "enterprise"
                    ? isSys
                      ? `<span class="pu-meta">企业账号</span>
                         <button type="button" class="perm-btn is-primary" data-approve="${u.id}">通过</button>`
                      : `<span class="pu-meta">企业账号 · 待系统管理员审核</span>`
                    : `<select data-approve-role="${u.id}">${roleOptions("cs")}</select>
                       <button type="button" class="perm-btn is-primary" data-approve="${u.id}">通过</button>`
                  : u.is_system_admin
                    ? `<span class="pu-meta">系统管理员</span>`
                    : u.is_enterprise_admin
                      ? `<span class="pu-meta">企业管理员</span>`
                      : `<select data-role="${u.id}">${roleOptions(u.role)}</select>`
              }
              ${
                u.is_system_admin || (u.account_type === "enterprise" && !isSys)
                  ? ""
                  : u.status === "disabled"
                    ? `<button type="button" class="perm-btn" data-enable="${u.id}">启用</button>`
                    : `<button type="button" class="perm-btn is-danger" data-disable="${u.id}">停用</button>`
              }
            </div>
            <div class="acc-meta">
              ${escapeHtml(u.created_at || "")}
              ${u.reviewed_by ? ` · 审核：${escapeHtml(u.reviewed_by)}` : ""}
              ${u.last_login_at ? ` · 最近登录 ${escapeHtml(u.last_login_at)}` : ""}
            </div>
          </div>`;
        })
        .join("")
    : `<div class="tp-empty">还没有账号</div>`;
}

async function approveAccount(id, role) {
  el("accounts-status").textContent = "审核中…";
  try {
    const res = await apiFetch(`/admin/users/${id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    await loadWhoami();
    el("accounts-status").textContent = "已通过审核，权限立即生效";
  } catch (e) {
    el("accounts-status").textContent = `审核失败：${e.message}`;
  }
}

async function changeAccountRole(id, role) {
  try {
    const res = await apiFetch(`/admin/users/${id}/role`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    await loadWhoami();
    el("accounts-status").textContent = "角色已更新，下一个请求即按新等级判定";
  } catch (e) {
    el("accounts-status").textContent = `改角色失败：${e.message}`;
  }
}

async function setAccountStatus(id, status) {
  try {
    const res = await apiFetch(`/admin/users/${id}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    await loadWhoami();
    el("accounts-status").textContent = status === "disabled" ? "账号已停用（会话立即失效）" : "账号已启用";
  } catch (e) {
    el("accounts-status").textContent = `操作失败：${e.message}`;
  }
}

/* ---------- 权限管理（管理员） ----------
 * 前端只负责把配置渲染成人能看懂的样子：
 * 能力目录、等级目录、角色清单、默认值全部来自 GET /admin/permissions，
 * 页面里不抄第二份权限表——否则加一个能力就会漏改一处。
 *
 * 改动是**即时生效**的：后端每次鉴权都重新解析身份并读最新配置，
 * 所以保存后只要再拉一次 /whoami，界面就和实际判定一致了。
 */
let PERM = null;

async function loadPermissions() {
  try {
    const res = await apiFetch("/admin/permissions");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    PERM = await res.json();
    renderPermissions();
  } catch (e) {
    el("perm-status").textContent = `权限配置加载失败：${e.message}`;
  }
}

function renderPermissions() {
  if (!PERM) return;
  const { config, capabilities, levels, roles } = PERM;
  const cfg = config || {};

  el("perm-path").textContent = PERM.path || "var/permissions.json";
  el("perm-status").textContent = cfg.updated_at
    ? `v${cfg.version} · ${cfg.updated_at} 由 ${cfg.updated_by || "-"} 保存`
    : "默认配置（尚未修改）";
  el("perm-hint").textContent = "";

  // 1) 等级 × 能力矩阵
  const head = capabilities
    .map((c) => `<th title="${escapeHtml(c.description)}">${escapeHtml(c.label)}</th>`)
    .join("");
  const body = levels
    .map((lv) => {
      const on = new Set((cfg.levels || {})[lv.value] || []);
      const cells = capabilities
        .map(
          (c) => `<td><input type="checkbox" data-level="${lv.value}" data-cap="${c.value}"
                    title="${escapeHtml(lv.label)} · ${escapeHtml(c.label)}"
                    ${on.has(c.value) ? "checked" : ""}></td>`
        )
        .join("");
      const name = String(lv.label).replace(lv.value, "").trim();
      return `<tr>
        <th title="${escapeHtml(lv.description)}"><span class="perm-lv">${lv.value}</span>${escapeHtml(name)}</th>
        ${cells}
      </tr>`;
    })
    .join("");
  el("perm-matrix").innerHTML = `<thead><tr><th>等级</th>${head}</tr></thead><tbody>${body}</tbody>`;

  // 2) 角色默认等级（guest 固定 L0，不给入口）
  el("perm-roles").innerHTML = roles
    .map((r) => {
      if (r.value === "guest") {
        return `<div class="perm-role">
          <span class="perm-role-name">${escapeHtml(r.label)}</span>
          <span class="pu-level">L0</span>
          <span class="perm-role-tag">未识别身份固定无权限</span>
        </div>`;
      }
      const opts = levels
        .map(
          (lv) =>
            `<option value="${lv.value}" ${r.level === lv.value ? "selected" : ""}>${escapeHtml(lv.label)}</option>`
        )
        .join("");
      return `<div class="perm-role">
        <span class="perm-role-name">${escapeHtml(r.label)}</span>
        <select data-role="${r.value}">${opts}</select>
        <span class="perm-role-tag">默认等级</span>
      </div>`;
    })
    .join("");

  // 3) 人员授权
  el("perm-level").innerHTML = levels
    .map((lv) => `<option value="${lv.value}">${escapeHtml(lv.label)}</option>`)
    .join("");
  const users = cfg.user_levels || {};
  const ids = Object.keys(users);
  el("perm-users").innerHTML = ids.length
    ? ids
        .map((uid) => {
          const item = users[uid] || {};
          return `<div class="perm-user">
            <span class="pu-id">${escapeHtml(uid)}</span>
            <span class="pu-level">${escapeHtml(item.level || "-")}</span>
            ${item.note ? `<span class="pu-note">${escapeHtml(item.note)}</span>` : ""}
            <span class="pu-meta">${escapeHtml(item.updated_by || "")} ${escapeHtml(item.updated_at || "")}</span>
            <button type="button" class="perm-btn is-danger" data-revoke="${escapeHtml(uid)}">撤销</button>
          </div>`;
        })
        .join("")
    : `<div class="tp-empty">还没有人员授权——所有人按角色默认等级判定</div>`;
}

/* 收集矩阵 + 角色下拉 → 保存请求体 */
function collectPermissions() {
  const levels = {};
  document.querySelectorAll("#perm-matrix input[data-level]").forEach((box) => {
    if (!box.checked) return;
    (levels[box.dataset.level] = levels[box.dataset.level] || []).push(box.dataset.cap);
  });
  const role_levels = {};
  document.querySelectorAll("#perm-roles select[data-role]").forEach((sel) => {
    role_levels[sel.dataset.role] = sel.value;
  });
  return { levels, role_levels };
}

async function savePermissions() {
  const hint = el("perm-hint");
  hint.textContent = "保存中…";
  try {
    const res = await apiFetch("/admin/permissions", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectPermissions()),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    await loadWhoami(); // 重新拉能力：后端已按新配置判定，界面要跟上
    el("perm-hint").textContent = "已保存，立即生效";
  } catch (e) {
    hint.textContent = `保存失败：${e.message}`;
  }
}

/* 典型操作：L1~L4 全部可访问全部信息（勾满后直接保存） */
async function openAllPermissions() {
  document.querySelectorAll("#perm-matrix input[data-level]").forEach((box) => {
    box.checked = true;
  });
  await savePermissions();
}

async function resetPermissions() {
  el("perm-hint").textContent = "正在恢复默认…";
  try {
    const res = await apiFetch("/admin/permissions/reset", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    await loadWhoami();
    el("perm-hint").textContent = "已恢复默认配置";
  } catch (e) {
    el("perm-hint").textContent = `恢复失败：${e.message}`;
  }
}

/* 典型操作：把某个销售人员从 L1 提到 L4（覆盖角色等级） */
async function grantPermission(event) {
  event.preventDefault();
  const hint = el("perm-grant-hint");
  const target = el("perm-user").value.trim();
  const level = el("perm-level").value;
  if (!target) {
    hint.textContent = "请先填用户 ID";
    return;
  }
  hint.textContent = "提交中…";
  try {
    const res = await apiFetch("/admin/permissions/grant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_type: "user", target, level }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    el("perm-user").value = "";
    await loadWhoami();
    el("perm-grant-hint").textContent = `${target} → ${level}，已生效`;
  } catch (e) {
    hint.textContent = `授权失败：${e.message}`;
  }
}

async function revokeUserPermission(uid) {
  try {
    const res = await apiFetch(`/admin/permissions/user/${encodeURIComponent(uid)}`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    await loadWhoami();
    el("perm-grant-hint").textContent = `已撤销 ${uid} 的人员授权`;
  } catch (e) {
    el("perm-grant-hint").textContent = `撤销失败：${e.message}`;
  }
}

/* ---------- 初始化 ---------- */
document.addEventListener("DOMContentLoaded", async () => {
  renderExamples();
  initRetriever();
  el("compare-btn").addEventListener("click", compareRecall);

  // 退出：服务端删会话 + 清 Cookie。只清 Cookie 不算退出（令牌还能用）
  el("logout-btn").addEventListener("click", async () => {
    try {
      await fetch("/auth/logout", { method: "POST" });
    } finally {
      window.location.href = "/login";
    }
  });

  // 账号管理：通过审核 / 改角色 / 停用启用
  el("accounts-list").addEventListener("click", (e) => {
    const approve = e.target.closest("button[data-approve]");
    if (approve) {
      const id = approve.dataset.approve;
      const sel = document.querySelector(`select[data-approve-role="${id}"]`);
      approveAccount(id, sel ? sel.value : "cs");
      return;
    }
    const disable = e.target.closest("button[data-disable]");
    if (disable) return setAccountStatus(disable.dataset.disable, "disabled");
    const enable = e.target.closest("button[data-enable]");
    if (enable) return setAccountStatus(enable.dataset.enable, "active");
  });
  el("accounts-list").addEventListener("change", (e) => {
    const sel = e.target.closest("select[data-role]");
    if (sel) changeAccountRole(sel.dataset.role, sel.value);
  });

  // 权限管理面板：元素常驻，事件只绑一次（内容是重新渲染的，容器本身不换）
  el("perm-save").addEventListener("click", savePermissions);
  el("perm-open-all").addEventListener("click", openAllPermissions);
  el("perm-reset").addEventListener("click", resetPermissions);
  el("perm-grant-form").addEventListener("submit", grantPermission);
  el("perm-matrix").addEventListener("change", () => {
    el("perm-hint").textContent = "有未保存的改动";
  });
  el("perm-users").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-revoke]");
    if (btn) revokeUserPermission(btn.dataset.revoke);
  });

  // 先拿当前账号（未登录会被 apiFetch 直接带回 /login），再决定渲染什么
  await loadWhoami();

  el("detail-fold").addEventListener("click", () => {
    const body = el("detail-body");
    body.hidden = !body.hidden;
    el("detail-fold").textContent = body.hidden ? "展开" : "收起";
  });

  el("ask-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = el("question-input").value.trim();
    if (!q) {
      el("question-input").focus();
      return;
    }
    ask(q);
  });

  el("question-input").addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      el("ask-form").requestSubmit();
    }
  });
});
