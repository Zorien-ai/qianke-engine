<script setup>
/**
 * A 端 Agent 协作审批台：处理 MCP Agent Bus 的高风险任务与最近消息。
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { getJson, postJson } from "../api";

const loading = ref(true);
const error = ref("");
const activeTab = ref("approvals");
const approvals = ref([]);
const stats = ref({ pending: 0, approved: 0, rejected: 0 });
const messages = ref([]);
const ttlDays = ref(30);
const approvalStatus = ref("PENDING");
const busyId = ref("");
const notes = ref({});
const purgeResult = ref("");
let pollTimer = null;

function date(value) { return value ? String(value).replace("T", " ").slice(0, 19) : "—"; }
function riskText(risk) { return { low: "低风险", medium: "中风险", high: "高风险" }[risk] || risk || "—"; }
function riskClass(risk) { return risk === "high" ? "is-error" : risk === "medium" ? "is-running" : "is-ok"; }
function approvalStatusText(status) { return { PENDING: "待审批", APPROVED: "已同意", REJECTED: "已驳回" }[status] || status; }
function approvalStatusClass(status) { return status === "APPROVED" ? "is-ok" : status === "REJECTED" ? "is-error" : "is-running"; }
function messageTarget(item) { return item.room_id ? `群 ${item.room_id}` : (item.recipient || "广播"); }
function messagePreview(item) {
  const content = item.content || {};
  return String(content.title || content.text || content.instruction || JSON.stringify(content)).slice(0, 220);
}
function pendingCount() { return stats.value.pending || 0; }

async function loadApprovals() {
  const statusQuery = approvalStatus.value ? `?status=${encodeURIComponent(approvalStatus.value)}` : "";
  const data = await getJson(`/api/admin/agent-comm/approvals${statusQuery}`);
  approvals.value = data.items || [];
  stats.value = data.stats || stats.value;
  ttlDays.value = Number(data.ttl_days || 30);
}

async function loadMessages() {
  const data = await getJson("/api/admin/agent-comm/messages?limit=50");
  messages.value = data.items || [];
  ttlDays.value = Number(data.ttl_days || ttlDays.value);
}

async function loadAll() {
  loading.value = true;
  error.value = "";
  try {
    await Promise.all([loadApprovals(), loadMessages()]);
  } catch (e) {
    error.value = e?.detail || e?.message || "审批台加载失败";
  } finally {
    loading.value = false;
  }
  schedulePoll();
}

async function refresh() {
  try {
    await loadApprovals();
    if (activeTab.value === "messages") await loadMessages();
  } catch { /* 保留当前数据 */ }
  schedulePoll();
}

function schedulePoll() {
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  if (pendingCount() > 0 || approvalStatus.value === "PENDING") {
    pollTimer = setTimeout(refresh, 5000);
  }
}

async function decide(item, action) {
  if (busyId.value) return;
  busyId.value = item.approval_id;
  error.value = "";
  try {
    await postJson(`/api/admin/agent-comm/approvals/${encodeURIComponent(item.approval_id)}/decision`, {
      action,
      note: notes.value[item.approval_id] || "",
    });
    await Promise.all([loadApprovals(), loadMessages()]);
  } catch (e) {
    error.value = e?.detail || e?.message || "审批失败";
  } finally {
    busyId.value = "";
    schedulePoll();
  }
}

async function purge() {
  try {
    purgeResult.value = "";
    const data = await postJson("/api/admin/agent-comm/purge", {});
    purgeResult.value = `已清理 ${data.purged} 条过期正文（TTL ${data.ttl_days} 天）`;
    await loadMessages();
  } catch (e) {
    error.value = e?.detail || e?.message || "清理失败";
  }
}

async function switchStatus(value) {
  approvalStatus.value = value;
  try { await loadApprovals(); } catch (e) { error.value = e?.detail || e?.message || "加载失败"; }
  schedulePoll();
}

onMounted(loadAll);
onBeforeUnmount(() => { if (pollTimer) clearTimeout(pollTimer); });
</script>

<template>
  <div class="page agent-comm">
    <header class="admin-hero">
      <div>
        <div class="monitor-kicker">AGENT BUS · HUMAN CONTROL</div>
        <div class="admin-title-line">
          <h2>Agent 协作审批</h2>
          <span class="badge is-primary">{{ pendingCount() }} 待审批</span>
          <span class="badge is-warn">系统管理员</span>
        </div>
        <p class="card-sub">AI 之间通过 MCP 协作；高风险任务在这里由人确认。消息正文保留 {{ ttlDays }} 天，过期只留审计元数据。</p>
      </div>
      <button type="button" class="btn btn-ghost" :disabled="loading" @click="loadAll">刷新</button>
    </header>

    <div class="comm-stats">
      <div class="comm-stat"><span>待审批</span><b>{{ stats.pending }}</b><small>需要人工决策</small></div>
      <div class="comm-stat"><span>已同意</span><b>{{ stats.approved }}</b><small>已回到 Agent</small></div>
      <div class="comm-stat"><span>已驳回</span><b>{{ stats.rejected }}</b><small>不执行</small></div>
      <div class="comm-stat"><span>正文 TTL</span><b>{{ ttlDays }} 天</b><small>过期自动清理</small></div>
    </div>

    <div class="obs-tabs comm-tabs">
      <button type="button" :class="{ 'is-active': activeTab === 'approvals' }" @click="activeTab = 'approvals'">审批</button>
      <button type="button" :class="{ 'is-active': activeTab === 'messages' }" @click="activeTab = 'messages'; loadMessages()">最近消息</button>
    </div>

    <div v-if="error" class="card comm-error"><span>{{ error }}</span><button type="button" class="btn btn-ghost btn-sm" @click="error = ''">关闭</button></div>
    <div v-if="loading" class="card"><div class="skeleton" style="height:120px"></div></div>

    <template v-else-if="activeTab === 'approvals'">
      <div class="comm-filter">
        <span class="field-hint">查看：</span>
        <button v-for="item in [{ value: 'PENDING', label: '待审批' }, { value: 'APPROVED', label: '已同意' }, { value: 'REJECTED', label: '已驳回' }, { value: '', label: '全部' }]" :key="item.value" type="button" class="comm-filter-btn" :class="{ 'is-active': approvalStatus === item.value }" @click="switchStatus(item.value)">{{ item.label }}</button>
      </div>

      <div v-if="!approvals.length" class="card empty-state"><div class="empty-title">没有待处理审批</div><div class="empty-desc">高风险任务被 Agent 提出后会出现在这里。</div></div>
      <div v-else class="comm-approval-list">
        <article v-for="item in approvals" :key="item.approval_id" class="card comm-approval">
          <div class="comm-approval-head">
            <div>
              <div class="comm-approval-kicker">{{ item.task_id }} · {{ date(item.created_at) }}</div>
              <h3>{{ item.title }}</h3>
            </div>
            <span class="obs-status" :class="riskClass(item.risk)">{{ riskText(item.risk) }}</span>
          </div>
          <p class="comm-approval-instruction">{{ item.instruction || "未填写任务说明" }}</p>
          <div class="comm-meta-row">
            <span>发起：<b>{{ item.sender_id }}</b></span>
            <span>执行：<b>{{ item.assignee_id || "—" }}</b></span>
            <span>模式：<b>{{ item.mode === "auto" ? "自动执行" : "人工审批" }}</b></span>
            <span v-for="cap in item.required_capabilities" :key="cap" class="comm-cap">{{ cap }}</span>
          </div>
          <div v-if="item.status === 'PENDING'" class="comm-decision">
            <textarea v-model="notes[item.approval_id]" rows="2" maxlength="1000" placeholder="可选：审批备注，会记录到审批日志" />
            <div class="comm-actions">
              <button type="button" class="btn btn-primary" :disabled="busyId === item.approval_id" @click="decide(item, 'approve')">{{ busyId === item.approval_id ? "处理中…" : "同意并放行" }}</button>
              <button type="button" class="btn btn-ghost" :disabled="busyId === item.approval_id" @click="decide(item, 'reject')">驳回</button>
            </div>
          </div>
          <div v-else class="comm-decision-result">
            <span class="obs-status" :class="approvalStatusClass(item.status)">{{ approvalStatusText(item.status) }}</span>
            <span v-if="item.decided_by" class="field-hint">由 {{ item.decided_by }} · {{ date(item.decided_at) }}</span>
            <span v-if="item.decision_note" class="field-hint">备注：{{ item.decision_note }}</span>
          </div>
        </article>
      </div>
    </template>

    <template v-else>
      <section class="card comm-messages-card">
        <div class="admin-section-head">
          <strong>最近消息</strong>
          <div class="comm-head-actions">
            <span v-if="purgeResult" class="field-hint">{{ purgeResult }}</span>
            <button type="button" class="btn btn-ghost btn-sm" @click="purge">清理过期正文</button>
          </div>
        </div>
        <div v-if="!messages.length" class="field-hint">暂无消息</div>
        <div v-else class="comm-message-list">
          <article v-for="item in messages" :key="item.message_id" class="comm-message">
            <div class="comm-message-head">
              <span class="comm-message-kind">{{ item.kind }}</span>
              <b>{{ item.sender }}</b>
              <span class="field-hint">→ {{ messageTarget(item) }}</span>
              <span class="field-hint comm-message-time">{{ date(item.created_at) }}</span>
            </div>
            <p>{{ messagePreview(item) }}</p>
            <div class="comm-message-foot">
              <span class="field-hint">过期：{{ date(item.expires_at) }}</span>
              <span class="field-hint">{{ item.message_id }}</span>
            </div>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.comm-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.comm-stat { padding: 14px 16px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); }
.comm-stat span { display: block; color: var(--muted); font-size: 11.5px; }
.comm-stat b { display: block; margin-top: 5px; font-size: 24px; letter-spacing: -.03em; }
.comm-stat small { display: block; margin-top: 3px; color: var(--muted); font-size: 10.5px; }
.comm-tabs { margin: 14px 0 0; display: flex; gap: 4px; border-bottom: 1px solid var(--border); }
.comm-tabs button { padding: 7px 11px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--muted); font-size: 12px; cursor: pointer; }
.comm-tabs button.is-active { border-bottom-color: var(--primary); color: var(--text); }
.comm-error { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 14px; color: #991b1b; background: #fff7f7; border-color: #fecaca; }
.comm-filter { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin: 14px 0 10px; }
.comm-filter-btn { padding: 5px 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); color: var(--muted); font-size: 11px; cursor: pointer; }
.comm-filter-btn.is-active { border-color: var(--primary); background: var(--surface-2); color: var(--text); }
.comm-approval-list { display: grid; gap: 10px; }
.comm-approval { padding: 16px; }
.comm-approval-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.comm-approval-head h3 { margin: 4px 0 0; font-size: 15px; }
.comm-approval-kicker { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 10px; }
.comm-approval-instruction { margin: 10px 0; color: var(--text-2); font-size: 12.5px; line-height: 1.7; white-space: pre-wrap; }
.comm-meta-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; color: var(--muted); font-size: 11px; }
.comm-meta-row b { color: var(--text-2); font-weight: 600; }
.comm-cap { padding: 1px 6px; border-radius: 5px; background: var(--surface-3); color: var(--text-2); font-size: 10px; }
.comm-decision { display: flex; align-items: flex-end; gap: 8px; flex-wrap: wrap; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
.comm-decision textarea { flex: 1; min-width: 220px; padding: 8px 9px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; font-size: 12px; resize: vertical; }
.comm-actions { display: flex; gap: 6px; }
.comm-decision-result { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); }
.comm-obs { color: var(--muted); font-size: 11px; }
.comm-messages-card { margin-top: 14px; }
.comm-head-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.comm-message-list { display: grid; gap: 6px; margin-top: 10px; }
.comm-message { padding: 9px 11px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2); }
.comm-message-head { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; font-size: 11.5px; }
.comm-message-kind { padding: 1px 6px; border-radius: 5px; background: var(--surface-3); color: var(--text-2); font-size: 10px; }
.comm-message p { margin: 5px 0; color: var(--text-2); font-size: 12px; line-height: 1.6; word-break: break-word; }
.comm-message-time { margin-left: auto; }
.comm-message-foot { display: flex; justify-content: space-between; gap: 8px; }
.obs-status { display: inline-flex; align-items: center; padding: 2px 7px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.obs-status.is-ok { color: #166534; background: #e8f5ec; }
.obs-status.is-error { color: #991b1b; background: #fdeaea; }
.obs-status.is-running { color: #92400e; background: #fef3c7; }
.obs-tabs { display: flex; gap: 4px; }
@media (max-width: 700px) {
  .comm-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .comm-decision { align-items: stretch; }
  .comm-decision textarea { min-width: 100%; }
  .comm-actions .btn { flex: 1; }
}
</style>
