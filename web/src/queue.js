import "./queue.css";

const root = document.getElementById("queue-root");
const state = { status: "", kind: "", jobs: [], stats: null, loading: false, message: "" };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    ...options,
  });
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : detail?.message || `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return data;
}

function loginView() {
  root.innerHTML = `
    <form class="login" id="queue-login">
      <h1>千客 · 队列管理</h1>
      <p>仅系统管理员可访问。查看 pending/running/dead，并重放失败任务。</p>
      <label for="q-account">账号</label>
      <input id="q-account" autocomplete="username" required />
      <label for="q-password">密码</label>
      <input id="q-password" type="password" autocomplete="current-password" required />
      <button class="btn primary" type="submit">登录</button>
      <div class="qmsg error" id="q-login-msg"></div>
    </form>`;
  document.getElementById("queue-login").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          account: document.getElementById("q-account").value.trim(),
          password: document.getElementById("q-password").value,
        }),
      });
      await load();
    } catch (error) {
      document.getElementById("q-login-msg").textContent = error.message;
    }
  });
}

function statsView() {
  const s = state.stats || {};
  return `
    <div class="queue-stats">
      <div class="qstat"><b>${s.total || 0}</b><span>总任务</span></div>
      <div class="qstat"><b>${s.pending || 0}</b><span>PENDING</span></div>
      <div class="qstat"><b>${s.running || 0}</b><span>RUNNING</span></div>
      <div class="qstat"><b>${s.done || 0}</b><span>DONE</span></div>
      <div class="qstat failed"><b>${s.failed || 0}</b><span>FAILED</span></div>
      <div class="qstat dead"><b>${s.dead || 0}</b><span>DEAD</span></div>
    </div>`;
}

function rowView(job) {
  const status = String(job.status || "").toUpperCase();
  const canReplay = status === "DEAD" || status === "FAILED";
  return `
    <tr>
      <td><code>${esc(job.job_id)}</code></td>
      <td><code>${esc(job.work_item_id)}</code></td>
      <td>${esc(job.kind)}</td>
      <td><span class="status ${esc(status)}">${esc(status)}</span></td>
      <td>${Number(job.attempts || 0)}/${Number(job.max_attempts || 0)}</td>
      <td><code>${esc(job.worker_id || "-")}</code></td>
      <td class="err" title="${esc(job.last_error || "")}">${esc(job.last_error || "-")}</td>
      <td>${esc(String(job.updated_at || "").replace("T", " ").slice(0, 19))}</td>
      <td>${canReplay ? `<button class="btn danger" data-replay="${esc(job.job_id)}">重放</button>` : ""}</td>
    </tr>`;
}

function pageView() {
  const s = state.stats || {};
  root.innerHTML = `
    <div class="queue-head">
      <div><h1>队列管理</h1><p>Super-agent Job 队列 · 最老 PENDING：${esc(s.oldest_pending_at || "-")}</p></div>
      <button class="btn ghost" id="q-refresh">刷新</button>
    </div>
    ${statsView()}
    <div class="panel">
      <div class="toolbar">
        <select id="q-status">
          ${["", "PENDING", "RUNNING", "DONE", "FAILED", "DEAD"].map((status) =>
            `<option value="${status}" ${state.status === status ? "selected" : ""}>${status || "全部状态"}</option>`
          ).join("")}
        </select>
        <select id="q-kind">
          ${["", "WORKER", "ACTION"].map((kind) =>
            `<option value="${kind}" ${state.kind === kind ? "selected" : ""}>${kind || "全部类型"}</option>`
          ).join("")}
        </select>
        <span class="spacer"></span>
        <span class="qmsg" id="q-count">${state.jobs.length} 条</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Job</th><th>WorkItem</th><th>类型</th><th>状态</th><th>尝试</th><th>Worker</th><th>错误</th><th>更新时间</th><th></th></tr></thead>
          <tbody>${state.jobs.length ? state.jobs.map(rowView).join("") : '<tr><td colspan="9" class="empty">当前筛选没有任务</td></tr>'}</tbody>
        </table>
      </div>
      <div class="qmsg ${state.message.startsWith("失败") ? "error" : ""}" id="q-msg">${esc(state.message)}</div>
    </div>`;
  document.getElementById("q-refresh").addEventListener("click", load);
  document.getElementById("q-status").addEventListener("change", (event) => {
    state.status = event.target.value;
    load();
  });
  document.getElementById("q-kind").addEventListener("change", (event) => {
    state.kind = event.target.value;
    load();
  });
  root.querySelectorAll("[data-replay]").forEach((button) => {
    button.addEventListener("click", () => replay(button.dataset.replay));
  });
}

async function load() {
  if (state.loading) return;
  state.loading = true;
  try {
    const params = new URLSearchParams({ limit: "100" });
    if (state.status) params.set("status", state.status);
    if (state.kind) params.set("kind", state.kind);
    const data = await api(`/api/superagent/jobs?${params.toString()}`);
    state.jobs = data.jobs || [];
    state.stats = data.stats || null;
    state.message = "";
    pageView();
  } catch (error) {
    if (error.status === 401 || error.status === 403) loginView();
    else {
      state.message = `加载失败：${error.message}`;
      pageView();
    }
  } finally {
    state.loading = false;
  }
}

async function replay(jobId) {
  if (!confirm(`确认重放 ${jobId}？attempts 会归零。`)) return;
  try {
    await api(`/api/superagent/jobs/${encodeURIComponent(jobId)}/replay`, { method: "POST" });
    state.message = `已重放 ${jobId}`;
    await load();
  } catch (error) {
    state.message = `重放失败：${error.message}`;
    pageView();
  }
}

load();
