<script setup>
/**
 * 权限配置（仅 whoami.can.ops，默认系统管理员）：
 * GET /admin/permissions 渲染「等级 × 能力」矩阵 + 角色 → 默认等级；
 * PUT /admin/permissions 整份保存；一键全开；POST /admin/permissions/reset 恢复默认。
 *
 * 能力 / 等级 / 角色目录全部由后端返回，前端不写死清单。
 * 人员级授权（user_levels）本页只读展示，编辑入口留给后续迭代。
 */
import { computed, onMounted, reactive, ref } from "vue";
import { getJson, postJson, putJson } from "../api";
import { hasCap, refreshWhoami, toast, toastError } from "../store";
import ConfirmButton from "../components/ConfirmButton.vue";

const data = ref(null);
const loading = ref(true);
const loadError = ref("");
const saving = ref(false);
const resetting = ref(false);
const levels = reactive({});
const roleLevels = reactive({});
const baseline = ref("{}");

const canOps = computed(() => hasCap("ops"));

function snapshot() {
  const lv = {};
  for (const key of Object.keys(levels)) lv[key] = [...(levels[key] || [])].sort();
  const rl = { ...roleLevels };
  return JSON.stringify({ levels: lv, role_levels: rl });
}

function hydrate(config) {
  for (const key of Object.keys(levels)) delete levels[key];
  for (const key of Object.keys(roleLevels)) delete roleLevels[key];
  const cfgLevels = (config && config.levels) || {};
  for (const key of Object.keys(cfgLevels)) levels[key] = [...cfgLevels[key]];
  const cfgRoles = (config && config.role_levels) || {};
  for (const key of Object.keys(cfgRoles)) roleLevels[key] = cfgRoles[key];
  baseline.value = snapshot();
}

const dirty = computed(() => snapshot() !== baseline.value);

const userLevels = computed(() => {
  const map = (data.value && data.value.config && data.value.config.user_levels) || {};
  return Object.entries(map).map(([uid, item]) => ({ uid, ...(item || {}) }));
});

async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    data.value = await getJson("/admin/permissions");
    hydrate(data.value.config);
  } catch (e) {
    loadError.value = e.detail || e.message || "权限配置加载失败";
  } finally {
    loading.value = false;
  }
}

async function save() {
  if (!data.value || saving.value) return;
  saving.value = true;
  try {
    const body = { levels: {}, role_levels: {} };
    for (const lv of data.value.levels) body.levels[lv.value] = [...(levels[lv.value] || [])];
    for (const role of data.value.roles) body.role_levels[role.value] = roleLevels[role.value];
    const res = await putJson("/admin/permissions", body);
    if (res && res.config) {
      data.value.config = res.config;
      hydrate(res.config);
    }
    toast("权限配置已保存，下一个请求立即生效", "success", 4200);
    refreshWhoami().catch(() => {});
  } catch (e) {
    toastError(e);
  } finally {
    saving.value = false;
  }
}

async function enableAll() {
  if (!data.value) return;
  const allCaps = data.value.capabilities.map((c) => c.value);
  for (const lv of data.value.levels) levels[lv.value] = [...allCaps];
  toast("已全部勾选（尚未保存），确认无误后点「保存配置」", "info", 4600);
}

async function restoreDefaults() {
  if (resetting.value) return;
  resetting.value = true;
  try {
    const res = await postJson("/admin/permissions/reset", {});
    if (res && res.config) {
      data.value.config = res.config;
      hydrate(res.config);
    }
    toast("已恢复默认权限配置", "success");
    refreshWhoami().catch(() => {});
  } catch (e) {
    toastError(e);
  } finally {
    resetting.value = false;
  }
}

function toggleCap(levelValue, capValue) {
  if (!levels[levelValue]) levels[levelValue] = [];
  const arr = levels[levelValue];
  const i = arr.indexOf(capValue);
  if (i >= 0) arr.splice(i, 1);
  else arr.push(capValue);
}

function hasCapInLevel(levelValue, capValue) {
  return !!(levels[levelValue] || []).includes(capValue);
}

function levelLabel(value) {
  const item = data.value && data.value.levels.find((lv) => lv.value === value);
  return item ? item.label : value;
}

onMounted(load);
</script>

<template>
  <div class="page">
    <div class="kb-hero">
      <div>
        <div class="kb-title-line">
          <h2 style="font-size: 20px">权限配置</h2>
          <span class="badge is-primary">等级 × 能力</span>
          <span class="badge" v-if="dirty">有未保存修改</span>
          <span class="badge is-success" v-else-if="data">与已保存配置一致</span>
        </div>
        <p class="card-sub" style="margin-top: 6px">
          勾选每个等级能看到的能力。配置保存后立即生效（后端每个请求都会重新解析身份与配置），无需重启。
        </p>
      </div>
      <div class="row-actions">
        <button type="button" class="btn btn-ghost" :disabled="saving || !data" @click="load">重新加载</button>
        <button type="button" class="btn btn-ghost" :disabled="saving || !data" @click="enableAll">一键全开</button>
        <ConfirmButton
          label="恢复默认"
          confirm-text="确认恢复默认？"
          kind="ghost"
          :busy="resetting"
          :disabled="!data"
          @confirm="restoreDefaults"
        />
        <button type="button" class="btn btn-primary" :disabled="saving || !data || !dirty" @click="save">
          <span v-if="saving" class="spinner spinner-sm" />
          {{ saving ? "保存中…" : "保存配置" }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="card">
      <div class="skeleton" style="height: 20px; width: 40%"></div>
      <div class="skeleton" style="height: 220px; margin-top: 16px"></div>
    </div>

    <div v-else-if="loadError" class="card">
      <div class="empty-state">
        <div class="empty-emoji">⛔</div>
        <div class="empty-title">无法加载权限配置</div>
        <div class="empty-desc">{{ loadError }}</div>
        <div class="row-actions">
          <button type="button" class="btn btn-primary" @click="load">重试</button>
          <RouterLink class="btn btn-ghost" to="/">回工作台</RouterLink>
        </div>
      </div>
    </div>

    <div v-else-if="!canOps" class="card">
      <div class="empty-state">
        <div class="empty-emoji">🔒</div>
        <div class="empty-title">仅系统管理员可配置权限</div>
        <div class="empty-desc">当前账号没有「运维 / 权限管理」能力，无法查看或修改等级矩阵。</div>
        <RouterLink to="/" class="btn btn-primary">回工作台</RouterLink>
      </div>
    </div>

    <template v-else-if="data">
      <!-- 能力矩阵 -->
      <section class="card">
        <div class="card-title">
          <span class="dot"></span>等级 → 能力矩阵
          <span class="spacer"></span>
          <span class="card-sub">共 {{ data.levels.length }} 个等级 × {{ data.capabilities.length }} 项能力</span>
        </div>

        <div class="perm-matrix-wrap">
          <table class="perm-matrix">
            <thead>
              <tr>
                <th>等级 \ 能力</th>
                <th v-for="cap in data.capabilities" :key="cap.value" :title="cap.description">
                  {{ cap.label }}
                  <div class="perm-caption">{{ cap.value }}</div>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="lv in data.levels" :key="lv.value">
                <td class="perm-row-head">
                  <div class="perm-level-name">{{ lv.label }}</div>
                  <div class="perm-level-desc">{{ lv.description }}</div>
                </td>
                <td v-for="cap in data.capabilities" :key="cap.value">
                  <input
                    class="perm-check"
                    type="checkbox"
                    :checked="hasCapInLevel(lv.value, cap.value)"
                    :title="`${lv.label} · ${cap.label}：${cap.description}`"
                    @change="toggleCap(lv.value, cap.value)"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p class="field-hint" style="margin-top: 10px">
          「本企业成员管理」由企业管理员身份自带，不在此矩阵中（不能按等级授予或撤销）。
          矩阵不允许把管理员等级的「运维 / 权限管理」取消——否则保存后将没有人能再改权限，后端会直接拒绝。
        </p>
      </section>

      <!-- 角色 → 默认等级 -->
      <section class="card" style="margin-top: 16px">
        <div class="card-title">
          <span class="dot"></span>角色 → 默认等级
          <span class="spacer"></span>
          <span class="card-sub">账号的等级 = 角色默认等级；人员级覆盖优先于它</span>
        </div>
        <div class="role-level-grid">
          <div v-for="role in data.roles" :key="role.value" class="role-level-item">
            <div>
              <div class="role-level-name">{{ role.label }}</div>
              <div class="role-level-hint">{{ role.value }}</div>
            </div>
            <select
              v-if="role.value !== 'guest'"
              v-model="roleLevels[role.value]"
              class="select"
            >
              <option v-for="lv in data.levels" :key="lv.value" :value="lv.value">{{ lv.label }}</option>
            </select>
            <span v-else class="badge">固定 L0（无权限）</span>
          </div>
        </div>
      </section>

      <!-- 人员授权（只读） -->
      <section class="card" style="margin-top: 16px">
        <div class="card-title">
          <span class="dot"></span>人员授权
          <span class="badge">{{ userLevels.length }} 条</span>
          <span class="spacer"></span>
          <span class="card-sub">本页只读：人员级覆盖 > 角色默认，编辑入口后续迭代</span>
        </div>
        <div v-if="userLevels.length" class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>用户名</th>
                <th>等级</th>
                <th>说明</th>
                <th>更新人</th>
                <th>更新时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in userLevels" :key="item.uid">
                <td><code>{{ item.uid }}</code></td>
                <td><span class="badge is-primary">{{ levelLabel(item.level) }}</span></td>
                <td>{{ item.note || "—" }}</td>
                <td>{{ item.updated_by || "—" }}</td>
                <td>{{ item.updated_at || "—" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-state" style="padding: 22px 10px">
          <div class="empty-desc">
            还没有人员级授权。所有账号当前按「角色 → 默认等级」取权限。
          </div>
        </div>
      </section>

      <!-- 配置元信息 -->
      <div class="alert is-info" style="margin-top: 16px">
        <div>
          配置版本 <b>{{ data.config?.version ?? "—" }}</b> ·
          最近更新 <b>{{ data.config?.updated_at || "从未修改（使用代码默认值）" }}</b>
          <span v-if="data.config?.updated_by"> · 更新人 {{ data.config.updated_by }}</span>
          <br />
          配置文件：<code>{{ data.path }}</code>
        </div>
      </div>
    </template>
  </div>
</template>
