/* 登录 / 注册页交互
 *
 * 分工：前端负责"说清楚哪里错了"（即时、逐字段、可聚焦），
 * 后端负责"真的能不能放行"（格式、占用、验证码、审核状态）。
 * 两边规则要一致，但前端永远只是提示——绕过它也不会拿到任何权限。
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const EMAIL_RE = /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$/;
  const PHONE_RE = /^1[3-9]\d{9}$/;
  const USERNAME_RE = /^[A-Za-z0-9_.-]{3,32}$/;

  let captchaId = "";
  let toastTimer = 0;

  /* ==================== 工具 ==================== */

  function normalizePhone(value) {
    let digits = String(value || "").replace(/[\s\-()]/g, "");
    if (digits.startsWith("+86")) digits = digits.slice(3);
    else if (digits.startsWith("86") && digits.length === 13) digits = digits.slice(2);
    return digits;
  }

  function accountError(value) {
    const v = String(value || "").trim();
    if (!v) return "请输入账号";
    if (v.includes("@")) {
      return EMAIL_RE.test(v) ? "" : "邮箱格式不正确，例如 name@example.com";
    }
    if (/^[+\d]/.test(v)) {
      return PHONE_RE.test(normalizePhone(v)) ? "" : "手机号需为 11 位且以 1 开头";
    }
    return USERNAME_RE.test(v) ? "" : "用户名为 3~32 位字母、数字、下划线、点或连字符";
  }

  function contactError(value) {
    const v = String(value || "").trim();
    if (!v) return "请填写手机号或邮箱";
    if (v.includes("@")) {
      return EMAIL_RE.test(v) ? "" : "邮箱格式不正确，例如 name@example.com";
    }
    if (/^[+\d]/.test(v)) {
      return PHONE_RE.test(normalizePhone(v)) ? "" : "手机号格式不正确（11 位，1 开头）";
    }
    return "请输入手机号或邮箱";
  }

  function setFieldError(id, message) {
    const input = $(id);
    const box = $(id + "-error");
    if (!input || !box) return;
    if (message) {
      input.setAttribute("aria-invalid", "true");
      box.textContent = message;
      box.hidden = false;
      if (input.type === "checkbox") {
        const wrap = input.closest(".checkbox");
        if (wrap) wrap.classList.add("is-invalid");
      }
    } else {
      input.removeAttribute("aria-invalid");
      box.hidden = true;
      box.textContent = "";
      if (input.type === "checkbox") {
        const wrap = input.closest(".checkbox");
        if (wrap) wrap.classList.remove("is-invalid");
      }
    }
  }

  function setAlert(box, kind, message) {
    if (!box) return;
    if (!kind) {
      box.hidden = true;
      box.textContent = "";
      delete box.dataset.kind;
      return;
    }
    box.dataset.kind = kind;
    box.textContent = message;
    box.hidden = false;
  }

  function setLoading(btn, loading, label) {
    if (!btn) return;
    if (!btn.dataset.label) btn.dataset.label = btn.querySelector(".btn-label").textContent;
    btn.disabled = loading;
    btn.dataset.loading = String(loading);
    btn.setAttribute("aria-busy", String(loading));
    btn.querySelector(".btn-label").textContent = loading ? label : btn.dataset.label;
    const spinner = btn.querySelector(".spinner");
    if (spinner) spinner.hidden = !loading;
  }

  function toast(message) {
    const box = $("toast");
    box.textContent = message;
    box.classList.add("is-show");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => box.classList.remove("is-show"), 2400);
  }

  function validateForm(form, errors, alertBox) {
    form.querySelectorAll(".error").forEach((el) => {
      el.hidden = true;
      el.textContent = "";
    });
    form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
    form.querySelectorAll(".checkbox.is-invalid").forEach((el) => el.classList.remove("is-invalid"));

    const ids = Object.keys(errors);
    ids.forEach((id) => setFieldError(id, errors[id]));

    if (!ids.length) {
      setAlert(alertBox, null);
      return true;
    }
    setAlert(alertBox, "error", `请检查标红的 ${ids.length} 项后再提交`);
    const first = $(ids[0]);
    if (first) first.focus();
    return false;
  }

  /* ==================== 主题 ==================== */

  const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function savedThemeMode() {
    try {
      const saved = localStorage.getItem("rag-theme");
      if (saved === "dark" || saved === "light" || saved === "system") return saved;
    } catch (e) {
      /* ignore */
    }
    return "system";
  }

  function resolveTheme(mode) {
    if (mode === "system") return media && media.matches ? "dark" : "light";
    return mode === "dark" ? "dark" : "light";
  }

  function applyTheme(mode) {
    const nextMode = mode === "dark" || mode === "light" || mode === "system" ? mode : "system";
    const theme = resolveTheme(nextMode);
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.themeMode = nextMode;
    document.querySelectorAll("#theme-switch [data-theme-mode]").forEach((btn) => {
      const active = btn.getAttribute("data-theme-mode") === nextMode;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function bindTheme() {
    document.querySelectorAll("#theme-switch [data-theme-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.getAttribute("data-theme-mode");
        try {
          localStorage.setItem("rag-theme", mode);
        } catch (e) {
          /* 隐私模式下 localStorage 会抛错，主题仍应能切换 */
        }
        applyTheme(mode);
      });
    });

    if (media) {
      media.addEventListener("change", () => {
        if (savedThemeMode() === "system") applyTheme("system");
      });
    }
  }

  /* ==================== 登录 / 注册切换 ==================== */

  const TABS = ["login", "register"];

  function activateTab(which, focusTab = false) {
    const name = which === "register" ? "register" : "login";
    TABS.forEach((item) => {
      const tab = $("tab-" + item);
      const panel = $("panel-" + item);
      const active = item === name;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      panel.hidden = !active;
    });
    if (name === "register" && !captchaId) loadCaptcha();
    if (focusTab) $("tab-" + name).focus();
    try {
      history.replaceState(null, "", name === "register" ? "#register" : "#login");
    } catch (e) {
      /* file:// 等场景下 replaceState 可能不可用，不影响功能 */
    }
  }

  function bindTabs() {
    TABS.forEach((item) => {
      $("tab-" + item).addEventListener("click", () => activateTab(item));
    });

    // 地址栏 / 前进后退改 hash 时也要跟着切（replaceState 不改 hash 时不触发）
    window.addEventListener("hashchange", () => {
      activateTab(window.location.hash === "#register" ? "register" : "login");
    });

    const tablist = document.querySelector(".auth-tabs");
    tablist.addEventListener("keydown", (event) => {
      const current = event.target.closest('[role="tab"]');
      if (!current) return;
      const index = TABS.findIndex((item) => $("tab-" + item) === current);
      let next = -1;
      if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
      else if (event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = TABS.length - 1;
      if (next < 0) return;
      event.preventDefault();
      activateTab(TABS[next], true);
    });
  }

  /* ==================== 密码可见性 ==================== */

  function bindReveals() {
    document.querySelectorAll("[data-reveal]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const input = $(btn.dataset.reveal);
        if (!input) return;
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.setAttribute("aria-pressed", String(show));
        btn.setAttribute("aria-label", show ? "隐藏密码" : "显示密码");
        input.focus({ preventScroll: true });
      });
    });
  }

  /* ==================== 账号类型 ==================== */

  function currentAccountType() {
    const checked = document.querySelector('input[name="account-type"]:checked');
    return checked ? checked.value : "enterprise";
  }

  function syncAccountType() {
    const isEnterprise = currentAccountType() === "enterprise";
    document.querySelectorAll(".type-option").forEach((label) => {
      label.classList.toggle("is-active", label.querySelector("input").checked);
    });

    document.querySelectorAll("[data-enterprise]").forEach((el) => {
      el.hidden = !isEnterprise;
    });
    document.querySelectorAll("[data-employee]").forEach((el) => {
      el.hidden = isEnterprise;
      const input = el.querySelector("input");
      input.disabled = isEnterprise;
      if (isEnterprise) input.value = "";
    });

    setFieldError("reg-company", "");
    setFieldError("reg-invite", "");
  }

  /* ==================== 密码强度 ==================== */

  function strengthOf(password) {
    if (!password) return 0;
    let score = 0;
    if (password.length >= 8) score += 1;
    if (password.length >= 12) score += 1;
    if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1;
    if (/\d/.test(password)) score += 1;
    if (/[^A-Za-z0-9]/.test(password)) score += 1;
    if (score <= 2) return 1;
    if (score <= 3) return 2;
    return 3;
  }

  function updateStrength() {
    const password = $("reg-password").value;
    const level = strengthOf(password);
    const meter = $("reg-strength");
    meter.dataset.level = String(level);
    const text = ["至少 8 位", "偏弱", "中等", "很强"][level];
    meter.querySelector(".strength-text").textContent = text;
  }

  /* ==================== 图形验证码 ==================== */

  async function loadCaptcha() {
    const btn = $("captcha-refresh");
    const img = $("captcha-img");
    btn.classList.remove("is-failed");
    btn.disabled = true;
    try {
      const res = await fetch("/auth/captcha", { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      captchaId = data.id;
      img.src = data.image;
      $("reg-captcha").value = "";
      setFieldError("reg-captcha", "");
    } catch (e) {
      captchaId = "";
      btn.classList.add("is-failed");
      img.removeAttribute("src");
      setFieldError("reg-captcha", "验证码加载失败，请点击图片重试");
    } finally {
      btn.disabled = false;
    }
  }

  /* ==================== 逐字段校验 ==================== */

  const VALIDATORS = {
    "login-account": (v) => accountError(v),
    "login-password": (v) => (!v ? "请输入密码" : v.length < 6 ? "密码至少 6 位" : ""),
    "reg-username": (v) => {
      const value = v.trim();
      if (!value) return "请输入用户名";
      return USERNAME_RE.test(value) ? "" : "用户名为 3~32 位字母、数字、下划线、点或连字符";
    },
    "reg-contact": (v) => contactError(v),
    "reg-company": (v) => {
      const value = v.trim();
      if (!value) return "请输入企业名称";
      return value.length > 64 ? "企业名称不能超过 64 个字符" : "";
    },
    "reg-invite": (v) => {
      const value = v.trim();
      if (!value) return "请输入企业邀请码";
      return /^[A-Za-z0-9]{6,16}$/.test(value) ? "" : "邀请码为 6~16 位字母或数字";
    },
    "reg-password": (v) => {
      if (!v) return "请设置密码";
      if (v.length < 8) return "密码至少 8 位";
      if (!/[A-Za-z]/.test(v) || !/\d/.test(v)) return "密码需同时包含字母和数字";
      return "";
    },
    "reg-confirm": (v) => {
      if (!v) return "请再次输入密码";
      return v === $("reg-password").value ? "" : "两次输入的密码不一致";
    },
    "reg-captcha": (v) => {
      const value = v.trim();
      if (!value) return "请输入验证码";
      return /^[A-Za-z0-9]{4}$/.test(value) ? "" : "验证码为 4 位字符";
    },
  };

  function bindFieldValidation() {
    Object.keys(VALIDATORS).forEach((id) => {
      const input = $(id);
      if (!input) return;
      const refresh = () => {
        if (input.getAttribute("aria-invalid") !== "true") return;
        setFieldError(id, VALIDATORS[id](input.value));
      };
      input.addEventListener("input", refresh);
      input.addEventListener("blur", refresh);
    });

    // 密码变化时：强度条跟随，同时如果"确认密码"已经报过错，要重新比对
    $("reg-password").addEventListener("input", () => {
      updateStrength();
      if ($("reg-confirm").getAttribute("aria-invalid") === "true") {
        setFieldError("reg-confirm", VALIDATORS["reg-confirm"]($("reg-confirm").value));
      }
    });

    $("reg-terms").addEventListener("change", () => {
      if ($("reg-terms").checked) setFieldError("reg-terms", "");
    });

    document.querySelectorAll('input[name="account-type"]').forEach((radio) => {
      radio.addEventListener("change", syncAccountType);
    });

    $("captcha-refresh").addEventListener("click", loadCaptcha);
  }

  /* ==================== 登录提交 ==================== */

  function collectLoginErrors() {
    const errors = {};
    const account = $("login-account").value.trim();
    const password = $("login-password").value;
    const accError = accountError(account);
    if (accError) errors["login-account"] = accError;
    if (!password) errors["login-password"] = "请输入密码";
    else if (password.length < 6) errors["login-password"] = "密码至少 6 位";
    return errors;
  }

  async function submitLogin(event) {
    event.preventDefault();
    const form = $("login-form");
    const alertBox = $("login-alert");
    if (!validateForm(form, collectLoginErrors(), alertBox)) return;

    const btn = $("login-submit");
    setLoading(btn, true, "登录中…");
    try {
      const res = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account: $("login-account").value.trim(),
          password: $("login-password").value,
          remember: $("login-remember").checked,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setAlert(alertBox, "error", data.detail || "登录失败，请稍后重试");
        if (res.status === 401) $("login-password").focus();
        return;
      }
      setAlert(alertBox, "success", "登录成功，正在进入…");
      toast("登录成功");
      window.setTimeout(() => {
        window.location.href = "/";
      }, 420);
    } catch (err) {
      setAlert(alertBox, "error", "网络异常，请检查连接后重试");
    } finally {
      setLoading(btn, false);
    }
  }

  /* ==================== 注册提交 ==================== */

  // 只校验注册表单自己的字段：VALIDATORS 里还有登录表单的两个字段，
  // 全量遍历会把隐藏的登录输入框一起标红（表现为"明明填好了还报 2 项"）。
  const REGISTER_FIELDS = [
    "reg-username", "reg-contact", "reg-company", "reg-invite",
    "reg-password", "reg-confirm", "reg-captcha",
  ];

  function collectRegisterErrors() {
    const errors = {};
    const isEnterprise = currentAccountType() === "enterprise";

    REGISTER_FIELDS.forEach((id) => {
      if (!isEnterprise && id === "reg-company") return;
      if (isEnterprise && id === "reg-invite") return;
      const message = VALIDATORS[id]($(id).value);
      if (message) errors[id] = message;
    });

    if (!$("reg-terms").checked) errors["reg-terms"] = "请先阅读并同意服务条款";
    return errors;
  }

  async function submitRegister(event) {
    event.preventDefault();
    const form = $("register-form");
    const alertBox = $("register-alert");
    if (!validateForm(form, collectRegisterErrors(), alertBox)) return;

    const isEnterprise = currentAccountType() === "enterprise";
    const contact = $("reg-contact").value.trim();
    const btn = $("register-submit");
    setLoading(btn, true, "提交中…");

    try {
      const res = await fetch("/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: $("reg-username").value.trim(),
          contact,
          password: $("reg-password").value,
          account_type: isEnterprise ? "enterprise" : "employee",
          display_name: isEnterprise ? $("reg-company").value.trim() : "",
          invite_code: isEnterprise ? null : $("reg-invite").value.trim(),
          captcha_id: captchaId,
          captcha_code: $("reg-captcha").value.trim(),
          agree_terms: true,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail || "注册失败，请稍后重试";
        setAlert(alertBox, "error", detail);
        if (detail.includes("验证码")) {
          loadCaptcha();
          $("reg-captcha").focus();
        }
        return;
      }

      form.reset();
      // 不在这里 await 新验证码：注册已经成功，反馈不该被另一张图卡住。
      // 清空 id 后，下次切到注册页会自动换一张（见 activateTab）。
      captchaId = "";
      syncAccountType();
      updateStrength();

      activateTab("login");
      $("login-account").value = contact;
      $("login-password").value = "";
      setAlert($("login-alert"), "success", `${data.message || "注册成功"}。可以先用刚注册的账号登录查看进度。`);
      $("login-password").focus();
      toast("注册成功，等待审核");
    } catch (err) {
      setAlert(alertBox, "error", "网络异常，请检查连接后重试");
    } finally {
      setLoading(btn, false);
    }
  }

  /* ==================== 找回密码 / 服务条款 ==================== */

  function bindDialogs() {
    document.querySelectorAll("[data-close-dialog]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const dialog = btn.closest("dialog");
        if (dialog) dialog.close();
      });
    });

    // 点遮罩关闭（点 dialog 本身即背景区域）
    document.querySelectorAll("dialog").forEach((dialog) => {
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) dialog.close();
      });
    });

    $("terms-link").addEventListener("click", (event) => {
      event.preventDefault();
      $("terms-dialog").showModal();
    });

    $("forgot-link").addEventListener("click", () => {
      setAlert($("forgot-alert"), null);
      setFieldError("forgot-contact", "");
      const account = $("login-account").value.trim();
      $("forgot-contact").value = account.includes("@") ? account : "";
      $("forgot-dialog").showModal();
      window.setTimeout(() => $("forgot-contact").focus(), 30);
    });

    $("forgot-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const contact = $("forgot-contact").value.trim();
      const message = contactError(contact);
      if (message) {
        setFieldError("forgot-contact", message);
        $("forgot-contact").focus();
        return;
      }
      setFieldError("forgot-contact", "");
      const btn = $("forgot-submit");
      setLoading(btn, true, "提交中…");
      // 演示环境没有短信/邮件通道，这里不伪造"已发送"，直接给出可执行的下一步
      window.setTimeout(() => {
        setLoading(btn, false);
        setAlert(
          $("forgot-alert"),
          "info",
          "演示环境不发送重置链接：请联系系统管理员（admin）重置密码，或使用其他账号登录。"
        );
      }, 420);
    });
  }

  /* ==================== 初始化 ==================== */

  function init() {
    applyTheme(document.documentElement.dataset.themeMode || savedThemeMode());
    bindTheme();
    bindTabs();
    bindReveals();
    bindDialogs();
    bindFieldValidation();
    syncAccountType();
    updateStrength();

    $("login-form").addEventListener("submit", submitLogin);
    $("register-form").addEventListener("submit", submitRegister);

    const wantsRegister = window.location.hash === "#register";
    activateTab(wantsRegister ? "register" : "login");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
