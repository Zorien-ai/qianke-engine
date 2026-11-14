<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { getJson, patchJson, postJson } from "../api";
import { toast } from "../store";

const router = useRouter();
const loading = ref(true);
const error = ref("");
const empty = ref(false);
const account = ref(null);
const companion = ref(null);
const avatarBroken = ref(false);
const avatarVersion = ref(Date.now());
const editing = ref(false);
const nicknameDraft = ref("");
const saving = ref(false);
const cardView = ref(false);
const loggingOut = ref(false);

const SETTINGS_KEY = "qianke:c:preferences";
const DEFAULT_PREFERENCES = {
  messages: true,
  proactive: true,
  offers: false,
  online: true,
  readReceipt: true,
};

function loadPreferences() {
  try {
    const parsed = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    return { ...DEFAULT_PREFERENCES, ...(parsed && typeof parsed === "object" ? parsed : {}) };
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

const preferences = ref(loadPreferences());

const displayName = computed(() => {
  const nickname = String(companion.value?.user_nickname || "").trim();
  const accountName = String(account.value?.display_name || "").trim();
  return nickname || accountName || String(account.value?.username || "").trim() || "千客用户";
});

const username = computed(() => String(account.value?.username || "").trim());
const accountType = computed(() => String(account.value?.account_type_label || "消费者").trim() || "消费者");
const accountStatus = computed(() => String(account.value?.status_label || "正常").trim() || "正常");
const initial = computed(() => displayName.value.slice(0, 1).toUpperCase());
const avatarSrc = computed(() => {
  if (avatarBroken.value || !companion.value?.user_avatar_url) return "";
  return `/api/c/companion/avatar/user?ts=${avatarVersion.value}`;
});

async function loadProfile() {
  loading.value = true;
  error.value = "";
  try {
    const [identity, pet] = await Promise.all([
      getJson("/whoami"),
      getJson("/api/c/companion").catch(() => null),
    ]);
    account.value = identity?.account || null;
    companion.value = pet || null;
    nicknameDraft.value = String(companion.value?.user_nickname || account.value?.display_name || "");
    empty.value = !account.value;
  } catch (err) {
    error.value = err?.detail || err?.message || "个人资料加载失败，请稍后重试";
  } finally {
    loading.value = false;
  }
}

function startEdit() {
  nicknameDraft.value = displayName.value;
  editing.value = true;
}

async function saveNickname() {
  const nickname = nicknameDraft.value.trim();
  if (!nickname) {
    toast("昵称不能为空", "error");
    return;
  }
  if (nickname.length > 12) {
    toast("昵称最多 12 个字", "error");
    return;
  }
  saving.value = true;
  try {
    const data = await patchJson("/api/c/companion", { user_nickname: nickname });
    companion.value = { ...(companion.value || {}), ...(data || {}), user_nickname: nickname };
    editing.value = false;
    toast("昵称已更新", "success");
  } catch (err) {
    toast(err?.detail || err?.message || "保存失败，请稍后重试", "error");
  } finally {
    saving.value = false;
  }
}

function persistPreferences() {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(preferences.value));
  } catch {
    // 本机存储不可用时仍保留当前会话状态
  }
}

function togglePreference(key, label) {
  preferences.value = { ...preferences.value, [key]: !preferences.value[key] };
  persistPreferences();
  toast(`${label}已${preferences.value[key] ? "开启" : "关闭"}`, "success");
}

function resetPreferences() {
  preferences.value = { ...DEFAULT_PREFERENCES };
  persistPreferences();
  toast("本机偏好已恢复默认", "success");
}

function openCard() {
  cardView.value = true;
}

function closeCard() {
  cardView.value = false;
}

async function logout() {
  if (loggingOut.value) return;
  if (!window.confirm("退出当前账号？")) return;
  loggingOut.value = true;
  try {
    await postJson("/auth/logout", {});
    await router.push("/home");
  } catch (err) {
    toast(err?.detail || err?.message || "退出失败，请稍后再试", "error");
  } finally {
    loggingOut.value = false;
  }
}

onMounted(loadProfile);
</script>

<template>
  <div class="c-me">
    <section v-if="loading" class="c-me-loading" aria-label="资料加载中">
      <div class="c-me-skeleton is-hero"></div>
      <div class="c-me-skeleton"></div>
      <div class="c-me-skeleton"></div>
    </section>

    <section v-else-if="error" class="c-me-error" role="alert">
      <strong>个人资料暂时不可用</strong>
      <p>{{ error }}</p>
      <button type="button" @click="loadProfile">重新加载</button>
    </section>

    <section v-else-if="empty" class="c-me-empty" role="status">
      <strong>暂无账号资料</strong>
      <p>当前账号没有可展示的消费者资料，请刷新或重新登录后再试。</p>
      <div class="c-me-empty-actions">
        <button type="button" @click="loadProfile">刷新资料</button>
        <a href="/c/login">重新登录</a>
      </div>
    </section>

    <template v-else>
      <section class="c-me-hero">
        <div class="c-me-avatar" :class="{ 'is-image': avatarSrc && !avatarBroken }">
          <img
            v-if="avatarSrc && !avatarBroken"
            :src="avatarSrc"
            :alt="displayName"
            @error="avatarBroken = true"
          />
          <span v-else>{{ initial }}</span>
        </div>
        <div class="c-me-identity">
          <p class="c-me-kicker">MY PROFILE</p>
          <h2>{{ displayName }}</h2>
          <p class="c-me-handle">@{{ username || "qianke" }}</p>
          <div class="c-me-badges">
            <span>{{ accountType }}</span>
            <span>{{ accountStatus }}</span>
          </div>
        </div>
        <button type="button" class="c-me-card-btn" @click="openCard">查看名片主页</button>
      </section>

      <section class="c-me-section" aria-labelledby="c-me-account-title">
        <header class="c-me-section-head">
          <div>
            <p class="c-me-kicker">ACCOUNT</p>
            <h3 id="c-me-account-title">账号资料</h3>
          </div>
        </header>

        <div v-if="editing" class="c-me-edit">
          <label for="c-me-nickname">昵称</label>
          <input
            id="c-me-nickname"
            v-model="nicknameDraft"
            maxlength="12"
            autocomplete="nickname"
            @keyup.enter="saveNickname"
          />
          <div class="c-me-edit-actions">
            <button type="button" class="c-me-btn" @click="editing = false" :disabled="saving">取消</button>
            <button type="button" class="c-me-btn is-primary" @click="saveNickname" :disabled="saving">
              {{ saving ? "保存中…" : "保存" }}
            </button>
          </div>
        </div>

        <div class="c-me-list">
          <div class="c-me-row">
            <span><b>昵称</b><small>仅用于 C 端展示</small></span>
            <button type="button" class="c-me-text-action" @click="startEdit">编辑</button>
          </div>
          <div class="c-me-row">
            <span><b>登录账号</b><small>账号 ID</small></span>
            <em>{{ username || "—" }}</em>
          </div>
          <div class="c-me-row">
            <span><b>账号类型</b><small>当前身份</small></span>
            <em>{{ accountType }}</em>
          </div>
          <a class="c-me-row" href="/password">
            <span><b>修改密码</b><small>账号安全</small></span>
            <span class="c-me-chevron">›</span>
          </a>
        </div>
      </section>

      <section class="c-me-section" aria-labelledby="c-me-notify-title">
        <header class="c-me-section-head">
          <div>
            <p class="c-me-kicker">NOTIFICATIONS</p>
            <h3 id="c-me-notify-title">通知偏好</h3>
          </div>
        </header>
        <div class="c-me-list">
          <button type="button" class="c-me-row" @click="togglePreference('messages', '新消息提醒')">
            <span><b>新消息提醒</b><small>店宠与好友消息</small></span>
            <span class="c-me-switch" :class="{ 'is-on': preferences.messages }" role="switch" :aria-checked="preferences.messages"></span>
          </button>
          <button type="button" class="c-me-row" @click="togglePreference('proactive', '伙伴主动关心')">
            <span><b>伙伴主动关心</b><small>允许小鱼偶尔主动问候</small></span>
            <span class="c-me-switch" :class="{ 'is-on': preferences.proactive }" role="switch" :aria-checked="preferences.proactive"></span>
          </button>
          <button type="button" class="c-me-row" @click="togglePreference('offers', '活动与优惠')">
            <span><b>活动与优惠</b><small>商家活动和优惠信息</small></span>
            <span class="c-me-switch" :class="{ 'is-on': preferences.offers }" role="switch" :aria-checked="preferences.offers"></span>
          </button>
        </div>
        <p class="c-me-note">通知偏好目前保存在本机；推送服务接入后会同步到账号。</p>
      </section>

      <section class="c-me-section" aria-labelledby="c-me-privacy-title">
        <header class="c-me-section-head">
          <div>
            <p class="c-me-kicker">PRIVACY</p>
            <h3 id="c-me-privacy-title">隐私与通用</h3>
          </div>
        </header>
        <div class="c-me-list">
          <button type="button" class="c-me-row" @click="togglePreference('online', '在线状态')">
            <span><b>展示在线状态</b><small>让好友知道你在线</small></span>
            <span class="c-me-switch" :class="{ 'is-on': preferences.online }" role="switch" :aria-checked="preferences.online"></span>
          </button>
          <button type="button" class="c-me-row" @click="togglePreference('readReceipt', '已读回执')">
            <span><b>发送已读回执</b><small>对方可以看到你已读</small></span>
            <span class="c-me-switch" :class="{ 'is-on': preferences.readReceipt }" role="switch" :aria-checked="preferences.readReceipt"></span>
          </button>
          <button type="button" class="c-me-row" @click="resetPreferences">
            <span><b>恢复本机默认偏好</b><small>不会影响账号资料</small></span>
            <span class="c-me-chevron">›</span>
          </button>
        </div>
      </section>

      <section class="c-me-section c-me-general">
        <header class="c-me-section-head">
          <div>
            <p class="c-me-kicker">GENERAL</p>
            <h3>通用</h3>
          </div>
        </header>
        <div class="c-me-list">
          <a class="c-me-row" href="/docs" target="_blank" rel="noopener">
            <span><b>产品说明</b><small>了解千客 C 端</small></span>
            <span class="c-me-chevron">↗</span>
          </a>
          <button type="button" class="c-me-row c-me-danger" @click="logout" :disabled="loggingOut">
            <span><b>{{ loggingOut ? "退出中…" : "退出登录" }}</b><small>退出当前消费者账号</small></span>
            <span class="c-me-chevron">›</span>
          </button>
        </div>
      </section>
    </template>

    <div v-if="cardView" class="c-me-card-mask" @click.self="closeCard">
      <section class="c-me-card-page" role="dialog" aria-modal="true" aria-label="个人名片主页">
        <button type="button" class="c-me-card-close" aria-label="关闭名片" @click="closeCard">×</button>
        <p class="c-me-kicker">PERSONAL CARD</p>
        <div class="c-me-card-avatar" :class="{ 'is-image': avatarSrc && !avatarBroken }">
          <img v-if="avatarSrc && !avatarBroken" :src="avatarSrc" :alt="displayName" @error="avatarBroken = true" />
          <span v-else>{{ initial }}</span>
        </div>
        <h2>{{ displayName }}</h2>
        <p class="c-me-handle">@{{ username || "qianke" }}</p>
        <div class="c-me-card-tags">
          <span>{{ accountType }}</span>
          <span>千客 C 端</span>
        </div>
        <dl class="c-me-card-meta">
          <div><dt>账号状态</dt><dd>{{ accountStatus }}</dd></div>
          <div><dt>登录账号</dt><dd>{{ username || "—" }}</dd></div>
        </dl>
        <p class="c-me-card-note">这是你的个人名片，仅在当前账号内展示。</p>
        <button type="button" class="c-me-btn is-primary c-me-card-back" @click="closeCard">返回个人中心</button>
      </section>
    </div>
  </div>
</template>

<style scoped>
.c-me {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px 0 calc(20px + env(safe-area-inset-bottom));
}

.c-me-kicker {
  margin: 0 0 5px;
  color: var(--primary);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.16em;
}

.c-me-hero {
  position: relative;
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  padding: 20px 16px 16px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: var(--surface);
}

.c-me-avatar,
.c-me-card-avatar {
  display: grid;
  width: 64px;
  height: 64px;
  place-items: center;
  overflow: hidden;
  border-radius: 50%;
  background: var(--primary-soft);
  color: var(--primary-strong);
  font-size: 26px;
  font-weight: 700;
}

.c-me-avatar img,
.c-me-card-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.c-me-identity {
  min-width: 0;
}

.c-me-identity h2 {
  margin: 0;
  overflow: hidden;
  color: var(--text);
  font-size: 23px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-me-handle {
  margin: 3px 0 8px;
  overflow: hidden;
  color: var(--text-3);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-me-badges,
.c-me-card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.c-me-badges span,
.c-me-card-tags span {
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 10px;
}

.c-me-card-btn {
  grid-column: 1 / -1;
  min-height: 38px;
  margin-top: 4px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.c-me-section {
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
}

.c-me-section-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.c-me-section h3 {
  margin: 0;
  color: var(--text);
  font-size: 19px;
}

.c-me-list {
  display: flex;
  flex-direction: column;
}

.c-me-row {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 52px;
  padding: 9px 0;
  border: 0;
  border-bottom: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  font: inherit;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}

.c-me-row:last-child {
  border-bottom: 0;
}

.c-me-row b,
.c-me-row small {
  display: block;
}

.c-me-row b {
  font-size: 14px;
  font-weight: 600;
}

.c-me-row small {
  margin-top: 2px;
  color: var(--text-3);
  font-size: 11px;
}

.c-me-row em {
  flex: none;
  max-width: 45%;
  overflow: hidden;
  color: var(--text-2);
  font-size: 12px;
  font-style: normal;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-me-chevron {
  flex: none;
  color: var(--text-3);
  font-size: 20px;
}

.c-me-text-action {
  flex: none;
  border: 0;
  background: transparent;
  color: var(--primary);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.c-me-switch {
  position: relative;
  width: 42px;
  height: 24px;
  flex: 0 0 42px;
  border-radius: 999px;
  background: var(--border);
  transition: background 0.18s ease;
}

.c-me-switch::after {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(30, 27, 22, 0.2);
  content: "";
  transition: transform 0.18s ease;
}

.c-me-switch.is-on {
  background: var(--primary);
}

.c-me-switch.is-on::after {
  transform: translateX(18px);
}

.c-me-note {
  margin: 9px 0 0;
  color: var(--text-3);
  font-size: 11px;
  line-height: 1.6;
}

.c-me-edit {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-bottom: 8px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-2);
}

.c-me-edit label {
  color: var(--text-3);
  font-size: 11px;
}

.c-me-edit input {
  width: 100%;
  height: 38px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 16px;
}

.c-me-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 7px;
}

.c-me-btn {
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.c-me-btn.is-primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.c-me-danger b {
  color: var(--primary-strong);
}

.c-me-loading {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.c-me-skeleton {
  height: 120px;
  border-radius: 16px;
  background: var(--surface-2);
  animation: c-me-shimmer 1.2s ease-in-out infinite;
}

.c-me-skeleton.is-hero {
  height: 164px;
}

@keyframes c-me-shimmer {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

.c-me-error {
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
  color: var(--text-2);
}

.c-me-error strong {
  color: var(--text);
}

.c-me-error p {
  margin: 8px 0 12px;
  font-size: 13px;
}

.c-me-empty {
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
  color: var(--text-2);
}

.c-me-empty strong {
  color: var(--text);
}

.c-me-empty p {
  margin: 8px 0 12px;
  font-size: 13px;
}

.c-me-empty-actions {
  display: flex;
  gap: 8px;
}

.c-me-empty button,
.c-me-empty a {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  padding: 0 14px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text);
  font: inherit;
  font-size: 12px;
  text-decoration: none;
}

.c-me-error button {
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text);
  font: inherit;
}

.c-me-card-mask {
  position: fixed;
  z-index: 80;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(30, 27, 22, 0.48);
}

.c-me-card-page {
  position: relative;
  width: min(420px, 100%);
  padding: 28px 22px 22px;
  border-radius: 22px;
  background: var(--surface);
  text-align: center;
  box-shadow: 0 24px 64px rgba(30, 27, 22, 0.24);
}

.c-me-card-close {
  position: absolute;
  top: 10px;
  right: 12px;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 20px;
  cursor: pointer;
}

.c-me-card-page .c-me-kicker {
  margin-bottom: 18px;
}

.c-me-card-avatar {
  width: 92px;
  height: 92px;
  margin: 0 auto 12px;
  font-size: 36px;
}

.c-me-card-page h2 {
  margin: 0;
  color: var(--text);
  font-size: 27px;
}

.c-me-card-tags {
  justify-content: center;
  margin-top: 10px;
}

.c-me-card-meta {
  margin: 20px 0 0;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  padding: 10px 0;
  text-align: left;
}

.c-me-card-meta div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 5px 0;
}

.c-me-card-meta dt {
  color: var(--text-3);
  font-size: 12px;
}

.c-me-card-meta dd {
  margin: 0;
  color: var(--text-2);
  font-size: 12px;
}

.c-me-card-note {
  margin: 13px 0 16px;
  color: var(--text-3);
  font-size: 11px;
}

.c-me-card-back {
  width: 100%;
}
</style>
