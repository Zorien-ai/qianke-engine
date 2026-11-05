<script setup>
/**
 * 我的 AI（B 端账号级人设设置）：
 * GET /api/b/persona 读取；PATCH /api/b/persona 保存（只提交发生变化的字段语义上也兼容，
 * 这里统一提交 name / user_address / tone_profile 三个键，后端按「任意子集」处理）。
 *
 * 契约（后端实现）：
 *   GET  → { name, user_address, tone_profile, resolved, defaults, tones }
 *   PATCH body 任意子集 { name?, user_address?, tone_profile? }；
 *         校验失败返回 400 + detail；成功返回与 GET 相同的结构。
 *
 * 规则：名字 1–12 字；称呼可留空（= 用账号昵称，没有昵称则用「您」）；
 * 语气档位只影响表达方式，不改变权限、数据范围和可用工具。
 * 接口未就绪时用默认人设渲染页面；保存失败如实报错，不伪造保存成功。
 */
import { computed, onMounted, reactive, ref } from "vue";
import { getJson, patchJson } from "../api";
import { store, toast, toastError } from "../store";
import ConfirmButton from "../components/ConfirmButton.vue";

/* 后端 defaults / tones 未返回时的兜底：只用于渲染，不代表已保存状态 */
const FALLBACK_DEFAULTS = { name: "小千", user_address: "", tone_profile: "standard" };
const FALLBACK_TONES = [
  { value: "standard", label: "专业直给" },
  { value: "concise", label: "数据老手" },
  { value: "guided", label: "新手引导" },
];

const loading = ref(true);
const loadError = ref("");
const saving = ref(false);
const resetting = ref(false);
const saveError = ref("");
/** 最近一次 GET / PATCH 成功的接口响应；null = 本次还没成功读过接口 */
const persona = ref(null);

const form = reactive({
  name: FALLBACK_DEFAULTS.name,
  user_address: FALLBACK_DEFAULTS.user_address,
  tone_profile: FALLBACK_DEFAULTS.tone_profile,
});

const defaults = computed(() => (persona.value && persona.value.defaults) || FALLBACK_DEFAULTS);
const tones = computed(() => {
  const list = persona.value && persona.value.tones;
  return Array.isArray(list) && list.length ? list : FALLBACK_TONES;
});

const accountNickname = computed(() => (store.account && store.account.display_name) || "");
const trimmedName = computed(() => form.name.trim());
const trimmedAddress = computed(() => form.user_address.trim());
const nameLength = computed(() => Array.from(trimmedName.value).length);
const addressLength = computed(() => Array.from(trimmedAddress.value).length);
const nameInvalid = computed(() => nameLength.value < 1 || nameLength.value > 12);
const addressInvalid = computed(() => addressLength.value > 12);

const dirty = computed(() => {
  // 没成功读到接口时没有基线，直接允许保存（提交的是当前表单值）
  if (!persona.value) return true;
  const base = persona.value;
  return (
    String(base.name || "").trim() !== trimmedName.value ||
    String(base.user_address || "").trim() !== trimmedAddress.value ||
    String(base.tone_profile || "") !== String(form.tone_profile || "")
  );
});

const previewName = computed(() => trimmedName.value || defaults.value.name);
const previewAddress = computed(() => {
  if (trimmedAddress.value) return trimmedAddress.value;
  // 留空：已保存状态也是留空时，直接信任后端解析出的称呼；否则回落账号昵称 / 「您」
  const saved = persona.value;
  if (saved && !String(saved.user_address || "").trim()) {
    return (saved.resolved && saved.resolved.user_address) || "您";
  }
  return accountNickname.value || "您";
});

function toneLabel(value) {
  const item = tones.value.find((t) => t.value === value);
  return item ? item.label : value;
}

function hydrate(p) {
  persona.value = p;
  const name = String((p && p.name) || "").trim();
  form.name = name || FALLBACK_DEFAULTS.name;
  form.user_address = String((p && p.user_address) || "").trim();
  form.tone_profile = (p && p.tone_profile) || FALLBACK_DEFAULTS.tone_profile;
}

async function load() {
  loading.value = true;
  loadError.value = "";
  saveError.value = "";
  try {
    hydrate(await getJson("/api/b/persona"));
  } catch (e) {
    loadError.value = (e && (e.detail || e.message)) || "人设接口暂时不可用";
    persona.value = null;
    form.name = FALLBACK_DEFAULTS.name;
    form.user_address = FALLBACK_DEFAULTS.user_address;
    form.tone_profile = FALLBACK_DEFAULTS.tone_profile;
    toastError(e);
  } finally {
    loading.value = false;
  }
}

function validate() {
  if (nameInvalid.value) {
    toast("AI 名字需要 1–12 个字，请修改后再保存", "warn", 4600);
    return false;
  }
  if (addressInvalid.value) {
    toast("称呼最多 12 个字；留空则用账号昵称", "warn", 4600);
    return false;
  }
  return true;
}

async function save() {
  if (saving.value || resetting.value || !validate()) return;
  saving.value = true;
  saveError.value = "";
  try {
    const data = await patchJson("/api/b/persona", {
      name: trimmedName.value,
      user_address: trimmedAddress.value,
      tone_profile: form.tone_profile,
    });
    hydrate(data);
    loadError.value = "";
    toast("已保存，之后的回答会用新的名字、称呼与语气", "success", 4200);
  } catch (e) {
    saveError.value = (e && (e.detail || e.message)) || "保存失败";
    toastError(e);
  } finally {
    saving.value = false;
  }
}

async function resetDefaults() {
  if (saving.value || resetting.value) return;
  resetting.value = true;
  saveError.value = "";
  const d = defaults.value;
  try {
    const data = await patchJson("/api/b/persona", {
      name: d.name,
      user_address: d.user_address,
      tone_profile: d.tone_profile,
    });
    hydrate(data);
    loadError.value = "";
    toast("已恢复默认人设", "success");
  } catch (e) {
    saveError.value = (e && (e.detail || e.message)) || "重置失败";
    toastError(e);
  } finally {
    resetting.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="page">
    <div class="kb-hero">
      <div>
        <div class="kb-title-line">
          <h2 style="font-size: 20px">我的 AI</h2>
          <span class="badge is-primary">账号级人设</span>
          <span v-if="persona && dirty" class="badge">有未保存修改</span>
          <span v-else-if="persona" class="badge is-success">与已保存人设一致</span>
        </div>
        <p class="card-sub" style="margin-top: 6px">
          在这里设置 AI 的名字、对您的称呼和语气档位。人设按账号保存，只影响称呼与表达方式，
          不改变您的权限、数据范围和可用工具。
        </p>
      </div>
      <div class="row-actions">
        <button type="button" class="btn btn-ghost" :disabled="loading || saving || resetting" @click="load">重新加载</button>
        <ConfirmButton
          label="重置默认"
          confirm-text="确认重置为默认人设？"
          kind="ghost"
          :busy="resetting"
          :disabled="loading || saving"
          @confirm="resetDefaults"
        />
        <button
          type="button"
          class="btn btn-primary"
          :disabled="loading || saving || resetting || !dirty || nameInvalid || addressInvalid"
          @click="save"
        >
          <span v-if="saving" class="spinner spinner-sm" />
          {{ saving ? "保存中…" : "保存" }}
        </button>
      </div>
    </div>

    <div v-if="loadError" class="alert is-warn" style="margin-bottom: 16px">
      <div>
        人设接口暂时不可用：{{ loadError }}。页面当前显示默认人设，保存会直接提交到接口，接口可用后立即生效。
        <div class="row-actions" style="margin-top: 10px">
          <button type="button" class="btn btn-sm btn-ghost" @click="load">重试</button>
        </div>
      </div>
    </div>

    <section v-if="loading" class="card">
      <div class="skeleton" style="height: 20px; width: 28%"></div>
      <div class="skeleton" style="height: 150px; margin-top: 16px"></div>
    </section>

    <template v-else>
      <section class="card">
        <div class="card-title"><span class="dot"></span>人设设置</div>

        <div class="persona-form">
          <div class="field">
            <label class="field-label" for="persona-name">AI 名字</label>
            <input
              id="persona-name"
              v-model="form.name"
              class="input"
              type="text"
              maxlength="12"
              placeholder="默认小千"
              :disabled="saving || resetting"
            />
            <span class="field-hint">1–12 个字（中文、英文、数字和下划线），默认「{{ defaults.name }}」。</span>
          </div>

          <div class="field">
            <label class="field-label" for="persona-address">怎么称呼您</label>
            <input
              id="persona-address"
              v-model="form.user_address"
              class="input"
              type="text"
              maxlength="12"
              placeholder="留空则用账号昵称"
              :disabled="saving || resetting"
            />
            <span class="field-hint">可用中文、英文、数字和下划线；留空时用账号昵称称呼您，没有昵称时用「您」。</span>
          </div>

          <div class="field">
            <span class="field-label">语气档位</span>
            <div class="tone-options">
              <button
                v-for="item in tones"
                :key="item.value"
                type="button"
                class="tone-option"
                :class="{ 'is-active': form.tone_profile === item.value }"
                :disabled="saving || resetting"
                @click="form.tone_profile = item.value"
              >
                {{ item.label }}
              </button>
            </div>
            <span class="field-hint">当前档位：{{ toneLabel(form.tone_profile) }}。档位只影响语气，不影响权限与数据范围。</span>
          </div>
        </div>

        <div v-if="saveError" class="alert is-error" style="margin-top: 16px">{{ saveError }}</div>

        <div class="persona-preview">
          <span class="preview-kicker">PREVIEW</span>
          <p>{{ previewName }} 会称呼您为 {{ previewAddress }}</p>
        </div>
      </section>

      <section class="card" style="margin-top: 16px">
        <div class="card-title"><span class="dot"></span>说明</div>
        <ul class="persona-tips">
          <li>人设按登录账号保存，不影响同企业的其他成员。</li>
          <li>名字与语气用于 B 端对话和 Agent 的回答；称呼用于回答里对您的称谓。</li>
          <li>人设只改变称呼与语气，权限、数据范围与可用工具仍由账号角色决定。</li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.persona-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px 18px;
}
.persona-form .field:last-child {
  grid-column: 1 / -1;
}

.tone-options { display: flex; gap: 8px; flex-wrap: wrap; }
.tone-option {
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.16s ease;
}
.tone-option:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-soft);
}
.tone-option.is-active {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-soft);
}
.tone-option:disabled { opacity: 0.55; cursor: not-allowed; }

.persona-preview {
  margin-top: 18px;
  padding: 14px 16px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}
.preview-kicker {
  font-family: var(--mono);
  font-size: 9.5px;
  letter-spacing: 0.14em;
  color: var(--primary);
  font-weight: 700;
}
.persona-preview p { margin-top: 6px; font-size: 15px; font-weight: 650; }

.persona-tips {
  margin: 0;
  padding-left: 18px;
  color: var(--text-2);
  font-size: 12.5px;
  line-height: 1.9;
}

@media (max-width: 760px) {
  .persona-form { grid-template-columns: 1fr; }
}
</style>
