import "./tenants.css";

const root = document.getElementById("tenant-root");
let tenants = [];

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
    <form class="login" id="login-form">
      <h1>千客 · 租户管理</h1>
      <p>仅系统管理员可访问。请使用管理员账号登录。</p>
      <label for="login-account">账号</label>
      <input id="login-account" name="account" autocomplete="username" required />
      <label for="login-password">密码</label>
      <input id="login-password" name="password" type="password" autocomplete="current-password" required />
      <button class="btn primary" type="submit">登录</button>
      <div class="tenant-msg error" id="login-msg"></div>
    </form>`;
  document.getElementById("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const account = document.getElementById("login-account").value.trim();
    const password = document.getElementById("login-password").value;
    try {
      await api("/auth/login", { method: "POST", body: JSON.stringify({ account, password }) });
      await boot();
    } catch (error) {
      document.getElementById("login-msg").textContent = error.message;
    }
  });
}

function statsView() {
  const members = tenants.reduce((sum, tenant) => sum + tenant.members.length, 0);
  const orders = tenants.reduce((sum, tenant) => sum + (tenant.counts?.orders || 0), 0);
  const open = tenants.reduce((sum, tenant) => sum + (tenant.counts?.open_work_items || 0), 0);
  return `
    <div class="tenant-stats">
      <div class="stat"><b>${tenants.length}</b><span>租户</span></div>
      <div class="stat"><b>${members}</b><span>绑定成员</span></div>
      <div class="stat"><b>${orders}</b><span>租户订单</span></div>
      <div class="stat"><b>${open}</b><span>待处理工作项</span></div>
    </div>`;
}

function memberView(tenant, member) {
  return `
    <div class="member">
      <div><strong>${esc(member.display_name || member.username)}</strong> <em>${esc(member.username)} · ${esc(member.role)}</em></div>
      <button class="btn ghost danger" data-remove-member="${member.account_id}" data-tenant="${esc(tenant.merchant_id)}">移除</button>
    </div>`;
}

function tenantView(tenant) {
  const counts = tenant.counts || {};
  return `
    <section class="tenant-card" data-tenant="${esc(tenant.merchant_id)}">
      <header>
        <div><h2>${esc(tenant.name)}</h2><code>${esc(tenant.merchant_id)}</code></div>
        <span class="pill">${esc(tenant.status)}</span>
      </header>
      <div class="counts">
        <span>订单 <b>${counts.orders || 0}</b></span>
        <span>商品 <b>${counts.products || 0}</b></span>
        <span>工作项 <b>${counts.work_items || 0}</b></span>
        <span>待处理 <b>${counts.open_work_items || 0}</b></span>
      </div>
      ${tenant.backend_error ? `<div class="tenant-msg error">${esc(tenant.backend_error)}</div>` : ""}
      <div class="member-list">
        ${tenant.members.length ? tenant.members.map((member) => memberView(tenant, member)).join("") : '<div class="tenant-msg">还没有绑定成员</div>'}
      </div>
      <div class="form-row" style="margin-top:10px">
        <input placeholder="账号 ID" data-account-id="${esc(tenant.merchant_id)}" style="width:94px" />
        <select data-role="${esc(tenant.merchant_id)}">
          <option value="owner">owner</option>
          <option value="admin">admin</option>
          <option value="staff">staff</option>
        </select>
        <button class="btn" data-bind="${esc(tenant.merchant_id)}">绑定成员</button>
      </div>
    </section>`;
}

function pageView() {
  root.innerHTML = `
    <div class="tenant-head">
      <div><h1>租户管理</h1><p>商家租户 · 成员绑定 · Super-agent 工作项概览</p></div>
      <button class="btn ghost" id="refresh">刷新</button>
    </div>
    ${statsView()}
    <div class="tenant-grid">${tenants.map(tenantView).join("") || '<div class="panel">暂无租户</div>'}</div>
    <section class="panel">
      <h3>新建租户</h3>
      <form class="form-row" id="create-tenant">
        <input id="tenant-id" placeholder="merchant_id，例如 m_tea_002" required />
        <input id="tenant-name" placeholder="租户名称" required />
        <button class="btn primary" type="submit">创建</button>
      </form>
      <div class="tenant-msg" id="create-msg"></div>
    </section>
    <section class="panel">
      <h3>账号查询</h3>
      <div class="form-row">
        <input id="account-q" placeholder="用户名 / 昵称关键词" />
        <button class="btn" id="search-account">查询</button>
      </div>
      <div class="tenant-msg" id="account-result">输入关键词查询可绑定账号</div>
    </section>`;
  document.getElementById("refresh").addEventListener("click", load);
  document.getElementById("create-tenant").addEventListener("submit", createTenant);
  document.getElementById("search-account").addEventListener("click", searchAccounts);
  root.querySelectorAll("[data-bind]").forEach((button) => {
    button.addEventListener("click", () => bindMember(button.dataset.bind));
  });
  root.querySelectorAll("[data-remove-member]").forEach((button) => {
    button.addEventListener("click", () => removeMember(button.dataset.tenant, button.dataset.removeMember));
  });
}

async function load() {
  try {
    const data = await api("/api/admin/tenants");
    tenants = data.tenants || [];
    pageView();
  } catch (error) {
    if (error.status === 401 || error.status === 403) loginView();
    else {
      root.innerHTML = `<div class="panel"><h1>租户管理加载失败</h1><div class="tenant-msg error">${esc(error.message)}</div></div>`;
    }
  }
}

async function createTenant(event) {
  event.preventDefault();
  const merchantId = document.getElementById("tenant-id").value.trim();
  const name = document.getElementById("tenant-name").value.trim();
  const message = document.getElementById("create-msg");
  try {
    await api("/api/admin/tenants", { method: "POST", body: JSON.stringify({ merchant_id: merchantId, name }) });
    message.textContent = "已创建";
    message.className = "tenant-msg";
    await load();
  } catch (error) {
    message.textContent = error.message;
    message.className = "tenant-msg error";
  }
}

async function bindMember(merchantId) {
  const input = root.querySelector(`[data-account-id="${CSS.escape(merchantId)}"]`);
  const role = root.querySelector(`[data-role="${CSS.escape(merchantId)}"]`);
  const accountId = Number(input?.value || 0);
  if (!accountId) {
    alert("请输入账号 ID");
    return;
  }
  try {
    await api(`/api/admin/tenants/${encodeURIComponent(merchantId)}/members`, {
      method: "POST",
      body: JSON.stringify({ account_id: accountId, role: role?.value || "staff" }),
    });
    await load();
  } catch (error) {
    alert(error.message);
  }
}

async function removeMember(merchantId, accountId) {
  if (!confirm(`确认移除账号 #${accountId}？`)) return;
  try {
    await api(`/api/admin/tenants/${encodeURIComponent(merchantId)}/members/${accountId}`, { method: "DELETE" });
    await load();
  } catch (error) {
    alert(error.message);
  }
}

async function searchAccounts() {
  const q = document.getElementById("account-q").value.trim();
  const target = document.getElementById("account-result");
  try {
    const data = await api(`/api/admin/tenants/accounts?q=${encodeURIComponent(q)}`);
    target.innerHTML = data.accounts.length
      ? data.accounts.map((user) => `<div class="member"><span>#${user.id} ${esc(user.username)} <em>${esc(user.display_name || "")} · ${esc(user.status)}</em></span></div>`).join("")
      : "没有匹配账号";
    target.className = "tenant-msg";
  } catch (error) {
    target.textContent = error.message;
    target.className = "tenant-msg error";
  }
}

async function boot() { await load(); }
boot();
