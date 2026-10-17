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
 * 能力清单来自后端 /whoami，前端**不硬编码权限表**——两份真源必然改漏一处。
 *
 * ⚠ 前端隐藏面板只是"不设计入口"，不是权限。真正的拦截在后端
 *   （直接 curl 接口绕不过去）。这里隐藏是因为"用不了的功能不该出现"，
 *   而不是因为"藏起来就安全"。
 */
let currentRole = null;
let CAPS = {};
let TOPK_RANGE = { min: 1, max: 30 };

/* 所有请求都带上当前角色（后端按它裁剪响应） */
function apiFetch(url, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}) } };
  if (currentRole) opts.headers["X-Role"] = currentRole;
  return fetch(url, opts);
}

async function loadWhoami() {
  // 第一次（可能不带角色）：只为拿"可选角色清单"，避免把角色写死在前端
  let info = await (await fetch("/whoami")).json();

  const select = el("role-select");
  if (!select.options.length) {
    // 只列出**可用**的角色。未识别身份（guest）不提供入口——
    // 用不了的东西直接不呈现，而不是让他点一下再告知没权限。
    const usable = (info.roles || []).filter((r) => r.usable);
    select.innerHTML = usable
      .map((r) => `<option value="${r.value}">${r.label}</option>`)
      .join("");
    select.value = currentRole || (usable.length ? usable[usable.length - 1].value : "");
  }

  currentRole = select.value;
  const mine = await (await apiFetch("/whoami")).json(); // 带上角色，拿自己的能力清单
  CAPS = mine.can || {};
  TOPK_RANGE = mine.topk_range || TOPK_RANGE;

  // 权限申请只做声明、不做处理：尚未接入电商系统，页面上说清楚
  el("role-note").textContent = mine.note || "";
  applyCapabilities();

  el("stats-panel").hidden = !CAPS.stats;
  if (CAPS.stats) loadStats();
  return mine;
}

function applyCapabilities() {
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

  // 看不到任何过程信息时，把上一身份留下的面板清掉，避免残留
  if (!CAPS.sources && !CAPS.sql && !CAPS.internals) el("detail-panel").hidden = true;

  el("ask-btn").disabled = !CAPS.ask;
  el("ask-hint").textContent = CAPS.ask
    ? "按 Ctrl / Cmd + Enter 快速提交"
    : "当前身份无权提问";
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

  renderDetail({ sources, sqlText, rowsCount, sqlRows, sqlError, trace, question });

  el("result-panel").hidden = false;
  el("result-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- 数据来源与检索过程（独立面板） ---------- */
function renderDetail({ sources, sqlText, rowsCount, sqlRows, sqlError, trace, question }) {
  const panel = el("detail-panel");

  // 闲聊：没有来源、没有 SQL、没有留痕，这个过程区没有意义
  if (!sources.length && !sqlText && !trace) {
    panel.hidden = true;
    // 只 hidden 不清内容的话，下一次面板重新出现时若某个子块没被重写，
    // 旧 DOM 会留在那儿——表现就是「溯源不刷新」。
    el("detail-question").textContent = "";
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
  //   · 真的命中缓存 -> 缓存里没有过程数据
  // 混着写的话，用户会以为「换了身份还在用旧缓存」（2026-10-17 实测反馈）。
  const canInternals = !!CAPS.internals;
  const hasTrace = !!trace;

  // 1) 原问题
  el("detail-question").textContent =
    (trace && trace.question) || question || "（本次请求未留痕）";

  // 2) 走的路径 + 改写的路径
  const variants = (trace && trace.variants) || [];
  const chips = [`<span class="tp-chip">检索路 <b>${variants.length}</b> 条</span>`];
  if (hasTrace) {
    chips.push(
      trace.need_sql
        ? `<span class="tp-chip is-sql">LLM 判定：需要 SQL</span>`
        : `<span class="tp-chip">LLM 判定：不需要 SQL</span>`
    );
  } else if (!canInternals) {
    chips.push(`<span class="tp-chip is-warn">当前身份无权查看检索过程</span>`);
  } else {
    chips.push(`<span class="tp-chip is-warn">本次命中缓存，未存过程数据</span>`);
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
  el("trace-flow").innerHTML = hasTrace
    ? `
    <span class="tp-node">各路并行召回 <b>${totalHits}</b></span>
    <span class="tp-arrow">→</span>
    <span class="tp-node">${profileText} · ${wikiText}</span>
    <span class="tp-arrow">→</span>
    <span class="tp-node">合并去重 <b>${merged}</b></span>
    <span class="tp-arrow">→</span>
    <span class="tp-node is-final">入上下文 <b>${sources.length}</b></span>`
    : `<span class="tp-empty">${
        canInternals ? "本次命中缓存，未存过程数据" : "当前身份无权查看检索链路"
      }</span>`;

  // 4) 数据来源（名称 + 分数 + 命中它的检索式 + 内容）
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

  // 5) SQL 语句与查询结果
  const sqlSec = el("trace-sql-section");
  if (sqlText) {
    sqlSec.hidden = false;
    el("sql-body").textContent = sqlText;
    // 总行数用后端的 rows_count（真实行数），不能用 sqlRows.length——
    // 后者是回传数组，已被 brief_rows 截到 20 行，>20 行时会显示成「共 20 行」，
    // 与顶部徽章的「返回 N 行」自相矛盾。
    const sqlTotal = typeof rowsCount === "number" ? rowsCount : sqlRows.length;
    el("trace-sql-note").textContent = sqlError
      ? `执行失败：${sqlError}`
      : sqlTotal > sqlRows.length
        ? `共 ${sqlTotal} 行，下列前 ${sqlRows.length} 行`
        : `共 ${sqlTotal} 行`;
    el("trace-sql-rows").innerHTML = sqlRows.length
      ? `<table class="tp-table">${sqlRows
          .map((r) => `<tr>${r.map((c) => `<td>${escapeHtml(String(c))}</td>`).join("")}</tr>`)
          .join("")}</table>`
      : `<div class="tp-empty">${sqlError ? escapeHtml(sqlError) : "（空结果）"}</div>`;
  } else {
    sqlSec.hidden = true;
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

/* ---------- 初始化 ---------- */
document.addEventListener("DOMContentLoaded", async () => {
  renderExamples();
  initRetriever();
  el("compare-btn").addEventListener("click", compareRecall);

  // 切换身份：必须先清空上一个身份留下的结果。
  // 不清的话，降权后旧的高权内容还挂在页面上，会让人以为"权限没生效"。
  el("role-select").addEventListener("change", async () => {
    currentRole = el("role-select").value;
    el("result-panel").hidden = true;
    el("detail-panel").hidden = true;
    el("compare-panel").hidden = true;
    el("error-panel").hidden = true;
    el("answer-body").innerHTML = "";
    await loadWhoami();
  });

  // 先定身份，再决定渲染什么（loadStats 由 applyCapabilities 按能力触发）
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
