/* 登录 / 注册页 —— 只做两件事：切表单、提交给 /auth/*。
 *
 * 校验只做"明显写错"的提示；真正的规则在后端（auth.create_user）：
 * 前端挡的是手滑，后端挡的才是脏数据与越权。
 */
const $ = (id) => document.getElementById(id);

function showTab(which) {
  const isLogin = which === "login";
  $("tab-login").classList.toggle("active", isLogin);
  $("tab-register").classList.toggle("active", !isLogin);
  $("login-form").hidden = !isLogin;
  $("register-form").hidden = isLogin;
}

/* 账号类型决定要填「企业名称」还是「邀请码」，两者不能同时出现：
 * 同时显示会让人以为两个都要填。 */
function syncRegType() {
  const isEnterprise = $("reg-type").value === "enterprise";
  $("reg-display-label").hidden = !isEnterprise;
  $("reg-invite-label").hidden = isEnterprise;
  $("reg-display-label").firstChild.textContent = isEnterprise ? "企业名称" : "显示名（可选）";
  if (isEnterprise) $("reg-invite").value = "";
  else $("reg-display").value = "";
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = {};
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  return { ok: res.ok, status: res.status, data };
}

document.addEventListener("DOMContentLoaded", () => {
  showTab("login");
  $("tab-login").addEventListener("click", () => showTab("login"));
  $("tab-register").addEventListener("click", () => showTab("register"));
  $("reg-type").addEventListener("change", syncRegType);
  syncRegType();

  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("login-msg");
    msg.textContent = "登录中…";
    msg.className = "login-msg";
    const { ok, data } = await postJson("/auth/login", {
      username: $("login-username").value.trim(),
      password: $("login-password").value,
    });
    if (!ok) {
      msg.textContent = data.detail || "登录失败";
      msg.className = "login-msg is-error";
      return;
    }
    // 待审核账号也能登录：进去后页面会显示「等待审核」，而不是卡在登录页
    window.location.href = "/";
  });

  $("register-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("reg-msg");
    msg.textContent = "提交中…";
    msg.className = "login-msg";
    const isEnterprise = $("reg-type").value === "enterprise";
    const { ok, data } = await postJson("/auth/register", {
      username: $("reg-username").value.trim(),
      password: $("reg-password").value,
      account_type: isEnterprise ? "enterprise" : "employee",
      display_name: $("reg-display").value.trim(),
      invite_code: isEnterprise ? null : $("reg-invite").value.trim(),
    });
    if (!ok) {
      msg.textContent = data.detail || "注册失败";
      msg.className = "login-msg is-error";
      return;
    }
    msg.textContent = `${data.message}。可以先用刚注册的账号登录查看进度。`;
    msg.className = "login-msg is-ok";
    $("register-form").reset();
    syncRegType();
    showTab("login");
    $("login-username").value = data.username || "";
    $("login-password").focus();
  });
});
