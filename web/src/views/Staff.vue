<script setup>
/**
 * 员工管理：GET /admin/users（成员列表 / 审核 / 改角色 / 停用启用）
 * + 邀请码卡（复制 / 重置，POST /admin/enterprise/invite-code/reset）
 * + 系统管理员专属的企业总览 GET /admin/enterprises。
 *
 * 越权规则前端只做"不显示入口"：真正拦截在后端（_check_target_scope）。
 */
import { computed, onMounted, reactive, ref } from "vue";
import { getJson, postJson } from "../api";
import { store, toast, toastError } from "../store";
import ConfirmButton from "../components/ConfirmButton.vue";

const data = ref(null);
const loading = ref(true);
const loadError = ref("");
const filter = ref("all");
const keyword = ref("");
const busyId = ref(null);
const roleDraft = reactive({});

const enterprises = ref(null);
const enterprisesError = ref("");
const entBusyId = ref(null);
const resettingInvite = ref(false);

const isSysAdmin = computed(() => !!(store.account && store.account.is_system_admin));
const me = computed(() => (data.value && data.value.me) || store.account || {});
const users = computed(() => (data.value && data.value.users) || []);
const roles = computed(() => (data.value && data.value.roles) || []);
const scopeLabel = computed(() => (data.value && data.value.scope === "all" ? "全部企业" : "本企业"));

const statusTabs = computed(() => {
  const all = users.value;
  return [
    { key: "all", label: "全部", count: all.length },
    { key: "pending", label: "待审核", count: all.filter((u) => u.status === "pending").length },
    { key: "active", label: "正常", count: all.filter((u) => u.status === "active").length },
    { key: "disabled", label: "已停用", count: all.filter((u) => u.status === "disabled").length },
    { key: "rejected", label: "已拒绝", count: all.filter((u) => u.status === "rejected").length },
  ];
});

const enterpriseMap = computed(() => {
  const map = {};
  for (const ent of (data.value && data.value.enterprises) || []) map[ent.id] = ent;
  return map;
});

const filteredUsers = computed(() => {
  const kw = keyword.value.trim().toLowerCase();
  return users.value.filter((u) => {
    if (filter.value !== "all" && u.status !== filter.value) return false;
    if (!kw) return true;
    const ent = enterpriseMap.value[u.enterprise_id];
    const hay = [
      u.username,
      u.display_name,
      u.contact,
      u.role_label,
      u.status_label,
      ent && ent.name,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return hay.includes(kw);
  });
});

/** 企业管理员视角：只看得到本企业；系统管理员看全部 */
const myEnterprise = computed(() => {
  if (!data.value) return null;
  const list = data.value.enterprises || [];
  if (isSysAdmin.value) return null; // 系统管理员没有自己的企业，走企业总览重置
  return list[0] || (store.account && store.account.enterprise) || null;
});

const totalStats = computed(() => {
  const list = enterprises.value && enterprises.value.enterprises;
  if (list) return enterprises.value.totals || null;
  const all = users.value;
  return {
    members: all.filter((u) => u.status === "active").length,
    pending: all.filter((u) => u.status === "pending").length,
    disabled: all.filter((u) => u.status === "disabled").length,
  };
});

async function loadUsers() {
  loading.value = true;
  loadError.value = "";
  try {
    data.value = await getJson("/admin/users");
    for (const u of data.value.users || []) roleDraft[u.id] = u.role;
  } catch (e) {
    loadError.value = e.detail || e.message || "成员列表加载失败";
  } finally {
    loading.value = false;
  }
}

async function loadEnterprises() {
  enterprisesError.value = "";
  try {
    enterprises.value = await getJson("/admin/enterprises");
  } catch (e) {
    enterprisesError.value = e.detail || e.message || "企业总览加载失败";
  }
}

onMounted(async () => {
  await loadUsers();
  if (isSysAdmin.value) await loadEnterprises();
});

async function refreshAll() {
  await loadUsers();
  if (isSysAdmin.value) await loadEnterprises();
}

function entName(u) {
  const ent = enterpriseMap.value[u.enterprise_id];
  return ent ? ent.name : u.enterprise_id ? `企业 #${u.enterprise_id}` : "—";
}

/** 当前操作者能不能改这个账号（后端会再校验一次；这里只是别显示按不动的按钮） */
function canManage(u) {
  if (!u || u.is_system_admin) return false;
  if (isSysAdmin.value) return true;
  if (!me.value || !me.value.enterprise_id) return false;
  if (u.enterprise_id !== me.value.enterprise_id) return false;
  if (u.account_type === "enterprise") return false; // 企业账号只能系统管理员审核
  if (u.is_enterprise_admin) return false; // 企业管理员之间不能互改
  return true;
}

function statusBadge(u) {
  if (u.status === "active") return "is-success";
  if (u.status === "pending") return "is-warn";
  if (u.status === "disabled" || u.status === "rejected") return "is-danger";
  return "";
}

async function approve(u) {
  if (busyId.value) return;
  busyId.value = u.id;
  try {
    const body = u.account_type === "enterprise" ? {} : { role: roleDraft[u.id] || "cs" };
    await postJson(`/admin/users/${u.id}/approve`, body);
    toast(`已通过 ${u.display_name || u.username} 的申请`, "success");
    await loadUsers();
    if (isSysAdmin.value) loadEnterprises();
  } catch (e) {
    toastError(e);
  } finally {
    busyId.value = null;
  }
}

async function reject(u) {
  busyId.value = u.id;
  try {
    await postJson(`/admin/users/${u.id}/reject`, {});
    toast(`已拒绝 ${u.display_name || u.username} 的申请`, "info");
    await loadUsers();
  } catch (e) {
    toastError(e);
  } finally {
    busyId.value = null;
  }
}

async function changeRole(u, role) {
  if (!role || role === u.role) {
    roleDraft[u.id] = u.role;
    return;
  }
  busyId.value = u.id;
  try {
    await postJson(`/admin/users/${u.id}/role`, { role });
    toast(`已把 ${u.display_name || u.username} 的角色改为 ${labelOfRole(role)}`, "success");
    await loadUsers();
  } catch (e) {
    roleDraft[u.id] = u.role;
    toastError(e);
  } finally {
    busyId.value = null;
  }
}

async function setStatus(u, status) {
  busyId.value = u.id;
  try {
    await postJson(`/admin/users/${u.id}/status`, { status });
    toast(status === "disabled" ? `已停用 ${u.display_name || u.username}` : `已启用 ${u.display_name || u.username}`, "success");
    await loadUsers();
  } catch (e) {
    toastError(e);
  } finally {
    busyId.value = null;
  }
}

function labelOfRole(role) {
  const item = roles.value.find((r) => r.value === role);
  return item ? item.label : role;
}

/* ---------- 邀请码 ---------- */
async function copyCode(code) {
  if (!code) return;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(code);
    } else {
      const ta = document.createElement("textarea");
      ta.value = code;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    toast("邀请码已复制", "success");
  } catch {
    toast("复制失败，请手动选中复制", "warn");
  }
}

async function resetInvite() {
  if (!myEnterprise.value || resettingInvite.value) return;
  resettingInvite.value = true;
  try {
    const body = isSysAdmin.value ? { enterprise_id: myEnterprise.value.id } : {};
    const res = await postJson("/admin/enterprise/invite-code/reset", body);
    applyEnterprise(res.enterprise);
    toast("邀请码已重置，旧邀请码立即失效", "success", 4600);
    await loadUsers();
  } catch (e) {
    toastError(e);
  } finally {
    resettingInvite.value = false;
  }
}

async function resetEnterpriseInvite(ent) {
  if (entBusyId.value) return;
  entBusyId.value = ent.id;
  try {
    const res = await postJson("/admin/enterprise/invite-code/reset", { enterprise_id: ent.id });
    applyEnterprise(res.enterprise);
    toast(`已重置「${ent.name}」的邀请码`, "success", 4200);
    await loadEnterprises();
    await loadUsers();
  } catch (e) {
    toastError(e);
  } finally {
    entBusyId.value = null;
  }
}

function applyEnterprise(ent) {
  if (!ent) return;
  if (data.value) {
    data.value.enterprises = (data.value.enterprises || []).map((x) =>
      x.id === ent.id ? { ...x, ...ent } : x
    );
  }
  if (enterprises.value && enterprises.value.enterprises) {
    enterprises.value.enterprises = enterprises.value.enterprises.map((x) =>
      x.id === ent.id ? { ...x, ...ent } : x
    );
  }
}

function entStatusBadge(ent) {
  return ent.dataset_ready ? "is-success" : "is-warn";
}
</script>

<template>
  <div class="page">
    <div class="kb-hero">
      <div>
        <div class="kb-title-line">
          <h2 style="font-size: 20px">成员与邀请</h2>
          <span class="badge is-primary">{{ scopeLabel }}</span>
          <span class="badge" v-if="isSysAdmin">系统管理员视角</span>
          <span class="badge" v-else>企业管理员视角</span>
        </div>
        <p class="card-sub" style="margin-top: 6px">
          审核注册申请、分配角色、停用账号；角色决定默认等级（可见信息范围），改完立即生效。
        </p>
      </div>
      <button type="button" class="btn btn-ghost" @click="refreshAll">刷新</button>
    </div>

    <div v-if="loading" class="card">
      <div class="skeleton" style="height: 18px; width: 36%"></div>
      <div class="skeleton" style="height: 48px; margin-top: 14px"></div>
      <div class="skeleton" style="height: 148px; margin-top: 14px"></div>
    </div>

    <div v-else-if="loadError" class="card">
      <div class="empty-state">
        <div class="empty-emoji">⛔</div>
        <div class="empty-title">无法加载成员列表</div>
        <div class="empty-desc">{{ loadError }}</div>
        <div class="row-actions">
          <button type="button" class="btn btn-primary" @click="loadUsers">重试</button>
          <a class="btn btn-ghost" href="/">回工作台</a>
        </div>
      </div>
    </div>

    <template v-else>
      <div class="staff-grid">
        <div>
          <!-- 成员统计 + 筛选 -->
          <section class="card">
            <div class="card-title">
              <span class="dot"></span>成员
              <span class="spacer"></span>
              <span class="card-sub" v-if="totalStats">
                正常 {{ totalStats.members ?? "—" }} · 待审核 {{ totalStats.pending ?? "—" }}
                <template v-if="totalStats.disabled != null"> · 停用 {{ totalStats.disabled }}</template>
              </span>
            </div>

            <div class="toolbar" style="margin-bottom: 14px">
              <button
                v-for="tab in statusTabs"
                :key="tab.key"
                type="button"
                class="chip"
                :class="{ 'is-active': filter === tab.key }"
                @click="filter = tab.key"
              >
                {{ tab.label }} <span class="field-hint">{{ tab.count }}</span>
              </button>
              <span class="spacer"></span>
              <input v-model="keyword" class="input" style="max-width: 230px" type="search" placeholder="搜索用户名 / 姓名 / 企业" />
            </div>

            <div v-if="filteredUsers.length">
              <div v-for="u in filteredUsers" :key="u.id" class="user-row">
                <span class="user-avatar">{{ (u.display_name || u.username || "?").slice(0, 1) }}</span>
                <div class="user-main">
                  <div class="user-name-line">
                    <span class="user-name">{{ u.display_name || u.username }}</span>
                    <span class="user-username">@{{ u.username }}</span>
                    <span class="badge" :class="statusBadge(u)">{{ u.status_label || u.status }}</span>
                    <span class="badge">{{ u.account_type_label || u.account_type }}</span>
                    <span class="badge is-primary">{{ u.role_label || u.role }}</span>
                    <span v-if="u.is_enterprise_admin" class="badge is-warn">企业管理员</span>
                    <span v-if="u.is_system_admin" class="badge is-warn">系统管理员</span>
                  </div>
                  <div class="user-sub">
                    <span>企业：{{ entName(u) }}</span>
                    <span v-if="u.contact">联系方式：{{ u.contact }}</span>
                    <span v-if="u.created_at">注册：{{ u.created_at }}</span>
                    <span v-if="u.reviewed_by">审核人：{{ u.reviewed_by }}</span>
                    <span v-if="u.last_login_at">最近登录：{{ u.last_login_at }}</span>
                    <span v-if="u.id === me.id">这是你本人</span>
                  </div>
                </div>

                <div class="user-actions" v-if="canManage(u)">
                  <template v-if="u.status === 'pending'">
                    <select
                      v-if="u.account_type !== 'enterprise'"
                      v-model="roleDraft[u.id]"
                      class="select"
                      :disabled="busyId === u.id"
                    >
                      <option v-for="r in roles" :key="r.value" :value="r.value">{{ r.label }}（{{ r.level }}）</option>
                    </select>
                    <button type="button" class="btn btn-sm btn-primary" :disabled="busyId === u.id" @click="approve(u)">
                      通过
                    </button>
                    <ConfirmButton label="拒绝" confirm-text="确认拒绝？" kind="danger" :busy="busyId === u.id" @confirm="reject(u)" />
                  </template>

                  <template v-else-if="u.status === 'active'">
                    <select
                      v-if="u.account_type !== 'enterprise'"
                      :value="roleDraft[u.id] || u.role"
                      class="select"
                      :disabled="busyId === u.id"
                      @change="changeRole(u, $event.target.value)"
                    >
                      <option v-for="r in roles" :key="r.value" :value="r.value">{{ r.label }}（{{ r.level }}）</option>
                    </select>
                    <ConfirmButton label="停用" confirm-text="确认停用？" kind="danger" :busy="busyId === u.id" @confirm="setStatus(u, 'disabled')" />
                  </template>

                  <template v-else-if="u.status === 'disabled'">
                    <button type="button" class="btn btn-sm btn-soft" :disabled="busyId === u.id" @click="setStatus(u, 'active')">启用</button>
                  </template>

                  <template v-else-if="u.status === 'rejected'">
                    <select
                      v-if="u.account_type !== 'enterprise'"
                      v-model="roleDraft[u.id]"
                      class="select"
                      :disabled="busyId === u.id"
                    >
                      <option v-for="r in roles" :key="r.value" :value="r.value">{{ r.label }}（{{ r.level }}）</option>
                    </select>
                    <button type="button" class="btn btn-sm btn-primary" :disabled="busyId === u.id" @click="approve(u)">改判通过</button>
                  </template>
                </div>
                <div class="user-actions" v-else-if="u.id === me.id">
                  <span class="field-hint">（当前登录账号）</span>
                </div>
                <div class="user-actions" v-else>
                  <span class="field-hint">仅系统管理员可调整</span>
                </div>
              </div>
            </div>
            <div v-else class="empty-state" style="padding: 32px 12px">
              <div class="empty-emoji">🗂️</div>
              <div class="empty-title">没有匹配的成员</div>
              <div class="empty-desc">换个筛选条件或关键词试试。</div>
            </div>

            <p class="field-hint" style="margin-top: 12px">
              角色 → 默认等级：管理层 L3 / 数据分析师 L2 / 运营 L2 / 销售 L1。等级决定能看到的信息范围；
              企业管理员与企业账号的具体调整需系统管理员操作。
            </p>
          </section>
        </div>

        <div>
          <!-- 邀请码卡：企业管理员（系统管理员走下方企业总览逐企业重置） -->
          <section v-if="!isSysAdmin && myEnterprise" class="invite-card">
            <div class="invite-label">企业邀请码</div>
            <div class="invite-code" :class="{ 'is-empty': !myEnterprise.invite_code }">
              {{ myEnterprise.invite_code || "未生成" }}
            </div>
            <div class="invite-meta">
              {{ myEnterprise.name }} · 数据集 {{ myEnterprise.dataset || "—" }}
            </div>
            <div class="invite-actions">
              <button type="button" class="btn btn-sm" @click="copyCode(myEnterprise.invite_code)">复制邀请码</button>
              <ConfirmButton
                label="重置邀请码"
                confirm-text="确认重置？旧码立即失效"
                kind="ghost"
                :busy="resettingInvite"
                @confirm="resetInvite"
              />
            </div>
            <p class="invite-meta" style="margin-top: 12px; opacity: 0.85">
              新员工在 <a href="/login" style="color: #fff; text-decoration: underline">登录页</a>
              选择「员工注册」，填写该邀请码即可加入本企业（注册后需审核）。
            </p>
          </section>

          <section v-else-if="!isSysAdmin" class="card">
            <div class="empty-state" style="padding: 24px 8px">
              <div class="empty-desc">当前账号没有关联企业，无法展示邀请码。</div>
            </div>
          </section>

          <!-- 企业总览（系统管理员） -->
          <section v-if="isSysAdmin" class="card" style="margin-top: 0">
            <div class="card-title">
              <span class="dot"></span>企业总览
              <span class="spacer"></span>
              <button type="button" class="btn btn-sm btn-ghost" @click="loadEnterprises">刷新</button>
            </div>

            <div v-if="enterprisesError" class="alert is-info">
              企业总览暂不可用：{{ enterprisesError }}
            </div>
            <template v-else-if="enterprises">
              <div class="ent-total-grid">
                <div class="ent-total">
                  <div class="ent-total-value">{{ enterprises.totals?.enterprises ?? "—" }}</div>
                  <div class="ent-total-label">企业</div>
                </div>
                <div class="ent-total">
                  <div class="ent-total-value">{{ enterprises.totals?.members ?? "—" }}</div>
                  <div class="ent-total-label">正常成员</div>
                </div>
                <div class="ent-total">
                  <div class="ent-total-value">{{ enterprises.totals?.pending ?? "—" }}</div>
                  <div class="ent-total-label">待审核</div>
                </div>
              </div>

              <div v-if="enterprises.enterprises && enterprises.enterprises.length" class="table-wrap">
                <table class="table">
                  <thead>
                    <tr>
                      <th>企业</th>
                      <th>数据集</th>
                      <th class="num">成员</th>
                      <th class="num">待审核</th>
                      <th>库状态</th>
                      <th>最近构建</th>
                      <th>邀请码</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="ent in enterprises.enterprises" :key="ent.id">
                      <td>
                        <div style="font-weight: 600; color: var(--text)">{{ ent.name }}</div>
                        <div class="field-hint">#{{ ent.id }} · 创建于 {{ ent.created_at || "—" }}</div>
                      </td>
                      <td><span class="kb-dataset">{{ ent.dataset }}</span></td>
                      <td class="num">{{ ent.members ?? 0 }}</td>
                      <td class="num">{{ ent.pending ?? 0 }}</td>
                      <td>
                        <span class="badge" :class="entStatusBadge(ent)">
                          {{ ent.dataset_ready ? "已构建" : "未构建" }}
                        </span>
                      </td>
                      <td>{{ ent.last_build_at || "—" }}</td>
                      <td>
                        <div class="row-actions">
                          <code style="font-size: 12px">{{ ent.invite_code || "—" }}</code>
                          <button type="button" class="btn btn-sm btn-ghost" @click="copyCode(ent.invite_code)">复制</button>
                        </div>
                      </td>
                      <td>
                        <ConfirmButton
                          label="重置"
                          confirm-text="确认重置？"
                          kind="danger"
                          :busy="entBusyId === ent.id"
                          @confirm="resetEnterpriseInvite(ent)"
                        />
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-else class="empty-state" style="padding: 26px 10px">
                <div class="empty-desc">还没有企业注册。</div>
              </div>
            </template>
            <div v-else class="skeleton" style="height: 120px"></div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
