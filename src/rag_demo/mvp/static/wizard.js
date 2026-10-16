/* 搭建向导（MVP M1）—— 上传 → 确认字段 → 一键构建 → 提问
 *
 * 这一层只做「取数据 + 渲染」，不写业务规则：
 * 字段怎么认、进度怎么算、答案从哪来，全在服务端（现在的 mock，M2 换真实实现）。
 * 前端唯一自己做的事是**读取本地文件**——这不是绕过后端，
 * 而是上传前就能给出「几行、什么编码」的即时反馈，避免先把 10MB 传上去再告诉用户格式不对。
 */

const el = (id) => document.getElementById(id);

const state = {
  csvFiles: [],      // {name, size, encoding, rowCount, columns}
  mdFiles: [],       // {name, size, encoding, text}
  analysis: null,    // /api/wizard/analyze 的结果
  taskId: null,
  pollTimer: null,
  history: [],       // {question, answer, sources, time}
};

let maxStep = 1; // 已经走到过的最远步骤，决定步骤条能回退到哪

/* ================= 通用工具 ================= */

function showMsg(node, text, kind = "is-error") {
  node.className = "inline-msg " + kind;
  node.textContent = text;
  node.hidden = !text;
}

function clearMsg(node) { node.hidden = true; node.textContent = ""; }

function fmtSize(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1024 / 1024).toFixed(2) + " MB";
}

/* 统一请求封装：把后端/网络错误一律翻译成一句能看懂的中文，绝不把异常抛到页面上 */
async function api(url, options = {}) {
  let resp;
  try {
    resp = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (e) {
    throw new Error("连接不上服务，请确认服务还在运行（终端窗口别关掉），然后重试。");
  }
  let data = null;
  try { data = await resp.json(); } catch (e) { /* 非 JSON 响应，下面统一按状态码处理 */ }
  if (!resp.ok) {
    const detail = (data && (data.detail || data.message)) || `服务返回了 ${resp.status} 错误。`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

/* ================= 文件读取（在浏览器里完成） ================= */

/* 编码识别：先看 BOM，再试 UTF-8 严格解码，失败才退回 GBK。
 * 顺序不能反——GBK 几乎能解码任意字节流，先试 GBK 会把 UTF-8 中文读成乱码。 */
function decodeBuffer(buf) {
  const bytes = new Uint8Array(buf);
  if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    return { text: new TextDecoder("utf-8").decode(buf), encoding: "utf-8(BOM)" };
  }
  try {
    return { text: new TextDecoder("utf-8", { fatal: true }).decode(buf), encoding: "utf-8" };
  } catch (e) {
    try {
      return { text: new TextDecoder("gbk").decode(buf), encoding: "gbk" };
    } catch (e2) {
      return { text: new TextDecoder("utf-8").decode(buf), encoding: "未知(可能乱码)" };
    }
  }
}

function detectDelimiter(line) {
  let best = ",", bestCount = 0;
  for (const d of [",", "\t", ";", "|"]) {
    const n = line.split(d).length - 1;
    if (n > bestCount) { best = d; bestCount = n; }
  }
  return best;
}

/* 逐字符切一行，处理引号包裹的逗号——"深圳市,南山区" 不能被当成两列 */
function splitCsvLine(line, delim) {
  const out = [];
  let cur = "", inQuote = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuote) {
      if (ch === '"') {
        if (line[i + 1] === '"') { cur += '"'; i++; } else { inQuote = false; }
      } else { cur += ch; }
    } else if (ch === '"') {
      inQuote = true;
    } else if (ch === delim) {
      out.push(cur); cur = "";
    } else { cur += ch; }
  }
  out.push(cur);
  return out;
}

async function parseCsv(file) {
  const { text, encoding } = decodeBuffer(await file.arrayBuffer());
  const lines = text.split(/\r\n|\n|\r/);
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  const header = lines[0] || "";
  const delim = detectDelimiter(header);
  const columns = splitCsvLine(header, delim).map((s) => s.trim()).filter((s) => s !== "");
  return {
    name: file.name,
    size: file.size,
    encoding,
    // 行数是**估算**：带换行的引号字段会被多算，页面上也如实写「约」
    rowCount: Math.max(0, lines.length - 1),
    columns,
  };
}

async function parseMd(file) {
  const { text, encoding } = decodeBuffer(await file.arrayBuffer());
  return { name: file.name, size: file.size, encoding, text };
}

function isMdFile(file) {
  return /\.(md|markdown)$/i.test(file.name);
}

/* ================= 第 1 步：上传 ================= */

async function addFiles(fileList, kind) {
  const files = Array.from(fileList || []);
  if (!files.length) return;

  const rejected = [];
  for (const f of files) {
    try {
      if (isMdFile(f)) {
        if (state.mdFiles.some((x) => x.name === f.name)) { rejected.push(`${f.name}（已存在，跳过）`); continue; }
        state.mdFiles.push(await parseMd(f));
      } else if (/\.csv$/i.test(f.name)) {
        if (kind === "md") { rejected.push(`${f.name}（不是 .md 文档）`); continue; }
        if (state.csvFiles.some((x) => x.name === f.name)) { rejected.push(`${f.name}（已存在，跳过）`); continue; }
        state.csvFiles.push(await parseCsv(f));
      } else {
        rejected.push(`${f.name}（只支持 .csv 和 .md）`);
      }
    } catch (e) {
      rejected.push(`${f.name}（读取失败：${e.message}）`);
    }
  }

  renderFileLists();
  clearMsg(el("msg-step1"));
  if (rejected.length) {
    showMsg(el("msg-step1"), "以下文件没有被加入：\n· " + rejected.join("\n· "), "is-warn");
  }
}

function renderFileLists() {
  const csvList = el("csv-list");
  const mdList = el("md-list");

  el("csv-count").textContent = `${state.csvFiles.length} 个`;
  el("md-count").textContent = `${state.mdFiles.length} 个`;

  if (!state.csvFiles.length) {
    csvList.innerHTML = '<li class="fl-empty">还没有文件</li>';
  } else {
    csvList.innerHTML = state.csvFiles.map((f, i) => `
      <li>
        <span class="fl-name">${escapeHtml(f.name)}</span>
        <span class="fl-meta">约 ${f.rowCount.toLocaleString()} 行 · ${f.columns.length} 列 · ${escapeHtml(f.encoding)} · ${fmtSize(f.size)}</span>
        <button type="button" class="fl-remove" data-kind="csv" data-index="${i}" title="移除">×</button>
      </li>`).join("");
  }

  if (!state.mdFiles.length) {
    mdList.innerHTML = '<li class="fl-empty">还没有文件</li>';
  } else {
    mdList.innerHTML = state.mdFiles.map((f, i) => `
      <li>
        <span class="fl-name">${escapeHtml(f.name)}</span>
        <span class="fl-meta">${escapeHtml(f.encoding)} · ${fmtSize(f.size)}</span>
        <button type="button" class="fl-remove" data-kind="md" data-index="${i}" title="移除">×</button>
      </li>`).join("");
  }
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* 拖拽：必须同时阻止 dragover 的默认行为，否则浏览器会直接打开文件 */
function bindDropzone(zoneId, kind) {
  const zone = el(zoneId);
  const input = el(zoneId === "dz-csv" ? "file-csv" : "file-md");

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
  });
  input.addEventListener("change", () => { addFiles(input.files, kind); input.value = ""; });

  ["dragenter", "dragover"].forEach((ev) =>
    zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("is-over"); }));
  ["dragleave", "drop"].forEach((ev) =>
    zone.addEventListener(ev, () => zone.classList.remove("is-over")));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    addFiles(e.dataTransfer.files, kind);
  });
}

/* ================= 步骤切换 ================= */

function showStep(n) {
  document.querySelectorAll(".step-panel").forEach((p) => {
    p.hidden = Number(p.dataset.step) !== n;
  });
  maxStep = Math.max(maxStep, n);
  document.querySelectorAll("#stepper li").forEach((li) => {
    const s = Number(li.dataset.step);
    li.classList.toggle("is-active", s === n);
    li.classList.toggle("is-done", s < n);
    li.classList.toggle("reachable", s <= maxStep);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ================= 第 2 步：字段确认 ================= */

async function goAnalyze() {
  const btn = el("btn-to-step2");
  clearMsg(el("msg-step1"));

  if (!state.csvFiles.length && !state.mdFiles.length) {
    showMsg(el("msg-step1"), "还没有文件。请先拖入文件，或点「用示例数据填满」直接体验流程。", "is-warn");
    return;
  }

  btn.disabled = true;
  btn.textContent = "正在识别…";
  try {
    const data = await api("/api/wizard/analyze", {
      method: "POST",
      body: JSON.stringify({
        csv_files: state.csvFiles.map((f) => ({
          name: f.name, size: f.size, encoding: f.encoding,
          row_count: f.rowCount, columns: f.columns,
        })),
        md_files: state.mdFiles.map((f) => ({ name: f.name, size: f.size, text: f.text })),
      }),
    });
    state.analysis = data;
    renderAnalysis(data);
    showStep(2);
  } catch (e) {
    showMsg(el("msg-step1"), e.message, "is-error");
  } finally {
    btn.disabled = false;
    btn.textContent = "下一步：确认字段";
  }
}

function renderAnalysis(data) {
  const s = data.summary;
  el("analyze-summary").innerHTML = `
    <div class="summary-chip"><b>${s.csv_count}</b>个数据文件</div>
    <div class="summary-chip"><b>${s.md_count}</b>篇规则文档</div>
    <div class="summary-chip"><b>${s.total_rows.toLocaleString()}</b>行交易记录</div>
    <div class="summary-chip"><b>${s.detected_fields}/${s.total_fields}</b>个字段自动识别</div>
    <div class="summary-chip"><b>${s.total_chunks}</b>个预计分块</div>`;

  el("field-table").innerHTML =
    `<div class="field-row is-head"><span>字段</span><span>对应的数据列</span><span>状态</span></div>` +
    data.fields.map((f) => `
      <div class="field-row ${f.detected ? "" : "is-missed"}">
        <div class="f-name">
          ${escapeHtml(f.label)}${f.required ? '<span class="f-req">关键</span>' : ""}
          <span class="f-hint">${escapeHtml(f.hint)}</span>
        </div>
        <div>
          <select class="f-select" data-key="${f.key}">
            <option value="">（不使用这个字段）</option>
            ${f.options.map((c) => `<option value="${escapeHtml(c)}"${c === f.column ? " selected" : ""}>${escapeHtml(c)}</option>`).join("")}
          </select>
        </div>
        <div class="f-status ${f.detected ? "ok" : "miss"}">
          ${f.detected ? "已自动识别" : "请手动选择"}
        </div>
      </div>`).join("");

  if (!data.docs.length) {
    el("doc-table").innerHTML = '<div class="doc-row">没有上传规则文档，只能做数据类查询。</div>';
  } else {
    el("doc-table").innerHTML =
      `<div class="doc-row is-head"><span>文档</span><span>标题结构</span><span>预计分块</span></div>` +
      data.docs.map((d) => `
        <div class="doc-row ${d.warning ? "is-warn" : ""}">
          <span class="doc-name">${escapeHtml(d.name)}</span>
          <span class="heading-tags">
            <span class="htag ${d.h1 ? "" : "zero"}">一级 ${d.h1}</span>
            <span class="htag ${d.h2 ? "" : "zero"}">二级 ${d.h2}</span>
            <span class="htag ${d.h3 ? "" : "zero"}">三级 ${d.h3}</span>
          </span>
          <span class="doc-chunks">${d.est_chunks} 块</span>
        </div>`).join("");
  }

  const warnBox = el("warn-list");
  if (data.warnings.length) {
    warnBox.innerHTML = data.warnings.map((w) => `<div class="warn-item">⚠<span>${escapeHtml(w)}</span></div>`).join("");
    warnBox.hidden = false;
  } else {
    warnBox.hidden = true;
  }
}

function collectFields() {
  const fields = {};
  document.querySelectorAll(".f-select").forEach((sel) => { fields[sel.dataset.key] = sel.value || null; });
  return fields;
}

/* ================= 第 3 步：构建 ================= */

function buildPayload() {
  return {
    fields: collectFields(),
    csv_files: state.csvFiles.map((f) => ({
      name: f.name, size: f.size, encoding: f.encoding,
      row_count: f.rowCount, columns: f.columns,
    })),
    md_files: state.mdFiles.map((f) => ({ name: f.name, size: f.size, text: f.text })),
    simulate_failure: el("sim-fail").checked,
  };
}

async function startBuild() {
  const btn = el("btn-start-build");
  clearMsg(el("msg-step2"));
  el("build-error").hidden = true;
  el("build-retry").hidden = true;

  btn.disabled = true;
  btn.textContent = "启动中…";
  try {
    const res = await api("/api/wizard/build", { method: "POST", body: JSON.stringify(buildPayload()) });
    state.taskId = res.task_id;
    el("progress-wrap").hidden = false;
    el("build-intro").hidden = true;
    renderProgress({ percent: 0, steps: [], note: "正在准备…", processed: 0, total: 0 });
    pollBuild();
  } catch (e) {
    showMsg(el("msg-step2"), e.message, "is-error");
    el("msg-step2").scrollIntoView({ block: "center", behavior: "smooth" });
    btn.disabled = false;
    btn.textContent = "开始构建";
  }
}

function pollBuild() {
  // 原型里 0.8 秒一次：假构建总共才几秒，2 秒轮询只有两三次更新，看不出运动。
  // M2 接真实任务时改回 2000ms 的节奏（进度本来就更新不了那么快）。
  state.pollTimer = setTimeout(async () => {
    try {
      const task = await api(`/api/wizard/build/${state.taskId}`);
      renderProgress(task);
      if (task.status === "running") {
        pollBuild();
      } else if (task.status === "done") {
        onBuildDone(task);
      } else {
        onBuildFailed(task);
      }
    } catch (e) {
      el("build-error").hidden = false;
      el("build-error").innerHTML =
        `<div class="err-title">构建进度读取失败</div>${escapeHtml(e.message)}`;
      el("build-retry").hidden = false;
      el("btn-start-build").disabled = false;
      el("btn-start-build").textContent = "重新开始构建";
    }
  }, 800);
}

function renderProgress(task) {
  el("progress-fill").style.width = (task.percent || 0) + "%";
  el("progress-pct").textContent = (task.percent || 0) + "%";
  el("progress-note").textContent = task.note || "处理中…";
  el("progress-meta").textContent =
    task.total ? `本步已处理 ${Number(task.processed).toLocaleString()} / ${Number(task.total).toLocaleString()}` : "";

  if (!task.steps || !task.steps.length) return;
  el("step-list").innerHTML = task.steps.map((s) => {
    const mark = s.status === "done" ? "✓" : s.status === "failed" ? "!" : s.status === "running" ? "…" : "";
    return `<li class="${s.status}">
      <span class="sl-mark">${mark}</span>
      <span>${escapeHtml(s.label)}</span>
      <span class="sl-bar"><i style="width:${s.percent || 0}%"></i></span>
      <span class="sl-pct">${s.status === "done" ? "完成" : (s.percent || 0) + "%"}</span>
    </li>`;
  }).join("");
}

function onBuildDone(task) {
  el("btn-start-build").disabled = false;
  el("btn-start-build").textContent = "重新构建";
  el("build-retry").hidden = true;
  setTimeout(() => {
    showStep(4);
    loadExamples();
    // 缺字段/缺数据**不拦截**构建，但必须在跳转后说清楚，
    // 否则用户查到一半才发现「人群类问题答不了」，会把责任归到系统不准。
    const missing = (task && task.missing_required) || [];
    if (missing.length) {
      showMsg(el("msg-step4"), "构建完成，但以下内容没有配置，相关能力会受限：\n· " + missing.join("\n· "), "is-warn");
    } else {
      showMsg(el("msg-step4"), "构建完成，可以开始提问了。", "is-info");
    }
  }, 500);
}

function onBuildFailed(task) {
  const box = el("build-error");
  box.hidden = false;
  box.innerHTML =
    `<div class="err-title">构建失败</div>${escapeHtml(task.error || "未知错误")}` +
    (task.note ? `\n${escapeHtml(task.note)}` : "");
  el("build-retry").hidden = false;
  el("btn-start-build").disabled = false;
  el("btn-start-build").textContent = "重新开始构建";
}

async function retryBuild() {
  el("build-error").hidden = true;
  el("build-retry").hidden = true;
  el("sim-fail").checked = false;
  await startBuild();
}

/* ================= 第 4 步：查询 ================= */

async function loadExamples() {
  try {
    const data = await api("/api/wizard/examples");
    el("examples-list").innerHTML = (data.questions || [])
      .map((q) => `<button type="button" class="ex-chip">${escapeHtml(q)}</button>`).join("");
  } catch (e) {
    el("examples-list").innerHTML = "";
  }
}

async function ask(question) {
  const q = (question || "").trim();
  const msg = el("msg-step4");
  clearMsg(msg);

  if (!q) {
    showMsg(msg, "先输入一个问题，再点「提问」。", "is-warn");
    el("query-input").focus();
    return;
  }

  const btn = el("query-btn");
  const spinner = btn.querySelector(".spinner");
  const btnText = btn.querySelector(".btn-text");
  btn.disabled = true;
  spinner.hidden = false;
  btnText.textContent = "思考中…";

  try {
    const data = await api("/api/wizard/query", { method: "POST", body: JSON.stringify({ question: q }) });
    renderAnswer(q, data);
    pushHistory(q, data);
  } catch (e) {
    showMsg(msg, e.message, "is-error");
  } finally {
    btn.disabled = false;
    spinner.hidden = true;
    btnText.textContent = "提问";
  }
}

/* 答案正文里的 [来源N] 变成可点击的小标签，点一下跳到下方对应的来源卡片。
 * 与 Demo 页（api/static/app.js 的 formatAnswer）是同一套标记约定，只多了一层跳转。 */
function formatAnswer(text, hasSources) {
  let html = escapeHtml(text);
  // 没有来源列表时，[来源N] 指向一个不存在的东西——去掉比留着好，
  // 否则用户点了没反应，会以为页面坏了。
  if (!hasSources) return html.replace(/\[来源\s*\d+\]/g, "");
  return html.replace(
    /\[来源\s*(\d+)\]/g,
    '<button type="button" class="cite" data-cite="$1" title="跳转到第 $1 条来源">[来源$1]</button>'
  );
}

function jumpToSource(idx) {
  const node = el("src-" + idx);
  if (!node) return;
  node.scrollIntoView({ block: "center", behavior: "smooth" });
  // 先摘掉再重排：连续点同一条引用时，不这么做动画不会重放，看起来像没响应
  node.classList.remove("is-flash");
  void node.offsetWidth;
  node.classList.add("is-flash");
  setTimeout(() => node.classList.remove("is-flash"), 1600);
}

function renderAnswer(question, data) {
  const sources = data.sources || [];
  el("result").hidden = false;
  el("result-meta").textContent =
    `${(data.elapsed_ms / 1000).toFixed(1)} 秒 · 检索类问题` + (data.degraded ? " · 无引用来源" : "");
  el("answer-body").innerHTML = formatAnswer(data.answer, sources.length > 0);

  const box = el("sources-box");
  if (sources.length) {
    // id 用 1 起始，与正文里的 [来源N] 直接对应
    el("sources-list").innerHTML = sources.map((s, i) => `
      <div class="source-item" id="src-${i + 1}">
        <div class="source-head">
          <span class="source-idx">[来源${i + 1}]</span>${escapeHtml(s.doc)} · ${escapeHtml(s.section)}
        </div>
        <div class="source-snippet">${escapeHtml(s.snippet)}</div>
      </div>`).join("");
    box.hidden = false;
  } else {
    box.hidden = true;
  }
  el("result").scrollIntoView({ block: "nearest", behavior: "smooth" });
}

const HISTORY_KEY = "mvp_m1_history";

function pushHistory(question, data) {
  state.history.unshift({
    question,
    answer: data.answer,
    sources: data.sources || [],
    elapsed_ms: data.elapsed_ms,
    time: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
  });
  state.history = state.history.slice(0, 20);
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(state.history)); } catch (e) { /* 隐私模式写不了，忽略 */ }
  renderHistory();
}

function renderHistory() {
  const box = el("history-box");
  if (!state.history.length) { box.hidden = true; return; }
  box.hidden = false;
  el("history-list").innerHTML = state.history.map((h, i) => `
    <li data-index="${i}">
      <span class="hb-q">${escapeHtml(h.question)}</span>
      <span class="hb-time">${h.time}</span>
    </li>`).join("");
}

function restoreHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (Array.isArray(saved)) state.history = saved;
  } catch (e) { state.history = []; }
  renderHistory();
}

/* ================= 规则文档模板 ================= */

const DOC_TEMPLATE = `# 标签定义

> 说明：一个 # 是一级标题，## 是二级标题，### 是三级标题。
> 系统按标题切分文档，标题写得越清楚，答案引用得越准。

## 高价值客户

判定条件：近 90 天下单 ≥ 3 次，且客单价 ≥ 500 元。

### 与会员等级的区别

会员等级按成长值划分，与本标签不互为充分条件。

## 流失预警

判定条件：近 60 天无下单，且历史下单次数 ≥ 2 次。

## 沉睡用户

判定条件：近 180 天无下单、无登录行为。
`;

function downloadTemplate() {
  const blob = new Blob([DOC_TEMPLATE], { type: "text/markdown;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "规则文档模板.md";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

/* ================= 事件绑定与启动 ================= */

function bindEvents() {
  bindDropzone("dz-csv", "csv");
  bindDropzone("dz-md", "md");

  el("csv-list").addEventListener("click", onRemoveFile);
  el("md-list").addEventListener("click", onRemoveFile);

  el("btn-sample").addEventListener("click", async () => {
    const btn = el("btn-sample");
    btn.disabled = true;
    try {
      const data = await api("/api/wizard/sample");
      state.csvFiles = data.csv_files.map((f) => ({
        name: f.name, size: f.size, encoding: f.encoding,
        rowCount: f.row_count, columns: f.columns,
      }));
      state.mdFiles = data.md_files.map((f) => ({
        name: f.name, size: f.size, encoding: "utf-8", text: f.text,
      }));
      renderFileLists();
      showMsg(el("msg-step1"), "示例数据已填好，直接点「下一步：确认字段」即可。", "is-info");
    } catch (e) {
      showMsg(el("msg-step1"), e.message, "is-error");
    } finally {
      btn.disabled = false;
    }
  });

  el("btn-template").addEventListener("click", downloadTemplate);
  el("btn-to-step2").addEventListener("click", goAnalyze);
  el("btn-back-1").addEventListener("click", () => showStep(1));
  el("btn-build").addEventListener("click", () => { showStep(3); });
  el("btn-back-2").addEventListener("click", () => showStep(2));
  el("btn-start-build").addEventListener("click", startBuild);
  el("btn-retry").addEventListener("click", retryBuild);

  document.querySelectorAll("#stepper li").forEach((li) => {
    li.addEventListener("click", () => {
      const s = Number(li.dataset.step);
      if (s <= maxStep) showStep(s);
    });
  });

  el("query-form").addEventListener("submit", (e) => {
    e.preventDefault();
    ask(el("query-input").value);
  });
  el("query-input").addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      ask(el("query-input").value);
    }
  });
  el("answer-body").addEventListener("click", (e) => {
    const cite = e.target.closest(".cite");
    if (cite) jumpToSource(cite.dataset.cite);
  });
  el("examples-list").addEventListener("click", (e) => {
    const chip = e.target.closest(".ex-chip");
    if (!chip) return;
    el("query-input").value = chip.textContent;
    ask(chip.textContent);
  });
  el("history-list").addEventListener("click", (e) => {
    const li = e.target.closest("li");
    if (!li) return;
    const item = state.history[Number(li.dataset.index)];
    if (!item) return;
    el("query-input").value = item.question;
    ask(item.question);
  });
  el("btn-clear-history").addEventListener("click", () => {
    state.history = [];
    try { localStorage.removeItem(HISTORY_KEY); } catch (e) { /* 忽略 */ }
    renderHistory();
  });
}

function onRemoveFile(e) {
  const btn = e.target.closest(".fl-remove");
  if (!btn) return;
  const idx = Number(btn.dataset.index);
  if (btn.dataset.kind === "csv") state.csvFiles.splice(idx, 1);
  else state.mdFiles.splice(idx, 1);
  renderFileLists();
}

bindEvents();
renderFileLists();
restoreHistory();
