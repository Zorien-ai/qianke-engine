(function () {
  "use strict";

  var alertBox = document.getElementById("auth-alert");
  var loginPanel = document.getElementById("login-panel");
  var registerPanel = document.getElementById("register-panel");
  var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-tab]"));
  var loginMode = "code";
  var pending = false;

  function $(id) {
    return document.getElementById(id);
  }

  function showError(message) {
    alertBox.textContent = message || "操作失败，请稍后再试";
    alertBox.hidden = false;
  }

  function clearError() {
    alertBox.textContent = "";
    alertBox.hidden = true;
  }

  function detailMessage(data, fallback) {
    var detail = data && data.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail.message === "string") return detail.message;
    return fallback;
  }

  async function api(path, options) {
    var response = await fetch(path, Object.assign({
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" }
    }, options || {}));
    var data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    if (!response.ok) {
      var err = new Error(detailMessage(data, "请求失败（" + response.status + "）"));
      err.status = response.status;
      throw err;
    }
    return data || {};
  }

  function setTab(tab) {
    tabs.forEach(function (button) {
      var active = button.dataset.tab === tab;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    loginPanel.hidden = tab !== "login";
    registerPanel.hidden = tab !== "register";
    clearError();
  }

  function setLoginMode(mode) {
    loginMode = mode === "password" ? "password" : "code";
    var isCode = loginMode === "code";
    $("code-login-fields").hidden = !isCode;
    $("password-login-fields").hidden = isCode;
    $("login-submit").textContent = isCode ? "验证码登录" : "密码登录";
    $("toggle-password-mode").textContent = isCode ? "使用密码登录" : "使用验证码登录";
    clearError();
  }

  function setBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      button.dataset.originalLabel = button.textContent;
      button.textContent = label || "请稍候…";
      button.disabled = true;
    } else {
      button.textContent = button.dataset.originalLabel || label || button.textContent;
      button.disabled = false;
    }
  }

  async function sendCode(phoneInput, button, hint) {
    var phone = (phoneInput.value || "").trim();
    if (!/^1[3-9]\d{9}$/.test(phone)) {
      showError("请输入有效的 11 位手机号");
      phoneInput.focus();
      return;
    }
    var original = button.textContent;
    button.disabled = true;
    button.textContent = "发送中…";
    clearError();
    try {
      var data = await api("/api/c/auth/sms/send", {
        method: "POST",
        body: JSON.stringify({ phone: phone })
      });
      if (data.dev_mode && data.dev_code) {
        hint.textContent = "演示环境验证码：" + data.dev_code + "（生产环境不会展示）";
        hint.hidden = false;
      }
      var left = Number(data.cooldown_seconds || 60);
      button.textContent = left + "s 后重发";
      var timer = window.setInterval(function () {
        left -= 1;
        if (left <= 0) {
          window.clearInterval(timer);
          button.disabled = false;
          button.textContent = original;
          return;
        }
        button.textContent = left + "s 后重发";
      }, 1000);
    } catch (error) {
      showError(error.message);
      button.disabled = false;
      button.textContent = original;
    }
  }

  async function redirectAfterLogin() {
    try {
      var who = await fetch("/whoami", { credentials: "same-origin" }).then(function (response) {
        return response.ok ? response.json() : null;
      });
      var account = (who && who.account) || {};
      if (account.is_system_admin || account.is_enterprise_admin) {
        window.location.href = "/v2/#/";
        return;
      }
      if (account.account_type !== "consumer") {
        try {
          var me = await fetch("/api/b/workbench/me", { credentials: "same-origin" });
          if (me.ok) {
            window.location.href = "/v2/b.html";
            return;
          }
        } catch (error) {
          /* 不是商家，继续走 C 端 */
        }
      }
      if (account.account_type === "consumer" || (!account.enterprise_id && !account.is_system_admin && !account.is_enterprise_admin)) {
        window.location.href = "/v2/#/c/app";
        return;
      }
      window.location.href = "/v2/#/";
    } catch (error) {
      window.location.href = "/v2/#/c/app";
    }
  }

  async function submitLogin() {
    if (pending) return;
    var phone = ($("login-phone").value || "").trim();
    if (!/^1[3-9]\d{9}$/.test(phone)) {
      showError("请输入有效的 11 位手机号");
      $("login-phone").focus();
      return;
    }
    pending = true;
    var button = $("login-submit");
    setBusy(button, true, "登录中…");
    clearError();
    try {
      if (loginMode === "code") {
        var code = ($("login-code").value || "").trim();
        if (!/^\d{4,8}$/.test(code)) {
          throw new Error("请输入验证码");
        }
        await api("/api/c/auth/login/code", {
          method: "POST",
          body: JSON.stringify({
            phone: phone,
            code: code,
            remember: $("login-remember").checked
          })
        });
      } else {
        var password = $("login-password").value || "";
        if (!password) throw new Error("请输入密码");
        await api("/auth/login", {
          method: "POST",
          body: JSON.stringify({
            account: phone,
            password: password,
            remember: $("login-remember").checked
          })
        });
      }
      await redirectAfterLogin();
    } catch (error) {
      showError(error.message);
      setBusy(button, false, "验证码登录");
      setLoginMode(loginMode);
    } finally {
      pending = false;
    }
  }

  async function submitRegister() {
    if (pending) return;
    var phone = ($("register-phone").value || "").trim();
    var code = ($("register-code").value || "").trim();
    var nickname = ($("register-nickname").value || "").trim();
    var password = $("register-password").value || "";
    if (!/^1[3-9]\d{9}$/.test(phone)) {
      showError("请输入有效的 11 位手机号");
      $("register-phone").focus();
      return;
    }
    if (!/^\d{4,8}$/.test(code)) {
      showError("请输入验证码");
      $("register-code").focus();
      return;
    }
    if (nickname.length < 2) {
      showError("昵称至少 2 个字符");
      $("register-nickname").focus();
      return;
    }
    if (password.length < 8) {
      showError("密码至少 8 位");
      $("register-password").focus();
      return;
    }
    if (!$("register-terms").checked) {
      showError("请先阅读并同意用户协议和隐私政策");
      return;
    }
    pending = true;
    var button = $("register-submit");
    setBusy(button, true, "注册中…");
    clearError();
    try {
      await api("/api/c/auth/register", {
        method: "POST",
        body: JSON.stringify({
          phone: phone,
          code: code,
          nickname: nickname,
          password: password,
          agree_terms: true
        })
      });
      window.location.href = "/v2/#/c/app";
    } catch (error) {
      showError(error.message);
      setBusy(button, false, "注册并进入小鱼");
    } finally {
      pending = false;
    }
  }

  tabs.forEach(function (button) {
    button.addEventListener("click", function () {
      setTab(button.dataset.tab);
    });
  });

  $("toggle-password-mode").addEventListener("click", function () {
    setLoginMode(loginMode === "code" ? "password" : "code");
  });

  $("login-send").addEventListener("click", function () {
    sendCode($("login-phone"), $("login-send"), $("dev-code-hint"));
  });

  $("register-send").addEventListener("click", function () {
    sendCode($("register-phone"), $("register-send"), $("register-dev-hint"));
  });

  $("login-submit").addEventListener("click", submitLogin);
  $("register-submit").addEventListener("click", submitRegister);

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter") return;
    if (!loginPanel.hidden) submitLogin();
    else submitRegister();
  });

  (async function boot() {
    try {
      var who = await fetch("/whoami", { credentials: "same-origin" }).then(function (response) {
        return response.ok ? response.json() : null;
      });
      if (who && who.account) {
        await redirectAfterLogin();
      }
    } catch (error) {
      /* 未登录是正常情况 */
    }
  })();
})();
