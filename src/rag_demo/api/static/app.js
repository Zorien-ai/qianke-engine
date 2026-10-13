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

/* ---------- 数据概况 ---------- */
async function loadStats() {
  const grid = el("stats-grid");
  const status = el("stats-status");
  try {
    const res = await fetch("/stats");
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
  return escapeHtml(text).replace(
    /\[来源\s*(\d+)\]/g,
    '<span class="cite">[来源$1]</span>'
  );
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
    const res = await fetch("/qa/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, retriever: currentRetriever }),
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
          if (data.cached) btnText.textContent = "命中缓存";
        } else if (event === "delta") {
          if (!resultShown) {
            // 首个片段到达——此刻才让结果区出现，避免空白面板闪一下
            renderStreamShell(route, sources, sqlText, rowsCount, data.cached);
            resultShown = true;
          }
          if (firstCharAt === null) {
            firstCharAt = performance.now();
            btnText.textContent = "生成中…";
          }
          answer += data.delta;
          el("answer-body").innerHTML = formatAnswer(answer);
        } else if (event === "error") {
          throw new Error(data.message || "服务端错误");
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
    el("error-text").textContent = `请求失败：${err.message}`;
  } finally {
    btn.disabled = false;
    spinner.hidden = true;
    btnText.textContent = "提问";
  }
}

/* 流式结果区：先搭好骨架，后续只更新答案文本 */
function renderStreamShell(route, sources, sqlText, rowsCount, cached) {
  const badges = [
    `<span class="badge ${route}">${String(route).toUpperCase()}</span>`,
    `<span class="badge time" id="elapsed-badge">生成中…</span>`,
  ];
  if (cached) badges.push(`<span class="badge time">缓存命中</span>`);
  el("result-badges").innerHTML = badges.join("");

  el("answer-body").innerHTML = "";

  if (sqlText) {
    el("sql-block").hidden = false;
    el("sql-body").textContent = sqlText;
    el("rows-count").textContent = `共 ${rowsCount ?? 0} 行`;
  } else {
    el("sql-block").hidden = true;
  }

  if (sources.length) {
    el("sources-block").hidden = false;
    el("sources-list").innerHTML = sources
      .map((s) => {
        const name = s.source || "unknown";
        let cls = "is-sql";
        if (name.endsWith(".md")) cls = "is-wiki";
        else if (name === "user_profile") cls = "is-profile";
        return `<span class="source-chip ${cls}">[来源${s.index}] ${name}</span>`;
      })
      .join("");
  } else {
    el("sources-block").hidden = true;
  }

  el("result-panel").hidden = false;
  el("result-panel").scrollIntoView({ behavior: "smooth", block: "start" });
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

  // SQL
  if (data.sql) {
    el("sql-block").hidden = false;
    el("sql-body").textContent = data.sql;
    el("rows-count").textContent = `共 ${data.rows_count ?? 0} 行`;
  } else {
    el("sql-block").hidden = true;
  }

  // 来源
  const sources = data.sources || [];
  if (sources.length) {
    el("sources-block").hidden = false;
    el("sources-list").innerHTML = sources
      .map((s) => {
        const name = s.source || "unknown";
        let cls = "is-sql";
        if (name.endsWith(".md")) cls = "is-wiki";
        else if (name === "user_profile") cls = "is-profile";
        return `<span class="source-chip ${cls}">[来源${s.index}] ${name}</span>`;
      })
      .join("");
  } else {
    el("sources-block").hidden = true;
  }

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
    const res = await fetch("/search", {
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
document.addEventListener("DOMContentLoaded", () => {
  loadStats();
  renderExamples();
  initRetriever();
  el("compare-btn").addEventListener("click", compareRecall);

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
