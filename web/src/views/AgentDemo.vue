<script setup>
import { computed, ref } from "vue";
import { postJson } from "../api";

const DEFAULT_QUERY = "帮我给上海的黑卡流失用户写一段美妆产品的召回短信";

const query = ref(DEFAULT_QUERY);
const running = ref(false);
const result = ref(null);
const error = ref("");
const copied = ref(false);

const pendingSteps = [
  { agent: "supervisor", label: "主管", message: "正在判断任务分派…", status: "running" },
  { agent: "analyst", label: "数据分析师", message: "准备查询用户画像", status: "pending" },
  { agent: "copywriter", label: "文案专家", message: "准备调取运营 SOP", status: "pending" },
  { agent: "finalizer", label: "主管汇总", message: "等待最终结果", status: "pending" },
];

const displaySteps = computed(() => (result.value?.steps?.length ? result.value.steps : pendingSteps));
const userCards = computed(() => result.value?.user_cards || []);
const sopSources = computed(() => result.value?.sop?.sources || []);
const finalReply = computed(() => result.value?.final_reply || "");
const isGated = computed(() => finalReply.value.includes("未找到匹配用户"));

const pendingActions = computed(() => result.value?.pending_actions || []);
const actionBusy = ref("");

async function confirmAction(actionId) {
  if (!actionId || actionBusy.value) return;
  actionBusy.value = actionId;
  try {
    const updated = await postJson(`/api/agent/actions/${encodeURIComponent(actionId)}/confirm`, {});
    const current = result.value?.pending_actions?.find((item) => item.action_id === actionId);
    if (current) Object.assign(current, updated);
  } catch (e) {
    error.value = e?.detail?.message || e?.detail || e?.message || "任务确认失败";
  } finally {
    actionBusy.value = "";
  }
}

const STEP_ICON = {
  supervisor: "🧭",
  analyst: "🔍",
  copywriter: "✍️",
  finalizer: "✅",
};

function stepIcon(step) {
  return STEP_ICON[step.agent] || "•";
}

function stepClass(step) {
  if (step.agent === "finalizer") return "is-final";
  if (step.status === "error") return "is-error";
  if (step.status === "done") return "is-done";
  if (step.status === "running") return "is-running";
  return "is-pending";
}

function money(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

async function runAgent() {
  const text = query.value.trim();
  if (!text || running.value) return;
  running.value = true;
  error.value = "";
  copied.value = false;
  result.value = null;
  try {
    result.value = await postJson("/api/agent/run", { query: text });
  } catch (e) {
    error.value = e?.detail || e?.message || "Agent 运行失败";
  } finally {
    running.value = false;
  }
}

async function copyReply() {
  const text = finalReply.value;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    copied.value = true;
  } catch {
    // 非安全上下文 / 浏览器拒绝 Clipboard API 时退回 execCommand
    try {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
      copied.value = true;
    } catch {
      copied.value = false;
    }
  }
  if (copied.value) window.setTimeout(() => (copied.value = false), 1800);
}
</script>

<template>
  <div class="agent-page">
    <header class="agent-hero">
      <div class="hero-kicker">LANGGRAPH · MULTI-AGENT</div>
      <h2>Agent 智能助理</h2>
      <p>
        主管理解需求，数据分析师查真实用户，文案专家读取运营 SOP，
        最后生成千人千面的召回短信。
      </p>
      <div class="hero-tags">
        <span>Supervisor</span>
        <span>Analyst</span>
        <span>Copywriter</span>
      </div>
    </header>

    <section class="query-card">
      <div class="query-label">
        <span class="dot" />
        给智能体一个运营任务
      </div>
      <textarea
        v-model="query"
        rows="3"
        :disabled="running"
        placeholder="例如：帮我给上海的黑卡流失用户写一段美妆产品的召回短信"
        @keydown.ctrl.enter="runAgent"
        @keydown.meta.enter="runAgent"
      />
      <div class="query-actions">
        <span class="hint">Ctrl / ⌘ + Enter 发送</span>
        <button class="run-btn" type="button" :disabled="running || !query.trim()" @click="runAgent">
          <span v-if="running" class="spinner" />
          <span>{{ running ? "多智能体协作中…" : "启动多智能体" }}</span>
        </button>
      </div>
    </section>

    <p v-if="error" class="error-line">
      <span>⚠</span>
      {{ error }}
    </p>

    <section v-if="running || result" class="flow-card">
      <div class="section-head">
        <h3>节点流转</h3>
        <span class="section-meta">{{ running ? "运行中" : "已完成" }}</span>
      </div>
      <div class="flow-list">
        <div v-for="(step, i) in displaySteps" :key="`${step.agent}-${i}`" class="flow-step" :class="stepClass(step)">
          <div class="flow-rail">
            <span class="flow-icon">{{ stepIcon(step) }}</span>
            <span v-if="i < displaySteps.length - 1" class="flow-line" />
          </div>
          <div class="flow-body">
            <div class="flow-title">
              <strong>{{ step.label }}</strong>
              <span v-if="step.status === 'running'" class="pulse">处理中</span>
              <span v-else-if="step.status === 'error'" class="bad">需关注</span>
            </div>
            <p>{{ step.message }}</p>
          </div>
        </div>
      </div>
    </section>

    <section v-if="result && pendingActions.length" class="action-card" aria-label="待确认写入">
      <div class="section-head">
        <h3>待确认写入</h3>
        <span class="section-meta">Agent 只生成草稿，确认后才落正式任务</span>
      </div>
      <article v-for="action in pendingActions" :key="action.action_id" class="action-row">
        <div class="action-copy">
          <strong>{{ action.title }}</strong>
          <p>{{ action.description || "运营跟进任务" }}</p>
          <span class="action-meta">
            {{ action.owner || "未指定负责人" }} ·
            {{ action.priority }} ·
            {{ action.due_date || "未设截止日期" }}
          </span>
        </div>
        <div class="action-side">
          <span class="action-status" :class="action.status.toLowerCase()">{{ action.status }}</span>
          <button
            v-if="action.status === 'DRAFT'"
            type="button"
            class="action-confirm"
            :disabled="actionBusy === action.action_id"
            @click="confirmAction(action.action_id)"
          >
            {{ actionBusy === action.action_id ? "确认中…" : "确认写入" }}
          </button>
        </div>
      </article>
    </section>

    <section v-if="result" class="result-grid">
      <div class="panel user-panel">
        <div class="panel-head">
          <h3>{{ isGated ? "候选用户（未命中）" : "查到的用户" }}</h3>
          <span>{{ userCards.length }} 位</span>
        </div>
        <div v-if="userCards.length" class="user-list">
          <article v-for="card in userCards" :key="card.user_id" class="user-card">
            <div class="user-top">
              <div class="user-avatar">{{ (card.user_id || "?").slice(0, 1) }}</div>
              <div>
                <h4>{{ card.user_id }}</h4>
                <p>{{ card.city || "城市未知" }} · {{ card.member_level || "等级未知" }}</p>
              </div>
              <span class="user-chip">{{ card.top_category || "品类未知" }}</span>
            </div>
            <dl class="user-stats">
              <div><dt>客单价</dt><dd>¥{{ money(card.avg_amount) }}</dd></div>
              <div><dt>累计消费</dt><dd>¥{{ money(card.total_amount) }}</dd></div>
              <div><dt>订单</dt><dd>{{ card.order_count ?? "—" }} 笔</dd></div>
              <div><dt>最近购买</dt><dd>{{ card.days_since_last_buy ?? "—" }} 天前</dd></div>
            </dl>
          </article>
        </div>
        <p v-else class="empty-line">本次没有返回结构化用户卡片。</p>

        <div v-if="sopSources.length" class="sop-block">
          <div class="sop-head">
            <span>📖</span>
            运营规则依据
            <small>{{ sopSources.length }} 条</small>
          </div>
          <ul>
            <li v-for="(src, i) in sopSources.slice(0, 3)" :key="i">
              <span>{{ src.source }}</span>
              {{ (src.text || "").slice(0, 110) }}…
            </li>
          </ul>
        </div>
      </div>

      <div class="panel copy-panel">
        <div class="panel-head">
          <h3>专属召回短信</h3>
          <button v-if="!isGated" class="copy-btn" type="button" :disabled="!finalReply" @click="copyReply">
            {{ copied ? "已复制 ✓" : "一键复制" }}
          </button>
          <span v-else class="gated-tag">未生成文案</span>
        </div>
        <div class="sms-preview">
          <span class="sms-label">SMS · 100 字以内</span>
          <p>{{ finalReply || "没有生成文案" }}</p>
          <span class="sms-count">{{ finalReply.length }} 字</span>
        </div>
        <div class="copy-note">
          <span>🧬 千人千面</span>
          结合用户偏好与 SOP 权益生成，未通过模板套用。
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.agent-page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 8px 0 40px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.agent-hero {
  padding: 26px 28px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background:
    radial-gradient(520px 180px at 95% 0%, var(--primary-soft), transparent 70%),
    var(--surface);
  box-shadow: var(--shadow-sm);
}
.hero-kicker {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.16em;
  color: var(--primary);
  font-weight: 700;
}
.agent-hero h2 { margin: 7px 0 7px; font-size: 30px; }
.agent-hero p { color: var(--text-2); max-width: 760px; }
.hero-tags { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
.hero-tags span {
  padding: 4px 9px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--muted);
  background: var(--surface-2);
  font-family: var(--mono);
  font-size: 10px;
}

.query-card,
.flow-card,
.panel {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
.query-card { padding: 18px; }
.query-label {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; font-weight: 650; margin-bottom: 11px;
}
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--primary); box-shadow: 0 0 0 4px var(--primary-soft); }
textarea {
  width: 100%; resize: vertical; min-height: 84px;
  border: 1px solid var(--border); border-radius: 14px;
  background: var(--surface-2); color: var(--text);
  padding: 13px 14px; font: inherit; line-height: 1.65;
  outline: none; transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
textarea:focus { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
textarea:disabled { opacity: 0.65; }
.query-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 12px; }
.hint { color: var(--muted); font-size: 11px; }
.run-btn,
.copy-btn {
  border: 0; cursor: pointer; font-weight: 650;
  border-radius: 11px; transition: transform 0.15s ease, opacity 0.15s ease;
}
.run-btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 17px; color: #fff;
  background: var(--grad); box-shadow: 0 8px 22px var(--primary-soft);
}
.run-btn:hover:not(:disabled) { transform: translateY(-1px); }
.run-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.spinner {
  width: 13px; height: 13px; border-radius: 50%;
  border: 2px solid rgba(255,255,255,0.35); border-top-color: #fff;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.error-line {
  display: flex; gap: 8px; padding: 11px 14px;
  color: var(--danger); background: var(--danger-soft);
  border: 1px solid color-mix(in srgb, var(--danger) 24%, transparent);
  border-radius: 12px;
}

.section-head,
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.flow-card { padding: 18px 20px; }
.flow-card h3, .panel h3 { font-size: 15px; }
.section-meta { color: var(--muted); font-size: 11px; font-family: var(--mono); }
.flow-list { margin-top: 16px; display: flex; flex-direction: column; gap: 0; }
.flow-step { display: grid; grid-template-columns: 32px 1fr; gap: 12px; }
.flow-rail { display: flex; flex-direction: column; align-items: center; }
.flow-icon {
  width: 28px; height: 28px; display: grid; place-items: center;
  border: 1px solid var(--border); border-radius: 50%;
  background: var(--surface-2); font-size: 13px; z-index: 1;
}
.flow-line { width: 1px; flex: 1; background: var(--border); min-height: 24px; }
.flow-body { padding: 3px 0 17px; }
.flow-title { display: flex; align-items: center; gap: 9px; }
.flow-title strong { font-size: 13px; }
.flow-body p { color: var(--text-2); font-size: 12px; margin-top: 4px; }
.pulse, .bad {
  font-size: 10px; padding: 1px 7px; border-radius: 999px;
}
.pulse { color: var(--primary); background: var(--primary-soft); animation: blink 1.3s ease-in-out infinite; }
.bad { color: var(--danger); background: var(--danger-soft); }
@keyframes blink { 50% { opacity: 0.45; } }
.flow-step.is-done .flow-icon { color: var(--success); background: var(--success-soft); border-color: color-mix(in srgb, var(--success) 30%, transparent); }
.flow-step.is-running .flow-icon { color: var(--primary); background: var(--primary-soft); border-color: color-mix(in srgb, var(--primary) 35%, transparent); }
.flow-step.is-error .flow-icon { color: var(--danger); background: var(--danger-soft); }
.flow-step.is-final .flow-icon { color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); }

.action-card {
  margin-top: 18px;
  padding: 18px 20px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}
.action-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.action-copy strong { font-size: 13px; }
.action-copy p { margin-top: 4px; color: var(--text-2); font-size: 12px; }
.action-meta { display: block; margin-top: 6px; color: var(--muted); font-size: 10px; }
.action-side { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.action-status {
  padding: 3px 7px;
  border-radius: 999px;
  color: var(--warn);
  background: var(--warn-soft);
  font-family: var(--mono);
  font-size: 9px;
}
.action-status.confirmed { color: var(--success); background: var(--success-soft); }
.action-confirm {
  padding: 6px 10px;
  border: 1px solid var(--primary);
  border-radius: var(--radius-xs);
  background: var(--primary);
  color: #fff;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}
.action-confirm:disabled { opacity: 0.6; cursor: not-allowed; }

.result-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.85fr); gap: 18px; align-items: start; }
.panel { padding: 18px 20px; }
.panel-head > span { color: var(--muted); font-family: var(--mono); font-size: 11px; }
.user-list { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; }
.user-card {
  padding: 13px; border: 1px solid var(--border);
  border-radius: 13px; background: var(--surface-2);
}
.user-top { display: flex; align-items: center; gap: 10px; }
.user-avatar {
  width: 34px; height: 34px; flex: 0 0 auto; display: grid; place-items: center;
  border-radius: 10px; background: var(--primary-soft); color: var(--primary);
  font-weight: 700;
}
.user-top h4 { font-size: 13px; }
.user-top p { color: var(--muted); font-size: 11px; margin-top: 1px; }
.user-chip {
  margin-left: auto; padding: 3px 8px; border-radius: 999px;
  color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent);
  font-size: 10px; white-space: nowrap;
}
.user-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 7px; margin: 12px 0 0; }
.user-stats div { padding: 7px 8px; border-radius: 9px; background: var(--surface); }
.user-stats dt { color: var(--muted); font-size: 10px; }
.user-stats dd { margin: 2px 0 0; font-size: 12px; font-weight: 650; }
.empty-line { color: var(--muted); font-size: 12px; margin-top: 14px; }

.sop-block { margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--border); }
.sop-head { display: flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 650; }
.sop-head small { margin-left: auto; color: var(--muted); font-weight: 400; }
.sop-block ul { list-style: none; padding: 0; margin: 9px 0 0; display: flex; flex-direction: column; gap: 7px; }
.sop-block li { color: var(--text-2); font-size: 11px; line-height: 1.55; }
.sop-block li span { display: inline-block; margin-right: 5px; color: var(--primary); font-family: var(--mono); font-size: 10px; }

.copy-btn {
  padding: 7px 11px; color: var(--primary); background: var(--primary-soft);
  border: 1px solid color-mix(in srgb, var(--primary) 25%, transparent);
}
.gated-tag {
  padding: 4px 9px; border-radius: 999px;
  color: var(--warn); background: var(--warn-soft);
  font-family: var(--mono); font-size: 10px;
}
.copy-btn:hover:not(:disabled) { transform: translateY(-1px); }
.copy-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.sms-preview {
  position: relative; margin-top: 14px; padding: 18px 16px 30px;
  border: 1px solid color-mix(in srgb, var(--primary) 20%, var(--border));
  border-radius: 14px;
  background:
    radial-gradient(300px 100px at 100% 0%, var(--primary-soft), transparent 70%),
    var(--surface-2);
}
.sms-label { font-family: var(--mono); font-size: 9px; color: var(--primary); letter-spacing: 0.08em; }
.sms-preview p { margin-top: 11px; font-size: 15px; line-height: 1.8; white-space: pre-wrap; }
.sms-count { position: absolute; right: 13px; bottom: 9px; color: var(--muted); font-family: var(--mono); font-size: 10px; }
.copy-note { display: flex; gap: 7px; color: var(--muted); font-size: 11px; margin-top: 13px; }
.copy-note span { color: var(--accent); }

@media (max-width: 860px) {
  .result-grid { grid-template-columns: 1fr; }
  .agent-hero { padding: 20px; }
  .agent-hero h2 { font-size: 24px; }
  .user-stats { grid-template-columns: repeat(2, 1fr); }
  .query-actions { align-items: flex-end; }
}
</style>
