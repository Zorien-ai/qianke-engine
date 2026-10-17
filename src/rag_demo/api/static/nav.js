/**
 * 视图路由（M3 前端改造）
 *
 * 把原来「一长页滚到底」的首页拆成几个视图，用 hash 切换：
 *   #/home      首页（我的数据空间 + 数据概况）
 *   #/chat      对话（提问 + 回答 + 数据来源）
 *   #/kb        知识库管理（M3 排期，先给入口与说明）
 *   #/staff     员工管理（账号审核 / 角色 / 停用）
 *   #/settings  权限配置（等级 → 能力矩阵）
 *   /wizard     数据导入（独立向导页，四步流程，不走进 SPA 路由）
 *
 * 分工：本文件只负责「显示哪个视图」；面板本身的显隐仍由 app.js 的
 * applyCapabilities 按能力决定。两边叠加，不互相覆盖——视图管 .view 容器，
 * 能力管容器里的 .panel。
 * 前端隐藏入口只是「不给他点」，真正的拦截在后端。
 */
(function () {
  "use strict";

  var VIEWS = ["home", "chat", "kb", "staff", "settings"];
  var sidebar = document.getElementById("sidebar");
  var backdrop = document.getElementById("nav-backdrop");
  var toggle = document.getElementById("nav-toggle");

  function currentView() {
    var h = (location.hash || "").replace(/^#\/?/, "").split("?")[0];
    return VIEWS.indexOf(h) >= 0 ? h : "home";
  }

  function closeDrawer() {
    document.body.classList.remove("nav-open");
    if (backdrop) backdrop.hidden = true;
  }

  function openDrawer() {
    document.body.classList.add("nav-open");
    if (backdrop) backdrop.hidden = false;
  }

  function showView(name) {
    var views = document.querySelectorAll(".view[data-view]");
    for (var i = 0; i < views.length; i++) {
      views[i].hidden = views[i].getAttribute("data-view") !== name;
    }
    var items = document.querySelectorAll(".nav-item[data-nav]");
    for (var j = 0; j < items.length; j++) {
      items[j].classList.toggle("is-active", items[j].getAttribute("data-nav") === name);
    }
    closeDrawer();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /** 账号 / 企业 / 数据集：与 app.js 读同一份 /whoami 结果（全局 ACCOUNT） */
  function fillWelcome() {
    var tag = document.getElementById("welcome-tag");
    var text = document.getElementById("welcome-text");
    if (!tag || !text) return;
    if (typeof ACCOUNT === "undefined" || !ACCOUNT || !ACCOUNT.username) {
      text.textContent = "请先登录后查看你的数据空间。";
      return;
    }
    var role = ACCOUNT.role || "-";
    if (ACCOUNT.is_system_admin) {
      // 系统管理员没有企业库：他的数据空间就是演示数据集
      tag.textContent = "演示数据集 demo";
      text.innerHTML =
        "当前账号 <b>" + escapeHtml(ACCOUNT.username) + "</b>（系统管理员）。" +
        "可以查看演示数据概况、管理全部账号与权限配置；" +
        "要操作某家企业的数据，请用该企业的管理员账号登录。";
      return;
    }
    // dataset 挂在 enterprise 下（whoami 的 account 结构），顶层没有这个键
    var ds = (ACCOUNT.enterprise && ACCOUNT.enterprise.dataset) || "（未绑定）";
    tag.textContent = "数据集 " + ds;
    text.innerHTML =
      "当前账号 <b>" + escapeHtml(ACCOUNT.username) + "</b>（角色 " + escapeHtml(role) +
      "），数据空间 <code>" + escapeHtml(ds) + "</code>。" +
      (ACCOUNT.is_enterprise_admin
        ? "你是本企业的管理员：可以导入数据、审核员工、查看数据概况。"
        : "你可以基于本企业数据提问；导入与重建请联系企业管理员。");
  }

  /** 能力显隐与 app.js 同一口径；ACCOUNT / CAPS / canManageAccounts 都是它的全局量 */
  function syncNav() {
    var staff = document.querySelector('.nav-item[data-cap="accounts"]');
    if (staff) {
      staff.hidden = !(typeof canManageAccounts === "function" && canManageAccounts());
    }
    var settings = document.querySelector('.nav-item[data-cap="ops"]');
    if (settings) settings.hidden = !(typeof CAPS !== "undefined" && CAPS && CAPS.ops);

    var acc = document.getElementById("nav-account");
    if (acc) {
      if (typeof ACCOUNT !== "undefined" && ACCOUNT && ACCOUNT.username) {
        var ent = (ACCOUNT.enterprise && ACCOUNT.enterprise.name) || "系统";
        acc.textContent = ACCOUNT.username + " · " + ent;
      } else {
        acc.textContent = "未登录";
      }
    }
    fillWelcome();
  }

  function route() {
    var name = currentView();
    // 无能力的视图：手动敲 #/staff 也进不去。面板被能力藏了，留着一个空视图
    // 不如直接送回首页——「进不去」要说清楚去向，而不是给一块空白。
    if (name === "staff" && !(typeof canManageAccounts === "function" && canManageAccounts())) {
      name = "home";
    }
    if (name === "settings" && !(typeof CAPS !== "undefined" && CAPS && CAPS.ops)) {
      name = "home";
    }
    showView(name);
  }

  window.addEventListener("hashchange", route);
  if (toggle) {
    toggle.addEventListener("click", function () {
      if (document.body.classList.contains("nav-open")) closeDrawer();
      else openDrawer();
    });
  }
  if (backdrop) backdrop.addEventListener("click", closeDrawer);

  // app.js 的 loadWhoami 是异步的：等它拿到账号后再同步一次导航与欢迎卡
  window.addEventListener("rag:capabilities", syncNav);
  route();
  syncNav();
  setTimeout(syncNav, 800);
})();
