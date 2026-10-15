/* 用户画像 RAG 智能问答 —— 前端交互 */

const EXAMPLE_QUESTIONS = [
  "高客单、喜欢美妆的女性用户有哪些",
  "深圳的钻石会员都是什么特征",
  "高价值用户怎么定义的",
  "流失预警的判定标准",
  "用户说优惠券过期了怎么办",
  "美妆用户的客单价分布",
  "本周高价值用户规模有多少",
  "母婴偏好用户在哪些城市集中",
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

    const cards = [
      { value: data.users.toLocaleString(), label: "用户画像", extra: `共 ${data.profiles_columns} 个结构化字段` },
      { value: data.docs, label: "知识库文档", extra: `切分为 ${data.chunks} 个分块` },
      { value: data.cities, label: "覆盖城市", extra: `品类 ${data.categories} 类` },
      { value: data.diamond_ratio, label: "钻石会员占比", extra: levelText || "—" },
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

function formatAnswer(text) {
  let html = escapeHtml(text);
  // 看不到来源列表的身份：[来源N] 指向一个用户看不见的东西，留着比去掉更糟。
  // 流式路径必须在这里处理——服务端按 delta 分片正则匹配会被切片边界漏掉。
  if (!CAPS.sources) html = html.replace(/\[来源\s*\d+\]/g, "");
  return html.replace(/\[来源\s*(\d+)\]/g, '<span class="cite">[来源$1]</span>');
}

/* ---------- 提交提问（流式）---------- */
async function ask(question) {
  const btn = el("ask-btn");
  const spinner = btn.querySelector(".spinner");
  const btnText = btn.querySelector(".btn-text");

  el("result-panel").hidden = true;
  el("error-panel").hidden = true;
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
    let sources = [];
    let sqlText = "";
    let rowsCount = null;
    let sqlRows = [];
    let sqlError = null;
    let trace = null;
    let cached = false;
    let resultShown = false;

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
        } else if (event === "delta") {
          if (!resultShown) {
            // 首个片段到达——此刻才让结果区出现，避免空白面板闪一下
            renderStreamShell({
              route, sources, sqlText, rowsCount,
              sqlRows, sqlError, trace, cached,
            });
            resultShown = true;
          }
          if (firstCharAt === null) {
            firstCharAt = performance.now();
            btnText.textContent = "生成中…";
          }
          answer += data.delta;
          el("answer-body").innerHTML = formatAnswer(answer);
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
function renderStreamShell({ route, sources, sqlText, rowsCount, sqlRows, sqlError, trace, cached }) {
  const badges = [
    `<span class="badge ${route}">${String(route).toUpperCase()}</span>`,
    `<span class="badge time" id="elapsed-badge">生成中…</span>`,
  ];
  if (cached) badges.push(`<span class="badge time">缓存命中</span>`);
  el("result-badges").innerHTML = badges.join("");

  el("answer-body").innerHTML = "";

  renderDetail({ sources, sqlText, rowsCount, sqlRows, sqlError, trace });

  el("result-panel").hidden = false;
  el("result-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- 数据来源与检索过程（独立面板） ---------- */
function renderDetail({ sources, sqlText, rowsCount, sqlRows, sqlError, trace }) {
  const panel = el("detail-panel");

  // 闲聊：没有来源、没有 SQL、没有留痕，这个过程区没有意义
  if (!sources.length && !sqlText && !trace) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  el("detail-body").hidden = false;
  el("detail-fold").textContent = "收起";

  // 1) 原问题
  el("detail-question").textContent = (trace && trace.question) || "（缓存结果，未留痕）";

  // 2) 走的路径 + 改写的路径
  const variants = (trace && trace.variants) || [];
  const chips = [`<span class="tp-chip">检索路 <b>${variants.length}</b> 条</span>`];
  if (trace) {
    chips.push(
      trace.need_sql
        ? `<span class="tp-chip is-sql">LLM 判定：需要 SQL</span>`
        : `<span class="tp-chip">LLM 判定：不需要 SQL</span>`
    );
    if (trace.sql_blocked) {
      chips.push(`<span class="tp-chip is-warn">SQL 路被「预测类」规则否决</span>`);
    }
  } else {
    chips.push(`<span class="tp-chip is-warn">缓存结果，无过程数据</span>`);
  }
  el("trace-plan").innerHTML = chips.join("");

  el("trace-variants").innerHTML =
    variants
      .map(
        (v) => `
      <div class="tp-variant">
        <div class="tp-variant-head">
          <span class="tp-strategy">${escapeHtml(v.strategy || "-")}</span>
          <span class="tp-count">召回 ${v.hit_count ?? 0} 条 · 精排留 ${v.kept_count ?? 0} 条</span>
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

  // 3) 收敛链路：各路并行召回 → 各路分来源精排 → 合并去重 → 入上下文
  const totalHits = variants.reduce((n, v) => n + (v.hit_count ?? 0), 0);
  const merged = (trace && trace.fused_count) ?? 0;
  const kept = (trace && trace.kept_per_route) || {};
  const keptText =
    kept.profile != null && kept.wiki != null
      ? `画像<b>${kept.profile}</b>+文档<b>${kept.wiki}</b>`
      : "分来源";
  el("trace-flow").innerHTML = `
    <span class="tp-node">各路并行召回 <b>${totalHits}</b></span>
    <span class="tp-arrow">→</span>
    <span class="tp-node">各路精排 ${keptText}</span>
    <span class="tp-arrow">→</span>
    <span class="tp-node">合并去重 <b>${merged}</b></span>
    <span class="tp-arrow">→</span>
    <span class="tp-node is-final">入上下文 <b>${sources.length}</b></span>`;

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
        <div class="ds-text">${escapeHtml(s.text || "")}</div>
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
  el("answer-body").innerHTML = formatAnswer(data.answer || "（无内容）");

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
