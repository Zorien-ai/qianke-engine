/* 搭建向导 —— 上传 → 确认字段 → 一键构建 → 提问
 *
 * 这一层只做「取数据 + 渲染」，不写业务规则：字段怎么认、几行、什么编码、
 * 进度怎么算、答案从哪来，全部由服务端给出（见 rag_demo/mvp/app.py）。
 *
 * M2 改动：**文件不再在浏览器里解析**。
 *   M1 是自己解码文件、按换行数行数、按逗号数列名，再把结果发给服务端——
 *   服务端从头到尾没见过文件本身，行数只能写「约」，编码判断还散在前端。
 *   现在文件直接 multipart 上传，服务端统一转 UTF-8 后用 pandas 真读一遍，
 *   返回**真实行数**与列名；页面只负责把服务端的话渲染出来。
 */

const el = (id) => document.getElementById(id);

const UPLOAD_KEY = "wizard-upload-id";   // 刷新页面后据此恢复上传批次（内容在服务端磁盘上）

const state = {
  uploadId: null,    // 服务端的上传批次号（内容已落盘，这里是唯一需要记住的东西）
  csvFiles: [],      // {name, size, encoding, rowCount, columns}
  mdFiles: [],       // {name, size, encoding, chars}
  analysis: null,    // 上传接口返回的完整状态（字段识别 + 文档结构 + 汇总）
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

/* 统一请求封装：把后端/网络错误一律翻译成一句能看懂的中文，绝不把异常抛到页面上
 *
 * 注意 FormData 分支：上传文件时**不能**手动设 Content-Type——
 * multipart 的 boundary 由浏览器生成，自己写死会变成「服务端解析不出任何文件字段」。
 */
async function api(url, options = {}) {
  let resp;
  const headers = options.body instanceof FormData
      ? {}
      : { "Content-Type": "application/json" };
  try {
    resp = await fetch(url, { headers, ...options });
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

/* ================= 上传前的本地校验（不做解析） =================
 * 这里只判「该不该收」，解析一律交给服务端。
 * 保留这一步是因为它能在**选中文件的瞬间**给出反馈（拖错框、拖了 .xlsx），
 * 不用等一个 15MB 的文件传完再说「格式不对」。
 */

function isMdFile(file) {
  return /\.(md|markdown)$/i.test(file.name);
}

function isCsvFile(file) {
  return /\.(csv|txt)$/i.test(file.name);
}

/* 服务端状态 → 页面模型。上传、删文件、示例填满、刷新恢复都走这一个函数，
 * 于是「刚上传」与「恢复到一半」不存在两套渲染逻辑。 */
function applyState(data) {
  state.uploadId = data.upload_id || null;
  state.analysis = data;
  state.csvFiles = (data.csv_files || []).map((f) => ({
    name: f.name,
    size: f.size,
    encoding: f.encoding || "",
    rowCount: f.row_count || 0,
    columns: f.columns || [],
  }));
  state.mdFiles = (data.md_files || []).map((f) => ({
    name: f.name,
    size: f.size,
    encoding: f.encoding || "",
    chars: f.chars || 0,
  }));
  try {
    if (state.uploadId) localStorage.setItem(UPLOAD_KEY, state.uploadId);
    else localStorage.removeItem(UPLOAD_KEY);
  } catch (e) { /* 隐私模式写不了，忽略 */ }
  renderFileLists();
}

/* 原始编码 → 展示话术：用户不需要知道 gbk 是什么，只需要知道「不用自己转」 */
function encodingLabel(encoding) {
  if (!encoding) return "";
  return /^utf-8/i.test(encoding) ? "UTF-8" : `原始 ${encoding} → 已转 UTF-8`;
}

/* ================= 第 1 步：上传 ================= */

async function addFiles(fileList, kind) {
  const files = Array.from(fileList || []);
  if (!files.length) return;

  // 本地只做「该不该收」的判断；真正的解析在服务端（见模块头注释）
  const rejected = [];
  const form = new FormData();
  for (const f of files) {
    if (kind === "md" && !isMdFile(f)) { rejected.push(`${f.name}（要放到左边「交易数据」）`); continue; }
    if (kind === "csv" && isMdFile(f)) { rejected.push(`${f.name}（这是文档，要放到右边）`); continue; }
    if (!isMdFile(f) && !isCsvFile(f)) { rejected.push(`${f.name}（只支持 .csv/.txt 与 .md）`); continue; }
    if (f.size === 0) { rejected.push(`${f.name}（空文件）`); continue; }
    form.append("files", f);
  }

  clearMsg(el("msg-step1"));
  if (!form.has("files")) {
    showMsg(el("msg-step1"), "以下文件没有被加入：\n· " + rejected.join("\n· "), "is-warn");
    return;
  }
  // 追加到同一批次；服务端的批次号就是「这次会话上传了什么」的唯一凭据
  if (state.uploadId) form.append("upload_id", state.uploadId);

  const zone = el(kind === "csv" ? "dz-csv" : "dz-md");
  zone.classList.add("is-uploading");
  try {
    const data = await api("/api/wizard/upload", { method: "POST", body: form });
    applyState(data);
    const all = rejected.concat(data.rejected || []);
    if (all.length) {
      showMsg(el("msg-step1"), "以下文件没有被加入：\n· " + all.join("\n· "), "is-warn");
    } else {
      const s = data.summary || {};
      showMsg(el("msg-step1"),
        `已上传并读取：交易数据 ${s.csv_count || 0} 个（共 ${(s.total_rows || 0).toLocaleString()} 行）`
        + ` / 规则文档 ${s.md_count || 0} 篇。点「下一步：确认字段」继续。`, "is-info");
    }
  } catch (e) {
    showMsg(el("msg-step1"), e.message, "is-error");
  } finally {
    zone.classList.remove("is-uploading");
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
    // 行数是服务端真读出来的，不再写「约」
    csvList.innerHTML = state.csvFiles.map((f, i) => `
      <li>
        <span class="fl-name">${escapeHtml(f.name)}</span>
        <span class="fl-meta">${f.rowCount.toLocaleString()} 行 · ${f.columns.length} 列 · ${escapeHtml(encodingLabel(f.encoding))} · ${fmtSize(f.size)}</span>
        <button type="button" class="fl-remove" data-kind="csv" data-index="${i}" title="移除">×</button>
      </li>`).join("");
  }

  if (!state.mdFiles.length) {
    mdList.innerHTML = '<li class="fl-empty">还没有文件</li>';
  } else {
    mdList.innerHTML = state.mdFiles.map((f, i) => `
      <li>
        <span class="fl-name">${escapeHtml(f.name)}</span>
        <span class="fl-meta">${f.chars.toLocaleString()} 字 · ${escapeHtml(encodingLabel(f.encoding))} · ${fmtSize(f.size)}</span>
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

function goAnalyze() {
  clearMsg(el("msg-step1"));

  if (!state.uploadId || (!state.csvFiles.length && !state.mdFiles.length)) {
    showMsg(el("msg-step1"), "还没有文件。请先拖入文件，或点「用示例数据填满」直接体验流程。", "is-warn");
    return;
  }
  // 字段识别与文档结构在**上传时就已算好**（服务端返回的 state 里），
  // 这一步只做本地校验 + 渲染，所以不再发请求、也不会出现「点了没反应」的等待
  renderAnalysis(state.analysis);
  showStep(2);
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
  // 只报「哪一批上传 + 用户确认的列映射」：文件本身已经在服务端磁盘上，
  // 前端不再需要（也无法）把数据搬过去——顺带堵掉了「前端报什么就构建什么」的口子
  return {
    upload_id: state.uploadId,
    fields: collectFields(),
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
    // 真实构建是分钟级的（要跑模型与入库），2 秒一次足够；
    // 原型阶段用 800ms 是因为假构建总共才几秒，看不出运动
  }, 2000);
}

function renderProgress(task) {
  el("progress-fill").style.width = (task.percent || 0) + "%";
  el("progress-pct").textContent = (task.percent || 0) + "%";
  el("progress-note").textContent = task.note || "处理中…";
  el("progress-meta").textContent =
    task.total ? `本步已处理 ${Number(task.processed).toLocaleString()} / ${Number(task.total).toLocaleString()}` : "";

  if (!task.steps || !task.steps.length) return;
  el("step-list").innerHTML = task.steps.map((s) => {
    // skipped 是真实存在的状态：只上传文档时不重建画像，那三步就没跑。
    // 标成「完成」会骗人，标成待处理又永远不动——所以单独一档。
    const mark = s.status === "done" ? "✓" : s.status === "failed" ? "!"
      : s.status === "skipped" ? "–" : s.status === "running" ? "…" : "";
    const pct = s.status === "done" ? "完成" : s.status === "skipped" ? "已跳过" : (s.percent || 0) + "%";
    return `<li class="${s.status}">
      <span class="sl-mark">${mark}</span>
      <span>${escapeHtml(s.label)}</span>
      <span class="sl-bar"><i style="width:${s.percent || 0}%"></i></span>
      <span class="sl-pct">${pct}</span>
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
    const q = state.uploadId ? `?upload_id=${encodeURIComponent(state.uploadId)}` : "";
    const data = await api("/api/wizard/examples" + q);
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
    const data = await api("/api/wizard/query", {
      method: "POST",
      body: JSON.stringify({ question: q, upload_id: state.uploadId }),
    });
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
  el("result-meta").textContent = data.busy
    ? "构建进行中 · 本次查询已被拒绝"
    : `${(data.elapsed_ms / 1000).toFixed(1)} 秒 · 检索类问题` + (data.degraded ? " · 无引用来源" : "");
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
      // 服务端把仓库自带的真实数据复制进上传目录，走与真人上传**完全相同**的
      // 落盘/解析路径——所以这里的响应结构与上传接口完全一致，直接套用同一个渲染
      const data = await api("/api/wizard/sample");
      applyState(data);
      const s = data.summary || {};
      showMsg(el("msg-step1"),
        `示例数据已填好（${s.csv_count || 0} 个 CSV / ${s.md_count || 0} 篇文档，共 ${(s.total_rows || 0).toLocaleString()} 行）。`
        + "直接点「下一步：确认字段」即可。", "is-info");
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

async function onRemoveFile(e) {
  const btn = e.target.closest(".fl-remove");
  if (!btn) return;
  const idx = Number(btn.dataset.index);
  const list = btn.dataset.kind === "csv" ? state.csvFiles : state.mdFiles;
  const target = list[idx];
  if (!target || !state.uploadId) return;

  // 移除要同步到服务端：文件已经落盘，只从页面列表里划掉的话，
  // 第 2 步的构建仍然会把这份数据算进去——「界面上没有」和「实际没有」必须一致。
  clearMsg(el("msg-step1"));
  try {
    const data = await api("/api/wizard/upload/remove", {
      method: "POST",
      body: JSON.stringify({ upload_id: state.uploadId, name: target.name }),
    });
    applyState(data);
  } catch (err) {
    showMsg(el("msg-step1"), err.message, "is-error");
  }
}

/* 刷新页面后恢复上传批次：内容在服务端磁盘上，这里只需要记着批次号。
 * 上一次的会话历史也一并恢复，用户不必从第 1 步重新开始。 */
async function restoreUpload() {
  let saved = null;
  try { saved = localStorage.getItem(UPLOAD_KEY); } catch (e) { /* 忽略 */ }
  if (!saved) return;
  try {
    const data = await api(`/api/wizard/upload/${encodeURIComponent(saved)}`);
    applyState(data);
    const s = data.summary || {};
    if (s.csv_count || s.md_count) {
      showMsg(el("msg-step1"),
        `已恢复上次的上传（交易数据 ${s.csv_count || 0} 个 / 规则文档 ${s.md_count || 0} 篇）。`
        + "如需换一批数据，请先移除或重新上传。", "is-info");
    }
  } catch (e) {
    // 服务端已清（比如重启时清了临时目录）：静默丢弃，别拿一句「恢复失败」打扰用户
    try { localStorage.removeItem(UPLOAD_KEY); } catch (e2) { /* 忽略 */ }
  }
}

bindEvents();
renderFileLists();
restoreHistory();
restoreUpload();
