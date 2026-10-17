/**
 * 企业后台（M3 原生前端）—— #/staff 员工管理 与 #/kb 知识库管理
 *
 * 为什么单独一个文件：app.js 已经有 1200 行（对话 / 溯源 / 权限矩阵），
 * 两个后台视图与其塞进去，不如按视图拆开。app.js 只保留它原本就有的能力
 * （身份 / 权限 / 对话），并把旧的 accounts 渲染整段搬到这里。
 *
 * 数据全部来自接口，页面里不写死任何数字 / 名单 / 状态：
 *   #/staff  GET  /admin/users              成员、角色、企业（含邀请码）、scope/me
 *            GET  /admin/enterprises        仅系统管理员：企业总览
 *            POST /admin/enterprise/invite-code/reset   重置邀请码（契约 C）
 *            POST /admin/users/{id}/approve|reject|role|status
 *   #/kb     GET  /api/kb/overview          概况（契约 A）
 *            POST /api/kb/clear             清空（契约 B，confirm=dataset 字面值）
 *            POST /api/wizard/build         重建（契约 D：last_source.upload_id+fields）
 *            GET  /api/wizard/build/{id}    构建进度轮询
 *
 * 懒加载：只有进入对应视图（或能力到达后仍停在该视图）才拉接口；切换视图
 * 不重复请求、不先把内容清空（已加载过就保留，刷新由按钮/操作触发）。
 * 权限口径与 app.js 一致：canManageAccounts() / ACCOUNT / CAPS 都是 app.js 的全局量，
 * 真正的拦截仍在后端，这里只是不给他点。
 */
(function () {
  "use strict";

  /* ---------- 小工具 ---------- */
  var $ = function (id) { return document.getElementById(id); };

  var VIEWS = ["home", "chat", "kb", "staff", "settings"];

  function currentViewName() {
    var h = (location.hash || "").replace(/^#\/?/, "").split("?")[0];
    return VIEWS.indexOf(h) >= 0 ? h : "home";
  }

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fmtInt(n) {
    var v = Number(n);
    if (!isFinite(v)) return "—";
    return v.toLocaleString("zh-CN");
  }

  function setText(id, text) {
    var node = $(id);
    if (node) node.textContent = text;
  }

  function setClass(id, cls, on) {
    var node = $(id);
    if (node) node.classList.toggle(cls, !!on);
  }

  function on(id, event, handler) {
    var node = $(id);
    if (node) node.addEventListener(event, handler);
  }

  function setHidden(id, hidden) {
    var node = $(id);
    if (node) node.hidden = !!hidden;
  }

  /** 统一读响应：非 2xx 时把后端的 detail 变成一句人话 */
  async function readJson(res) {
    var data = null;
    try {
      data = await res.json();
    } catch (e) {
      data = null;
    }
    if (!res.ok) {
      var detail = data && (data.detail || data.message);
      var msg = typeof detail === "string" ? detail : "HTTP " + res.status;
      throw new Error(msg);
    }
    return data || {};
  }

  /** 统一请求入口：优先走 app.js 的 apiFetch（401 会自动回登录页） */
  function request(url, options) {
    if (typeof apiFetch === "function") return apiFetch(url, options || {});
    return fetch(url, options || {});
  }

  async function fetchJson(url, options) {
    return readJson(await request(url, options));
  }

  function postJson(url, body) {
    return fetchJson(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }

  /** 复制到剪贴板：优先 Clipboard API，非安全上下文退回 execCommand */
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (e) {
        ok = false;
      } finally {
        document.body.removeChild(ta);
      }
      if (ok) resolve();
      else reject(new Error("浏览器拒绝访问剪贴板"));
    });
  }

  /* ---------- 页面状态 ---------- */
  var S = {
    route: "",
    accountId: undefined,
    staff: {
      loading: false,
      loaded: false,
      promise: null,
      error: null,
      data: null,
      entData: null,
      entError: null,
      filter: "all",
      query: "",
      resetTarget: null,
      busy: false,
    },
    kb: {
      loading: false,
      loaded: false,
      promise: null,
      error: null,
      data: null,
      clearBusy: false,
      build: { running: false, taskId: null, timer: null, failures: 0, startedAt: 0 },
    },
  };

  /* ================================================================
   * 路由 / 能力事件（懒加载入口）
   * ================================================================ */

  function syncRoute() {
    S.route = currentViewName();
    if (S.route === "staff") {
      if (typeof canManageAccounts === "function" && canManageAccounts()) loadStaff(false);
    } else if (S.route === "kb") {
      loadKb(false);
    }
  }

  function onCapabilities() {
    var acct = typeof ACCOUNT !== "undefined" ? ACCOUNT : null;
    var id = acct ? acct.id : null;
    var prev = S.accountId;
    S.accountId = id;

    // 同一页面里换了账号（极少数情况）：旧租户的数据必须立刻作废，不能等下一次操作
    if (prev !== undefined && prev !== id) {
      resetStaff();
      resetKb();
      if (S.route === "staff" && typeof canManageAccounts === "function" && canManageAccounts()) {
        loadStaff(true);
      } else if (S.route === "kb") {
        loadKb(true);
      }
      return;
    }

    // 首次拿到能力：直接落在 #/staff（刷新页面）的管理员，由这里触发首次加载
    if (S.route === "staff" && typeof canManageAccounts === "function" && canManageAccounts()) {
      loadStaff(false);
    } else if (S.route === "kb") {
      loadKb(false);
    }
  }

  /* ================================================================
   * #/staff —— 邀请码 / 成员 / 企业总览
   * ================================================================ */

  function resetStaff() {
    S.staff.loading = false;
    S.staff.loaded = false;
    S.staff.promise = null;
    S.staff.error = null;
    S.staff.data = null;
    S.staff.entData = null;
    S.staff.entError = null;
    S.staff.filter = "all";
    S.staff.query = "";
    var search = $("member-search");
    if (search) search.value = "";
    renderStaffLoading();
  }

  function loadStaff(force) {
    if (typeof canManageAccounts === "function" && !canManageAccounts()) {
      return Promise.resolve();
    }
    if (S.staff.loading) return S.staff.promise;
    if (S.staff.loaded && !force) return Promise.resolve();

    S.staff.loading = true;
    var firstLoad = !S.staff.data;
    if (firstLoad) renderStaffLoading();
    else setText("staff-invite-status", "刷新中…");

    var who = typeof ACCOUNT !== "undefined" && ACCOUNT ? ACCOUNT.id : undefined;
    S.staff.promise = (async function () {
      try {
        var users = await fetchJson("/admin/users");
        if (who !== undefined && (!ACCOUNT || ACCOUNT.id !== who)) return; // 账号中途变了，丢弃
        S.staff.data = users;
        S.staff.entData = null;
        S.staff.entError = null;

        // 企业总览只给系统管理员：企业管理员调它必然 403，不去撞
        if (users.me && users.me.is_system_admin) {
          try {
            S.staff.entData = await fetchJson("/admin/enterprises");
          } catch (e) {
            S.staff.entError = e.message || String(e);
          }
          if (who !== undefined && (!ACCOUNT || ACCOUNT.id !== who)) return;
        }
        S.staff.loaded = true;
        S.staff.error = null;
        setText("invite-hint", "");
        setText("accounts-hint", "");
        renderStaff();
      } catch (e) {
        S.staff.error = e.message || String(e);
        renderStaffError(e);
      } finally {
        S.staff.loading = false;
      }
    })();
    return S.staff.promise;
  }

  function renderStaffLoading() {
    setText("staff-invite-status", "读取中…");
    setText("accounts-status", "读取中…");
    setText("enterprises-status", "读取中…");
    setText("invite-hint", "");
    setText("accounts-hint", "");
    var list = $("accounts-list");
    if (list) list.innerHTML = '<div class="console-loading">正在加载成员列表…</div>';
    var body = $("enterprises-body");
    if (body) body.innerHTML = "";
    setHidden("enterprises-empty", true);
    setHidden("invite-card", true);
    setHidden("enterprise-box", true);
    setHidden("invite-empty", false);
    var empty = $("invite-empty");
    if (empty) empty.textContent = "正在读取企业信息…";
  }

  function renderStaffError(err) {
    var msg = (err && err.message) || "未知错误";
    setText("staff-invite-status", "加载失败");
    setText("accounts-status", "加载失败");
    setText("enterprises-status", "加载失败");
    setText("invite-hint", "邀请码加载失败：" + msg);
    setClass("invite-hint", "is-error", true);
    setText("accounts-hint", "成员列表加载失败：" + msg + "（点右上角「刷新」重试）");
    setClass("accounts-hint", "is-error", true);
    var list = $("accounts-list");
    if (list) list.innerHTML = '<div class="console-empty-cell">加载失败：' + esc(msg) + "</div>";
    var empty = $("invite-empty");
    if (empty) {
      empty.hidden = false;
      empty.textContent = "企业信息加载失败：" + msg + "。点成员列表右上角「刷新」重试。";
    }
  }

  function renderStaff() {
    var data = S.staff.data;
    if (!data) return;
    var users = data.users || [];
    var roles = data.roles || [];
    var ents = data.enterprises || [];
    var me = data.me || {};
    var isSys = !!me.is_system_admin;

    setText("staff-invite-status", isSys ? "系统管理员 · 全部企业" : "企业管理员 · 本企业");
    setClass("staff-invite-status", "is-danger", false);
    renderInvite(me, isSys);
    renderStaffStats(users);
    renderMembers(users, roles, ents, me, isSys);
    renderEnterprises(isSys);
    setHidden("enterprises-panel", !isSys);
  }

  /** 当前账号所属企业（/admin/users.enterprises 里找自己那条） */
  function currentEnterprise() {
    var data = S.staff.data;
    if (!data) return null;
    var me = data.me || {};
    if (!me.enterprise_id) return null;
    var list = data.enterprises || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === me.enterprise_id) return list[i];
    }
    return null;
  }

  function renderInvite(me, isSys) {
    var myEnt = currentEnterprise();
    var box = $("enterprise-box");
    var card = $("invite-card");
    var empty = $("invite-empty");

    if (myEnt && myEnt.invite_code) {
      box.hidden = false;
      card.hidden = false;
      empty.hidden = true;
      setText("ent-name", myEnt.name || "—");
      setText("ent-dataset", myEnt.dataset || "—");
      setText("ent-code", myEnt.invite_code);

      var link = location.origin + "/login";
      setText("invite-link", link);
      var open = $("invite-link-open");
      if (open) open.href = link;

      setDisabled("invite-copy", false);
      setDisabled("invite-link-copy", false);
      setDisabled("invite-reset", false);
      return;
    }

    box.hidden = true;
    card.hidden = true;
    empty.hidden = false;
    empty.textContent = isSys
      ? "系统管理员不归属任何企业，没有个人邀请码。可在下方「企业总览」查看各企业邀请码，或为某家企业重置邀请码。"
      : "当前账号还没有绑定企业，暂时没有邀请码。请联系系统管理员确认企业信息。";
    setDisabled("invite-copy", true);
    setDisabled("invite-link-copy", true);
    setDisabled("invite-reset", true);
  }

  function setDisabled(id, disabled) {
    var node = $(id);
    if (node) node.disabled = !!disabled;
  }

  function memberCounts(users) {
    var c = { all: users.length, pending: 0, active: 0, disabled: 0 };
    users.forEach(function (u) {
      if (u.status === "active") c.active++;
      else if (u.status === "disabled") c.disabled++;
      // pending 与 rejected 都算「待审核」：管理员对两者都还能操作（通过 / 改判通过）
      else c.pending++;
    });
    return c;
  }

  function renderStaffStats(users) {
    var c = memberCounts(users);
    setText("staff-stat-total", fmtInt(c.all));
    setText("staff-stat-pending", fmtInt(c.pending));
    setText("staff-stat-disabled", fmtInt(c.disabled));
  }

  function updateFilterCounts(counts) {
    setText("filter-count-all", String(counts.all));
    setText("filter-count-pending", String(counts.pending));
    setText("filter-count-active", String(counts.active));
    setText("filter-count-disabled", String(counts.disabled));
    var box = $("member-filters");
    if (!box) return;
    var btns = box.querySelectorAll("button[data-filter]");
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle("is-active", btns[i].dataset.filter === S.staff.filter);
    }
  }

  function entMapOf(ents) {
    var map = {};
    (ents || []).forEach(function (e) {
      map[e.id] = e;
    });
    return map;
  }

  function filteredMembers(users, entMap) {
    var filter = S.staff.filter;
    var q = (S.staff.query || "").trim().toLowerCase();
    return users.filter(function (u) {
      var st = u.status || "";
      if (filter === "pending" && !(st === "pending" || st === "rejected")) return false;
      if (filter === "active" && st !== "active") return false;
      if (filter === "disabled" && st !== "disabled") return false;
      if (!q) return true;
      var ent = u.enterprise_id ? entMap[u.enterprise_id] : null;
      var hay = [u.username, u.display_name, ent && ent.name]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.indexOf(q) !== -1;
    });
  }

  function roleOptionsHtml(roles, current) {
    return (roles || [])
      .map(function (r) {
        var sel = r.value === current ? " selected" : "";
        return (
          '<option value="' + esc(r.value) + '"' + sel + ">" +
          esc(r.label) + "（" + esc(r.level) + "）</option>"
        );
      })
      .join("");
  }

  function fallbackRole(roles) {
    var hasCs = false;
    (roles || []).forEach(function (r) {
      if (r.value === "cs") hasCs = true;
    });
    if (hasCs) return "cs";
    return roles && roles.length ? roles[0].value : "";
  }

  function renderMembers(users, roles, ents, me, isSys) {
    var entMap = entMapOf(ents);
    setText("accounts-title", isSys ? "账号管理" : "本企业成员");
    setText(
      "accounts-intro",
      isSys
        ? "企业账号审核通过后创建企业库并生成邀请码；员工账号由所属企业管理员审核并分配角色。角色决定默认等级 → 决定能看到什么。"
        : "本企业员工由你审核并分配角色；把邀请码发给同事，他们注册时填写。企业账号的审核由系统管理员负责。"
    );

    var counts = memberCounts(users);
    var list = filteredMembers(users, entMap);
    setText("accounts-status", "共 " + fmtInt(counts.all) + " 个账号");
    updateFilterCounts(counts);

    var filtering = S.staff.filter !== "all" || !!S.staff.query.trim();
    setText(
      "accounts-hint",
      filtering ? "筛选出 " + list.length + " / " + users.length + " 个账号" : ""
    );
    setClass("accounts-hint", "is-error", false);

    var box = $("accounts-list");
    if (!box) return;
    if (!list.length) {
      box.innerHTML =
        '<div class="console-empty-cell">' +
        (users.length ? "没有符合筛选条件的账号。" : "还没有账号。员工用邀请码注册后会出现在这里。") +
        "</div>";
      return;
    }
    var defaultRole = fallbackRole(roles);
    box.innerHTML = list
      .map(function (u) {
        return memberRow(u, roles, entMap, isSys, defaultRole);
      })
      .join("");
  }

  function memberRow(u, roles, entMap, isSys, defaultRole) {
    var ent = u.enterprise_id ? entMap[u.enterprise_id] : null;
    var pending = u.status === "pending";
    var rejected = u.status === "rejected";
    // 待审核 / 已拒绝都没拿到角色，操作区都要给「通过」；只有 pending 才需要「拒绝」
    var waiting = pending || rejected;
    var statusCls = pending
      ? "is-warn"
      : rejected || u.status === "disabled"
        ? "is-danger"
        : "";

    var actions = "";
    if (waiting) {
      if (u.account_type === "enterprise") {
        actions = isSys
          ? '<span class="pu-meta">企业账号</span>' +
            '<button type="button" class="perm-btn is-primary" data-approve="' + esc(u.id) + '">' +
            (rejected ? "改判通过" : "通过") + "</button>" +
            (pending
              ? '<button type="button" class="perm-btn is-danger" data-reject="' + esc(u.id) + '">拒绝</button>'
              : "")
          : '<span class="pu-meta">企业账号 · 待系统管理员审核</span>';
      } else {
        actions =
          '<select data-approve-role="' + esc(u.id) + '">' + roleOptionsHtml(roles, defaultRole) + "</select>" +
          '<button type="button" class="perm-btn is-primary" data-approve="' + esc(u.id) + '">' +
          (rejected ? "改判通过" : "通过") + "</button>" +
          (pending
            ? '<button type="button" class="perm-btn is-danger" data-reject="' + esc(u.id) + '">拒绝</button>'
            : "");
      }
    } else if (u.is_system_admin) {
      actions = '<span class="pu-meta">系统管理员</span>';
    } else if (u.is_enterprise_admin) {
      actions = '<span class="pu-meta">企业管理员</span>';
    } else {
      actions = '<select data-role="' + esc(u.id) + '">' + roleOptionsHtml(roles, u.role) + "</select>";
    }

    var statusBtn = "";
    if (!(u.is_system_admin || waiting || (u.account_type === "enterprise" && !isSys))) {
      statusBtn =
        u.status === "disabled"
          ? '<button type="button" class="perm-btn" data-enable="' + esc(u.id) + '">启用</button>'
          : '<button type="button" class="perm-btn is-danger" data-disable="' + esc(u.id) + '">停用</button>';
    }

    return (
      '<div class="account-row">' +
      '<div class="acc-main">' +
      '<span class="acc-name">' + esc(u.display_name || u.username) + "</span>" +
      '<span class="acc-username">@' + esc(u.username) + "</span>" +
      '<span class="pu-level">' + esc(u.account_type_label || "") + "</span>" +
      '<span class="acc-status ' + statusCls + '">' + esc(u.status_label || u.status) + "</span>" +
      (ent ? '<span class="pu-meta">' + esc(ent.name) + "</span>" : "") +
      "</div>" +
      '<div class="acc-actions">' + actions + statusBtn + "</div>" +
      '<div class="acc-meta">' +
      esc(u.created_at || "") +
      (u.reviewed_by ? " · 审核：" + esc(u.reviewed_by) : "") +
      (u.last_login_at ? " · 最近登录 " + esc(u.last_login_at) : "") +
      "</div>" +
      "</div>"
    );
  }

  function renderMembersFromState() {
    var data = S.staff.data;
    if (!data) return;
    renderMembers(data.users || [], data.roles || [], data.enterprises || [], data.me || {}, !!(data.me || {}).is_system_admin);
  }

  /* ---------- 企业总览（仅系统管理员，契约 E） ---------- */
  function renderEnterprises(isSys) {
    if (!isSys) return;
    var body = $("enterprises-body");
    if (!body) return;

    if (S.staff.entError) {
      setText("enterprises-status", "加载失败");
      body.innerHTML = "";
      setHidden("enterprises-empty", false);
      setText("enterprises-empty", "企业总览加载失败：" + S.staff.entError);
      return;
    }
    var data = S.staff.entData;
    if (!data) {
      setText("enterprises-status", "读取中…");
      return;
    }
    var ents = data.enterprises || [];
    var totals = data.totals || {};
    setText(
      "enterprises-status",
      "共 " + fmtInt(totals.enterprises != null ? totals.enterprises : ents.length) +
      " 家企业 · " + fmtInt(totals.members) + " 名成员 · " + fmtInt(totals.pending) + " 条待审核"
    );

    if (!ents.length) {
      body.innerHTML = "";
      setHidden("enterprises-empty", false);
      setText("enterprises-empty", "还没有企业。企业账号注册并通过系统管理员审核后会出现在这里。");
      return;
    }
    setHidden("enterprises-empty", true);
    body.innerHTML = ents
      .map(function (e) {
        var ready = e.dataset_ready
          ? '<span class="console-chip is-ok">已构建</span>'
          : '<span class="console-chip is-warn">未构建</span>';
        return (
          "<tr>" +
          "<td>" + esc(e.name) + '<span class="console-sub">#' + esc(e.id) + "</span></td>" +
          "<td><code>" + esc(e.dataset) + "</code></td>" +
          '<td class="console-num">' + fmtInt(e.members) + "</td>" +
          '<td class="console-num">' + fmtInt(e.pending) + "</td>" +
          '<td class="console-num">' + fmtInt(e.disabled) + "</td>" +
          "<td>" + ready + "</td>" +
          "<td>" + esc(e.last_build_at || "—") + "</td>" +
          "<td><code>" + esc(e.invite_code) + "</code></td>" +
          '<td><div class="console-actions">' +
          '<button type="button" class="perm-btn" data-copy-ent="' + esc(e.id) + '">复制邀请码</button>' +
          '<button type="button" class="perm-btn is-danger" data-reset-ent="' + esc(e.id) + '">重置</button>' +
          "</div></td>" +
          "</tr>"
        );
      })
      .join("");
  }

  function findEnterpriseById(id) {
    var num = Number(id);
    var lists = [];
    if (S.staff.data) lists.push(S.staff.data.enterprises || []);
    if (S.staff.entData) lists.push(S.staff.entData.enterprises || []);
    for (var i = 0; i < lists.length; i++) {
      for (var j = 0; j < lists[i].length; j++) {
        if (lists[i][j].id === num) return lists[i][j];
      }
    }
    return null;
  }

  /** 重置接口返回的 enterprise 覆盖两份缓存（/admin/users 与 /admin/enterprises 各存一份） */
  function applyEnterpriseUpdate(ent) {
    if (!ent) return;
    var lists = [];
    if (S.staff.data) lists.push(S.staff.data.enterprises || []);
    if (S.staff.entData) lists.push(S.staff.entData.enterprises || []);
    lists.forEach(function (list) {
      list.forEach(function (item) {
        if (item.id === ent.id) {
          Object.keys(ent).forEach(function (k) {
            item[k] = ent[k];
          });
        }
      });
    });
  }

  /* ---------- 成员操作 ---------- */
  function setStaffHint(msg, isError) {
    setText("invite-hint", msg || "");
    setClass("invite-hint", "is-error", !!isError);
  }

  function setAccountsHint(msg, isError) {
    setText("accounts-hint", msg || "");
    setClass("accounts-hint", "is-error", !!isError);
  }

  function setStaffBusy(busy) {
    S.staff.busy = !!busy;
    document.querySelectorAll("#accounts-list button, #accounts-list select, #enterprises-body button").forEach(function (node) {
      node.disabled = !!busy;
    });
  }

  /** 操作成功后刷新：先刷新 whoami（权限/状态可能变了），再拉最新成员 */
  async function refreshAfterMutation(message, isError) {
    try {
      if (typeof loadWhoami === "function") await loadWhoami();
      await loadStaff(true);
      if (!isError) setAccountsHint(message || "操作成功，权限立即生效");
      else setAccountsHint(message, true);
    } catch (e) {
      setAccountsHint((message ? message + "；" : "") + "刷新失败：" + (e.message || e), true);
    }
  }

  async function approveMember(id, role) {
    setStaffBusy(true);
    try {
      await postJson("/admin/users/" + encodeURIComponent(id) + "/approve", { role: role || "" });
      await refreshAfterMutation("已通过审核，权限立即生效");
    } catch (e) {
      setAccountsHint("审核失败：" + (e.message || e), true);
    } finally {
      setStaffBusy(false);
    }
  }

  async function changeMemberRole(id, role) {
    setStaffBusy(true);
    try {
      await postJson("/admin/users/" + encodeURIComponent(id) + "/role", { role: role });
      await refreshAfterMutation("角色已更新，下一个请求即按新等级判定");
    } catch (e) {
      setAccountsHint("改角色失败：" + (e.message || e), true);
    } finally {
      setStaffBusy(false);
    }
  }

  async function rejectMember(id) {
    if (!window.confirm("确认拒绝该注册申请？账号将无法登录（之后可以改判通过）。")) return;
    setStaffBusy(true);
    try {
      await postJson("/admin/users/" + encodeURIComponent(id) + "/reject", {});
      await refreshAfterMutation("已拒绝该申请（账号保留，可改判通过）");
    } catch (e) {
      setAccountsHint("拒绝失败：" + (e.message || e), true);
    } finally {
      setStaffBusy(false);
    }
  }

  async function setMemberStatus(id, status) {
    if (status === "disabled" && !window.confirm("确认停用该账号？停用后会话立即失效。")) return;
    setStaffBusy(true);
    try {
      await postJson("/admin/users/" + encodeURIComponent(id) + "/status", { status: status });
      await refreshAfterMutation(status === "disabled" ? "账号已停用（会话立即失效）" : "账号已启用");
    } catch (e) {
      setAccountsHint("操作失败：" + (e.message || e), true);
    } finally {
      setStaffBusy(false);
    }
  }

  /* ---------- 邀请码复制 / 重置 ---------- */
  function inviteCodeValue() {
    var node = $("ent-code");
    if (!node) return "";
    var v = (node.textContent || "").trim();
    return v === "—" ? "" : v;
  }

  function copyInviteCode() {
    var code = inviteCodeValue();
    if (!code) {
      setStaffHint("当前账号没有可复制的邀请码。", true);
      return;
    }
    copyText(code)
      .then(function () {
        setStaffHint("邀请码已复制：" + code + "（旧码在重置前一直有效）");
      })
      .catch(function (e) {
        setStaffHint("复制失败：" + (e.message || e) + "，可手动选中邀请码复制。", true);
      });
  }

  function copyLoginLink() {
    var link = location.origin + "/login";
    copyText(link)
      .then(function () {
        setStaffHint("入职链接已复制：" + link);
      })
      .catch(function (e) {
        setStaffHint("复制失败：" + (e.message || e) + "，可手动选中链接复制。", true);
      });
  }

  function openInviteReset(target) {
    S.staff.resetTarget = target || null;
    var text = $("invite-reset-text");
    if (text) {
      text.textContent = target && target.id
        ? "确定重置企业「" + target.name + "」的邀请码？重置后旧邀请码立即失效：已经拿到旧码、但还没注册的同事将无法使用。"
        : "确定重置本企业的邀请码？重置后旧邀请码立即失效：已经拿到旧码、但还没注册的同事将无法使用。";
    }
    setText("invite-reset-hint", "");
    setClass("invite-reset-hint", "is-error", false);
    setDisabled("invite-reset-confirm", false);
    var modal = $("invite-reset-modal");
    if (modal) modal.hidden = false;
  }

  function closeInviteReset() {
    var modal = $("invite-reset-modal");
    if (modal) modal.hidden = true;
    S.staff.resetTarget = null;
  }

  async function confirmInviteReset() {
    var target = S.staff.resetTarget;
    if (!target) return;
    var btn = $("invite-reset-confirm");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "重置中…";
    }
    try {
      var body = target.id ? { enterprise_id: target.id } : {};
      var data = await postJson("/admin/enterprise/invite-code/reset", body);
      var ent = data.enterprise || null;
      if (ent) applyEnterpriseUpdate(ent);
      closeInviteReset();
      renderStaff();
      setStaffHint(
        ent
          ? "已重置「" + ent.name + "」的邀请码，旧邀请码已立即失效。新邀请码：" + (ent.invite_code || "—")
          : "邀请码已重置，旧邀请码已立即失效。"
      );
    } catch (e) {
      setText("invite-reset-hint", "重置失败：" + (e.message || e));
      setClass("invite-reset-hint", "is-error", true);
      if (btn) btn.disabled = false;
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "确认重置";
      }
    }
  }

  /* ================================================================
   * #/kb —— 概况 / 文档矩阵 / 重建 / 清空
   * ================================================================ */

  function resetKb() {
    S.kb.loading = false;
    S.kb.loaded = false;
    S.kb.promise = null;
    S.kb.error = null;
    S.kb.data = null;
    stopBuildPolling();
    S.kb.build.running = false;
    S.kb.build.taskId = null;
    setHidden("kb-build-panel", true);
    renderKbLoading();
  }

  function loadKb(force) {
    if (S.kb.loading) return S.kb.promise;
    if (S.kb.loaded && !force) return Promise.resolve();

    S.kb.loading = true;
    if (!S.kb.data) renderKbLoading();
    else setText("kb-dataset-tag", "刷新中…");

    S.kb.promise = (async function () {
      try {
        var data = await fetchJson("/api/kb/overview");
        S.kb.data = data;
        S.kb.loaded = true;
        S.kb.error = null;
        renderKb(data);
      } catch (e) {
        S.kb.error = e.message || String(e);
        renderKbError(e);
      } finally {
        S.kb.loading = false;
      }
    })();
    return S.kb.promise;
  }

  function renderKbLoading() {
    setText("kb-dataset-tag", "读取中…");
    setHidden("kb-readonly", true);
    setHidden("kb-overview", false);
    setHidden("kb-freshness", true);
    setHidden("kb-notes", true);
    setHidden("kb-empty", true);
    setHidden("kb-actions", true);
    setHidden("kb-docs-panel", true);
    setText("kb-source-hint", "");
    var grid = $("kb-overview");
    if (grid) {
      grid.innerHTML =
        '<div class="stat-card is-loading"></div>' +
        '<div class="stat-card is-loading"></div>' +
        '<div class="stat-card is-loading"></div>' +
        '<div class="stat-card is-loading"></div>';
    }
  }

  function renderKbError(err) {
    var msg = (err && err.message) || "未知错误";
    setText("kb-dataset-tag", "读取失败");
    setHidden("kb-overview", true);
    setHidden("kb-freshness", true);
    setHidden("kb-notes", true);
    setHidden("kb-actions", true);
    setHidden("kb-docs-panel", true);
    setHidden("kb-readonly", true);
    setText("kb-source-hint", "");
    showKbEmpty("知识库概况加载失败", "接口 /api/kb/overview 返回错误：" + msg + "。可点下方「刷新概况」重试。", true);
  }

  function showKbEmpty(title, text, showRetry) {
    setHidden("kb-empty", false);
    setText("kb-empty-title", title);
    setText("kb-empty-text", text);
    setHidden("kb-empty-retry", !showRetry);
  }

  function hideKbEmpty() {
    setHidden("kb-empty", true);
  }

  function setKbFlash(msg, isError) {
    var node = $("kb-flash");
    if (!node) return;
    node.hidden = !msg;
    node.textContent = msg || "";
    node.classList.toggle("is-error", !!isError);
  }

  function renderKb(data) {
    // 数据集 / 模式标签：全部来自接口，不猜租户
    var mode = data.mode === "demo" ? "演示数据集" : "企业数据空间";
    var tag = mode + (data.dataset ? " · " + data.dataset : "");
    setText("kb-dataset-tag", tag);

    // 只读提示：员工 / 系统管理员都会走到这里（can_write 由后端判定）
    if (!data.can_write) {
      setHidden("kb-readonly", false);
      setText("kb-readonly", data.readonly_reason || "当前账号只能查看知识库，不能重建或清空数据。");
    } else {
      setHidden("kb-readonly", true);
    }

    var emptyReason = "";
    if (!data.ready) {
      emptyReason = data.can_write
        ? "当前数据空间还没有构建：数据库尚未建立。请先去「数据导入」上传数据并完成构建，概况与文档矩阵会自动出现在这里。"
        : "当前数据空间还没有构建。请联系企业管理员先导入数据并完成构建。";
    } else if (data.empty) {
      emptyReason = data.can_write
        ? "数据空间已就绪，但里面还没有任何数据（切片数与画像数均为 0）。请先去「数据导入」上传数据并完成构建。"
        : "数据空间已就绪，但里面还没有任何数据。请联系企业管理员导入数据并完成构建。";
    }

    if (emptyReason) {
      setHidden("kb-overview", true);
      setHidden("kb-freshness", true);
      setHidden("kb-actions", true);
      setHidden("kb-docs-panel", true);
      setText("kb-source-hint", "");
      renderKbNotes(data.notes);
      showKbEmpty("还没有可管理的数据", emptyReason, true);
      return;
    }

    hideKbEmpty();
    setHidden("kb-overview", false);
    renderKbOverview(data);
    renderKbFreshness(data.freshness || {});
    renderKbNotes(data.notes);
    renderKbDocs(data);
    renderKbActions();
    renderKbSource(data);
    setHidden("kb-actions", false);
    setHidden("kb-docs-panel", false);
  }

  function renderKbOverview(data) {
    var totals = data.totals || {};
    var cards = [
      {
        value: fmtInt(totals.docs),
        label: "文档数",
        extra: "本数据空间已入库的 Markdown 文档",
      },
      {
        value: fmtInt(totals.chunks),
        label: "切片数",
        extra: "检索索引里的向量分块",
      },
      {
        value: fmtInt(totals.profiles),
        label: "画像数",
        extra: "用户画像向量条数",
      },
      {
        value: data.built_at || "—",
        label: "最近构建",
        extra: data.built_at ? "索引最近一次构建时间" : "还没有构建记录",
      },
    ];
    var grid = $("kb-overview");
    if (!grid) return;
    grid.innerHTML = cards
      .map(function (c) {
        return (
          '<div class="stat-card">' +
          '<div class="stat-value">' + esc(c.value) + "</div>" +
          '<div class="stat-label">' + esc(c.label) + "</div>" +
          '<div class="stat-extra">' + esc(c.extra) + "</div>" +
          "</div>"
        );
      })
      .join("");
  }

  function renderKbFreshness(freshness) {
    var status = freshness.status || "unknown";
    var map = {
      fresh: { label: "新鲜", cls: "is-fresh", width: 100 },
      stale: { label: "过期", cls: "is-stale", width: 55 },
      unknown: { label: "未知", cls: "is-unknown", width: 25 },
    };
    var info = map[status] || map.unknown;
    var box = $("kb-freshness");
    if (!box) return;
    box.hidden = false;
    box.className = "kb-fresh " + info.cls;
    setText("kb-fresh-status", info.label);
    setText("kb-fresh-reason", freshness.reason || "后端未给出原因");
    var fill = $("kb-fresh-fill");
    if (fill) fill.style.width = info.width + "%";
  }

  function renderKbNotes(notes) {
    var list = $("kb-notes");
    if (!list) return;
    if (!notes || !notes.length) {
      list.hidden = true;
      list.innerHTML = "";
      return;
    }
    list.hidden = false;
    list.innerHTML = notes
      .map(function (n) {
        return '<div class="kb-note">' + esc(n) + "</div>";
      })
      .join("");
  }

  function renderKbDocs(data) {
    var docs = data.docs || [];
    var totals = data.totals || {};
    var totalChunks = Number(totals.chunks) || 0;
    setText(
      "kb-docs-status",
      "共 " + fmtInt(docs.length) + " 篇文档 · " + fmtInt(totalChunks) + " 个切片"
    );
    var body = $("kb-docs-body");
    if (!body) return;
    if (!docs.length) {
      body.innerHTML =
        '<tr><td colspan="4" class="console-empty-cell">没有文档切片：当前数据空间可能只有画像数据，或文档还没构建索引。</td></tr>';
      return;
    }
    body.innerHTML = docs
      .map(function (d) {
        var chunks = Number(d.chunks) || 0;
        var chars = Number(d.chars) || 0;
        var ratio = totalChunks > 0 ? chunks / totalChunks : 0;
        var pct = Math.round(ratio * 1000) / 10;
        var width = chunks > 0 ? Math.max(2, Math.round(ratio * 100)) : 0;
        return (
          "<tr>" +
          '<td class="kb-doc-name">' + esc(d.doc_name || "—") + "</td>" +
          '<td class="console-num">' + fmtInt(chunks) + "</td>" +
          '<td class="console-num">' + fmtInt(chars) + "</td>" +
          "<td><div class=\"kb-ratio\">" +
          '<span class="kb-ratio-bar"><i style="width:' + width + '%"></i></span>' +
          '<span class="kb-ratio-text">' + pct.toFixed(1) + "%</span>" +
          "</div></td>" +
          "</tr>"
        );
      })
      .join("");
  }

  /** 重建 / 清空按钮的可用性：所有判断都来自 overview 接口，不自己猜 */
  function actionState() {
    var d = S.kb.data;
    if (!d) return null;
    var src = d.last_source || null;
    var running = S.kb.build.running;
    var write = !!d.can_write;
    var buildDisabled = !write || running || !src || src.available === false;
    var clearDisabled = !write || running || !d.ready || !!d.empty;
    var reason = "";
    if (!write) reason = d.readonly_reason || "当前账号为只读，不能重建或清空数据。";
    else if (running) reason = "重建任务进行中，完成后按钮会自动恢复。";
    else if (!src) reason = "还没有上一次构建的源记录：请先去「数据导入」(/wizard) 上传数据并完成一次构建。";
    else if (src.available === false) reason = "上一次构建的源文件已不存在：请先去「数据导入」(/wizard) 重新上传，再回来重建。";
    else reason = "重建会按最近一次构建的源重新执行（会先清空再重写）；清空会删除当前数据空间的全部数据，不可恢复。";
    return {
      write: write,
      src: src,
      running: running,
      buildDisabled: buildDisabled,
      clearDisabled: clearDisabled,
      reason: reason,
    };
  }

  function renderKbActions() {
    var state = actionState();
    if (!state) return;
    setDisabled("kb-rebuild-btn", state.buildDisabled);
    setDisabled("kb-clear-btn", state.clearDisabled);
    setText("kb-action-hint", state.reason);
    setClass("kb-action-hint", "is-error", !state.write);
    setDisabled("kb-refresh-btn", false);
  }

  function renderKbSource(data) {
    var src = data.last_source;
    var hint = $("kb-source-hint");
    if (!hint) return;
    if (!src) {
      hint.textContent = "暂无构建来源记录，重建不可用。";
      return;
    }
    var parts = ["最近构建来源：批次 " + (src.upload_id || "—")];
    if (typeof src.csv === "number") parts.push("CSV " + src.csv + " 个");
    if (typeof src.md === "number") parts.push("文档 " + src.md + " 篇");
    if (src.built_at) parts.push("构建于 " + src.built_at);
    if (src.available === false) parts.push("源文件已不在");
    hint.textContent = parts.join(" · ");
    hint.classList.toggle("is-error", src.available === false);
  }

  /* ---------- 重建（POST /api/wizard/build + 轮询） ---------- */
  async function startRebuild() {
    var state = actionState();
    if (!state || state.buildDisabled || !state.src) return;
    if (state.src.available === false) {
      setKbFlash("源文件已不存在，请先去「数据导入」重新上传。", true);
      return;
    }

    var build = S.kb.build;
    build.running = true;
    build.taskId = null;
    build.failures = 0;
    build.startedAt = Date.now();
    setKbFlash("");
    setHidden("kb-build-panel", false);
    setText("kb-build-status", "启动中…");
    setClass("kb-build-status", "is-danger", false);
    setText("kb-build-note", "正在提交构建任务…");
    setText("kb-build-pct", "0%");
    var fill = $("kb-build-fill");
    if (fill) fill.style.width = "0%";
    setHidden("kb-build-error", true);
    setHidden("kb-build-result", true);
    var steps = $("kb-build-steps");
    if (steps) steps.innerHTML = "";
    renderKbActions();

    try {
      var data = await postJson("/api/wizard/build", {
        upload_id: state.src.upload_id,
        fields: state.src.fields || {},
      });
      if (!data.task_id) throw new Error("接口没有返回 task_id，无法跟踪构建进度");
      build.taskId = data.task_id;
      setText("kb-build-status", "重建中…");
      setText(
        "kb-build-note",
        "任务已提交（" + (data.dataset || S.kb.data.dataset) + "），正在等待构建进度…"
      );
      scheduleBuildPoll();
    } catch (e) {
      build.running = false;
      renderKbActions();
      setText("kb-build-status", "启动失败");
      setClass("kb-build-status", "is-danger", true);
      showBuildError("重建启动失败：" + (e.message || e));
      setKbFlash("重建启动失败：" + (e.message || e), true);
    }
  }

  function showBuildError(msg) {
    setHidden("kb-build-error", false);
    setText("kb-build-error", msg);
  }

  function scheduleBuildPoll() {
    var build = S.kb.build;
    if (build.timer) clearTimeout(build.timer);
    build.timer = setTimeout(pollBuildOnce, 1200);
  }

  function stopBuildPolling() {
    var build = S.kb.build;
    if (build.timer) clearTimeout(build.timer);
    build.timer = null;
  }

  async function pollBuildOnce() {
    var build = S.kb.build;
    if (!build.running || !build.taskId) return;

    // 兜底：任务可能因为服务重启而永远 running，别让轮询跑到天荒地老
    if (Date.now() - build.startedAt > 20 * 60 * 1000) {
      stopBuildPolling();
      build.running = false;
      renderKbActions();
      setText("kb-build-status", "已停止轮询");
      setClass("kb-build-status", "is-danger", true);
      showBuildError("构建任务超过 20 分钟仍未完成，已停止轮询。可点「刷新概况」查看当前状态。");
      return;
    }

    try {
      var task = await fetchJson("/api/wizard/build/" + encodeURIComponent(build.taskId));
      build.failures = 0;
      renderBuildTask(task);
      if (task.status === "done") {
        finishBuild(true, task);
        return;
      }
      if (task.status === "failed") {
        finishBuild(false, task);
        return;
      }
      scheduleBuildPoll();
    } catch (e) {
      build.failures += 1;
      if (build.failures >= 3) {
        stopBuildPolling();
        build.running = false;
        renderKbActions();
        setText("kb-build-status", "进度查询失败");
        setClass("kb-build-status", "is-danger", true);
        showBuildError("连续查询构建进度失败：" + (e.message || e) + "。构建可能仍在进行，可稍后点「刷新概况」确认。");
        return;
      }
      setText("kb-build-status", "进度查询失败，重试中…");
      scheduleBuildPoll();
    }
  }

  async function finishBuild(ok, task) {
    var build = S.kb.build;
    build.running = false;
    stopBuildPolling();
    renderBuildTask(task);
    renderKbActions();
    var note = ok
      ? (task.note || "重建完成，索引已更新。")
      : ("重建失败：" + (task.note || task.error || "未知错误"));
    await loadKb(true);
    setKbFlash(note, !ok);
  }

  function renderBuildTask(task) {
    task = task || {};
    var pct = Math.max(0, Math.min(100, Number(task.percent) || 0));
    var fill = $("kb-build-fill");
    if (fill) fill.style.width = pct + "%";
    setText("kb-build-pct", pct + "%");
    setText("kb-build-note", task.note || "");
    var status = task.status || "running";
    var statusText =
      status === "done" ? "已完成" : status === "failed" ? "构建失败" : "重建中…";
    setText("kb-build-status", statusText);
    setClass("kb-build-status", "is-danger", status === "failed");
    renderBuildSteps(task.steps || []);

    if (status === "failed") {
      setHidden("kb-build-result", true);
      showBuildError(task.note || task.error || "构建失败");
    } else {
      setHidden("kb-build-error", true);
      if (status === "done") {
        setHidden("kb-build-result", false);
        setText("kb-build-result", task.note || "重建完成。");
      } else {
        setHidden("kb-build-result", true);
      }
    }
  }

  function renderBuildSteps(steps) {
    var box = $("kb-build-steps");
    if (!box) return;
    if (!steps.length) {
      box.innerHTML = '<div class="console-hint">等待构建事件…</div>';
      return;
    }
    var stateLabels = {
      pending: "待处理",
      running: "进行中",
      done: "完成",
      skipped: "已跳过",
      failed: "失败",
    };
    box.innerHTML = steps
      .map(function (s) {
        var status = s.status || "pending";
        var pct =
          status === "done" || status === "skipped"
            ? 100
            : Math.max(0, Math.min(100, Number(s.percent) || 0));
        var count = "";
        if (s.total) {
          count =
            fmtInt(s.processed) + " / " + fmtInt(s.total) + " " + esc(s.unit || "");
        }
        return (
          '<div class="kb-step is-' + esc(status) + '">' +
          '<div class="kb-step-head">' +
          '<span class="kb-step-label">' + esc(s.label || s.key || "—") + "</span>" +
          '<span class="kb-step-state">' + esc(stateLabels[status] || status) + "</span>" +
          "</div>" +
          '<div class="kb-step-bar"><i style="width:' + pct + '%"></i></div>' +
          (count ? '<div class="kb-step-count">' + count + "</div>" : "") +
          "</div>"
        );
      })
      .join("");
  }

  /* ---------- 清空（POST /api/kb/clear，输入 dataset 字面值确认） ---------- */
  function openClearModal() {
    var data = S.kb.data;
    if (!data || !data.dataset) return;
    if (!data.can_write || !data.ready || data.empty) return;
    setText("kb-clear-dataset", data.dataset);
    var input = $("kb-clear-input");
    if (input) input.value = "";
    setDisabled("kb-clear-confirm", true);
    setText("kb-clear-hint", "需与 dataset 名称完全一致（区分大小写）");
    setClass("kb-clear-hint", "is-error", false);
    var modal = $("kb-clear-modal");
    if (modal) modal.hidden = false;
    if (input) {
      setTimeout(function () {
        input.focus();
      }, 0);
    }
  }

  function closeClearModal() {
    var modal = $("kb-clear-modal");
    if (modal) modal.hidden = true;
    setDisabled("kb-clear-confirm", true);
  }

  function onClearInput() {
    var data = S.kb.data;
    var input = $("kb-clear-input");
    if (!data || !input) return;
    var matched = input.value.trim() === data.dataset;
    setDisabled("kb-clear-confirm", !matched);
    setText(
      "kb-clear-hint",
      matched ? "dataset 名称已确认，可以清空。" : "需与 dataset 名称完全一致（区分大小写）"
    );
    setClass("kb-clear-hint", "is-error", false);
  }

  async function confirmClear() {
    var data = S.kb.data;
    if (!data || !data.dataset || S.kb.clearBusy) return;
    var input = $("kb-clear-input");
    if (!input || input.value.trim() !== data.dataset) {
      setText("kb-clear-hint", "输入的 dataset 名称不一致，已取消。");
      setClass("kb-clear-hint", "is-error", true);
      return;
    }

    S.kb.clearBusy = true;
    setDisabled("kb-clear-confirm", true);
    setDisabled("kb-clear-cancel", true);
    setText("kb-clear-hint", "正在清空…");
    setClass("kb-clear-hint", "is-error", false);

    try {
      var result = await postJson("/api/kb/clear", { confirm: data.dataset });
      var cleared = result.cleared || {};
      closeClearModal();
      await loadKb(true);
      setKbFlash(
        "已清空 dataset " + (result.dataset || data.dataset) +
        "：画像 " + fmtInt(cleared.profiles) + " 条、切片 " + fmtInt(cleared.chunks) +
        " 条、索引 " + fmtInt(cleared.index) + " 条。此操作不可恢复。",
        false
      );
    } catch (e) {
      setText("kb-clear-hint", "清空失败：" + (e.message || e));
      setClass("kb-clear-hint", "is-error", true);
      setDisabled("kb-clear-confirm", false);
    } finally {
      S.kb.clearBusy = false;
      setDisabled("kb-clear-cancel", false);
    }
  }

  /* ================================================================
   * 事件绑定（只绑一次；内容区是重新渲染的，所以用容器委托）
   * ================================================================ */
  function bindEvents() {
    // ---- #/staff ----
    on("invite-copy", "click", copyInviteCode);
    on("invite-link-copy", "click", copyLoginLink);
    on("invite-reset", "click", function () {
      // 企业管理员：本企业；系统管理员没有自己的企业，重置入口在「企业总览」行内
      openInviteReset({ id: null, name: (currentEnterprise() || {}).name || "" });
    });

    on("invite-reset-cancel", "click", closeInviteReset);
    on("invite-reset-confirm", "click", confirmInviteReset);
    on("invite-reset-modal", "click", function (e) {
      if (e.target && e.target.getAttribute("data-close")) closeInviteReset();
    });

    on("member-refresh", "click", function () {
      loadStaff(true);
    });

    on("member-filters", "click", function (e) {
      var btn = e.target.closest("button[data-filter]");
      if (!btn) return;
      S.staff.filter = btn.dataset.filter || "all";
      renderMembersFromState();
    });

    on("member-search", "input", function (e) {
      S.staff.query = e.target.value || "";
      renderMembersFromState();
    });

    on("accounts-list", "click", function (e) {
      var approve = e.target.closest("button[data-approve]");
      if (approve) {
        var id = approve.dataset.approve;
        var sel = document.querySelector('select[data-approve-role="' + id + '"]');
        var chosen = sel ? sel.value : fallbackRole((S.staff.data || {}).roles || []);
        approveMember(id, chosen);
        return;
      }
      var reject = e.target.closest("button[data-reject]");
      if (reject) {
        rejectMember(reject.dataset.reject);
        return;
      }
      var disable = e.target.closest("button[data-disable]");
      if (disable) {
        setMemberStatus(disable.dataset.disable, "disabled");
        return;
      }
      var enable = e.target.closest("button[data-enable]");
      if (enable) setMemberStatus(enable.dataset.enable, "active");
    });

    on("accounts-list", "change", function (e) {
      var sel = e.target.closest("select[data-role]");
      if (sel) changeMemberRole(sel.dataset.role, sel.value);
    });

    on("enterprises-body", "click", function (e) {
      var copyBtn = e.target.closest("button[data-copy-ent]");
      if (copyBtn) {
        var ent = findEnterpriseById(copyBtn.dataset.copyEnt);
        if (ent && ent.invite_code) {
          copyText(ent.invite_code)
            .then(function () {
              setStaffHint("已复制「" + ent.name + "」的邀请码：" + ent.invite_code);
            })
            .catch(function (err) {
              setStaffHint("复制失败：" + (err.message || err), true);
            });
        }
        return;
      }
      var resetBtn = e.target.closest("button[data-reset-ent]");
      if (resetBtn) {
        var ent2 = findEnterpriseById(resetBtn.dataset.resetEnt);
        if (ent2) openInviteReset({ id: ent2.id, name: ent2.name });
      }
    });

    // ---- #/kb ----
    on("kb-rebuild-btn", "click", startRebuild);
    on("kb-clear-btn", "click", openClearModal);
    on("kb-refresh-btn", "click", function () {
      loadKb(true);
    });
    on("kb-empty-retry", "click", function () {
      loadKb(true);
    });
    on("kb-clear-cancel", "click", closeClearModal);
    on("kb-clear-confirm", "click", confirmClear);
    on("kb-clear-input", "input", onClearInput);
    on("kb-clear-input", "keydown", function (e) {
      if (e.key === "Enter" && !e.target.disabled) confirmClear();
    });
    on("kb-clear-modal", "click", function (e) {
      if (e.target && e.target.getAttribute("data-close")) closeClearModal();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (!$("kb-clear-modal").hidden) closeClearModal();
      else if (!$("invite-reset-modal").hidden) closeInviteReset();
    });
  }

  function init() {
    bindEvents();
    syncRoute();
  }

  /* ---------- 启动 ---------- */
  // 路由 / 能力事件在脚本执行时立刻注册：app.js 的 whoami 是异步的，
  // 事件会在 DOMContentLoaded 之后才派发，不会漏。
  window.addEventListener("hashchange", syncRoute);
  window.addEventListener("rag:capabilities", onCapabilities);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
