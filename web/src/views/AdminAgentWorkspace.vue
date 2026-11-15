<script setup>
/**
 * A 端多 AI 协作工作台：群聊 + Agent 花名册 + 任务。
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { getJson, postJson } from "../api";

const loading = ref(true);
const error = ref("");
const workspace = ref({ agents: [], rooms: [], tasks: [], pending_approvals: [] });
const activeRoomId = ref("");
const messages = ref([]);
const messageText = ref("");
const newRoomName = ref("");
const sending = ref(false);
const creatingRoom = ref(false);
const taskTitle = ref("");
const taskInstruction = ref("");
const taskCaps = ref("");
const taskRisk = ref("low");
const taskMode = ref("auto");
const creatingTask = ref(false);
const roomIdCopied = ref(false);
let timer = null;

const activeRoom = computed(() => (workspace.value.rooms || []).find((room) => room.room_id === activeRoomId.value) || null);
const agents = computed(() => workspace.value.agents || []);
const tasks = computed(() => workspace.value.tasks || []);
const pendingApprovals = computed(() => workspace.value.pending_approvals || []);
const canSend = computed(() => !!activeRoomId.value && !!messageText.value.trim() && !sending.value);

function date(value) { return value ? String(value).replace("T", " ").slice(0, 19) : "—"; }
function statusText(status) {
  return { ASSIGNED: "已分配", WAITING_APPROVAL: "待审批", RUNNING: "执行中", COMPLETED: "已完成", REJECTED: "已驳回" }[status] || status || "—";
}
function statusClass(status) {
  if (status === "COMPLETED" || status === "ASSIGNED") return "is-ok";
  if (status === "REJECTED") return "is-error";
  return "is-running";
}
function riskText(risk) { return { low: "低风险", medium: "中风险", high: "高风险" }[risk] || risk || "—"; }
function riskClass(risk) { return risk === "high" ? "is-error" : risk === "medium" ? "is-running" : "is-ok"; }
function senderLabel(sender) {
  if (String(sender).startsWith("human:")) return `人类 · ${String(sender).slice(6)}`;
  return sender || "unknown";
}
function isHuman(sender) { return String(sender).startsWith("human:"); }
function messageTextOf(item) {
  const content = item.content || {};
  if (content.text) return String(content.text);
  if (content.title) return String(content.title);
  if (content.instruction) return String(content.instruction);
  return JSON.stringify(content);
}
function agentCaps(agent) { return (agent.capabilities || []).join(" / "); }

async function loadWorkspace() {
  const data = await getJson("/api/admin/agent-comm/workspace");
  workspace.value = data;
  if (!activeRoomId.value && data.rooms?.length) activeRoomId.value = data.rooms[0].room_id;
  if (activeRoomId.value) await loadMessages();
}

async function loadMessages() {
  if (!activeRoomId.value) return;
  try {
    const data = await getJson(`/api/admin/agent-comm/rooms/${encodeURIComponent(activeRoomId.value)}/messages?limit=80`);
    messages.value = data.items || [];
  } catch (e) {
    error.value = e?.detail || e?.message || "群消息加载失败";
  }
}

async function refresh() {
  try {
    await loadWorkspace();
  } catch (e) {
    error.value = e?.detail || e?.message || "工作台刷新失败";
  }
}

async function selectRoom(room) {
  activeRoomId.value = room.room_id;
  roomIdCopied.value = false;
  await loadMessages();
}

async function createRoom() {
  if (!newRoomName.value.trim() || creatingRoom.value) return;
  creatingRoom.value = true;
  error.value = "";
  try {
    const room = await postJson("/api/admin/agent-comm/rooms", { name: newRoomName.value.trim() });
    newRoomName.value = "";
    activeRoomId.value = room.room_id;
    await loadWorkspace();
  } catch (e) {
    error.value = e?.detail || e?.message || "创建群失败";
  } finally {
    creatingRoom.value = false;
  }
}

async function sendMessage() {
  if (!canSend.value) return;
  sending.value = true;
  error.value = "";
  try {
    await postJson(`/api/admin/agent-comm/rooms/${encodeURIComponent(activeRoomId.value)}/messages`, { text: messageText.value.trim() });
    messageText.value = "";
    await loadMessages();
  } catch (e) {
    error.value = e?.detail || e?.message || "发送失败";
  } finally {
    sending.value = false;
  }
}

async function createTask() {
  if (!taskTitle.value.trim() || creatingTask.value) return;
  creatingTask.value = true;
  error.value = "";
  try {
    const caps = taskCaps.value.split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean);
    await postJson("/api/admin/agent-comm/tasks", {
      title: taskTitle.value.trim(),
      instruction: taskInstruction.value.trim(),
      required_capabilities: caps,
      risk: taskRisk.value,
      mode: taskMode.value,
    });
    taskTitle.value = "";
    taskInstruction.value = "";
    taskCaps.value = "";
    await loadWorkspace();
  } catch (e) {
    error.value = e?.detail || e?.message || "任务创建失败";
  } finally {
    creatingTask.value = false;
  }
}

async function copyRoomId() {
  if (!activeRoom.value) return;
  try {
    await navigator.clipboard.writeText(activeRoom.value.room_id);
    roomIdCopied.value = true;
  } catch {
    roomIdCopied.value = false;
  }
}

onMounted(async () => {
  try {
    await loadWorkspace();
  } catch (e) {
    error.value = e?.detail || e?.message || "工作台加载失败";
  } finally {
    loading.value = false;
  }
  timer = setInterval(refresh, 3000);
});
onBeforeUnmount(() => { if (timer) clearInterval(timer); });
</script>

<template>
  <div class="page agent-workspace">
    <header class="admin-hero">
      <div>
        <div class="monitor-kicker">AGENT BUS · WORKSPACE</div>
        <div class="admin-title-line">
          <h2>Agent 协作工作台</h2>
          <span class="badge is-primary">{{ agents.length }} Agents</span>
          <span class="badge is-warn">{{ pendingApprovals.length }} 待审批</span>
        </div>
        <p class="card-sub">WorkBuddy 和其他助手通过 MCP / HTTP 接入同一个 Bus；这里看群聊、派任务和处理审批。</p>
      </div>
      <div class="ws-head-actions">
        <button type="button" class="btn btn-ghost btn-sm" @click="refresh">刷新</button>
        <router-link class="btn btn-primary btn-sm" to="/admin/agent-comm">审批台（{{ pendingApprovals.length }}）</router-link>
      </div>
    </header>

    <div v-if="error" class="card ws-error"><span>{{ error }}</span><button type="button" class="btn btn-ghost btn-sm" @click="error = ''">关闭</button></div>
    <div v-if="loading" class="card"><div class="skeleton" style="height:180px"></div></div>

    <div v-else class="ws-grid">
      <aside class="ws-rooms card">
        <div class="admin-section-head"><strong>群组</strong><span class="field-hint">{{ (workspace.rooms || []).length }}</span></div>
        <div class="ws-new-room">
          <input v-model="newRoomName" maxlength="80" placeholder="新群名称" @keyup.enter="createRoom" />
          <button type="button" class="btn btn-primary btn-sm" :disabled="creatingRoom || !newRoomName.trim()" @click="createRoom">建群</button>
        </div>
        <div v-if="!(workspace.rooms || []).length" class="empty-state ws-empty"><div class="empty-title">还没有群</div><div class="empty-desc">建一个群，让 WorkBuddy 加入。</div></div>
        <button
          v-for="room in workspace.rooms || []"
          :key="room.room_id"
          type="button"
          class="ws-room-item"
          :class="{ 'is-active': room.room_id === activeRoomId }"
          @click="selectRoom(room)"
        >
          <b>{{ room.name }}</b>
          <span>{{ room.member_count || 0 }} 个成员 · {{ date(room.created_at) }}</span>
        </button>
        <p class="field-hint ws-room-tip">让 WorkBuddy 加入群：POST /agent-comm/remote action=join_room，room_id 见右侧。</p>
      </aside>

      <section class="ws-chat card">
        <template v-if="activeRoom">
          <div class="ws-chat-head">
            <div>
              <div class="monitor-kicker">ROOM</div>
              <h3>{{ activeRoom.name }}</h3>
            </div>
            <div class="ws-room-id">
              <span>{{ activeRoom.room_id }}</span>
              <button type="button" class="btn btn-ghost btn-sm" @click="copyRoomId">{{ roomIdCopied ? "已复制" : "复制" }}</button>
            </div>
          </div>

          <div class="ws-messages">
            <div v-if="!messages.length" class="empty-state ws-empty"><div class="empty-title">群里还没有消息</div><div class="empty-desc">人类或 Agent 发言后会显示在这里。</div></div>
            <article v-for="item in messages" :key="item.message_id" class="ws-message" :class="{ 'is-human': isHuman(item.sender) }">
              <div class="ws-message-head">
                <b>{{ senderLabel(item.sender) }}</b>
                <span class="ws-kind">{{ item.kind }}</span>
                <time>{{ date(item.created_at) }}</time>
              </div>
              <p>{{ messageTextOf(item) }}</p>
              <div v-if="item.task_id" class="field-hint">task：{{ item.task_id }}</div>
            </article>
          </div>

          <div class="ws-composer">
            <textarea v-model="messageText" rows="2" maxlength="4000" placeholder="以人类身份发言，连上这个群的 Agent 都能读到…" @keydown.ctrl.enter="sendMessage" />
            <div class="ws-composer-foot">
              <span class="field-hint">Ctrl + Enter 发送</span>
              <button type="button" class="btn btn-primary" :disabled="!canSend" @click="sendMessage">{{ sending ? "发送中…" : "发送" }}</button>
            </div>
          </div>
        </template>
        <div v-else class="empty-state ws-empty"><div class="empty-title">选择一个群</div><div class="empty-desc">左侧建群或选择已有群。</div></div>
      </section>

      <aside class="ws-side">
        <section class="card ws-side-card">
          <div class="admin-section-head"><strong>Agent 花名册</strong><span class="field-hint">固定能力</span></div>
          <div class="ws-agent" v-for="agent in agents" :key="agent.agent_id">
            <div class="ws-agent-head"><b>{{ agent.display_name }}</b><span class="ws-agent-id">{{ agent.agent_id }}</span></div>
            <div class="ws-caps"><span v-for="cap in agent.capabilities" :key="cap">{{ cap }}</span></div>
            <small>风险上限：{{ riskText(agent.max_risk) }}<span v-if="agent.auto_accept"> · 自动接单</span></small>
          </div>
        </section>

        <section class="card ws-side-card">
          <div class="admin-section-head"><strong>派任务</strong><span class="field-hint">按能力路由</span></div>
          <label class="ws-field"><span>标题</span><input v-model="taskTitle" maxlength="120" placeholder="例如：C 端详情页回归" /></label>
          <label class="ws-field"><span>说明</span><textarea v-model="taskInstruction" rows="2" maxlength="4000" placeholder="可选" /></label>
          <label class="ws-field"><span>所需能力</span><input v-model="taskCaps" placeholder="c_end, ui" /></label>
          <div class="ws-field-row">
            <label class="ws-field"><span>风险</span><select v-model="taskRisk"><option value="low">低</option><option value="medium">中</option><option value="high">高</option></select></label>
            <label class="ws-field"><span>模式</span><select v-model="taskMode"><option value="auto">自动</option><option value="approval">审批</option></select></label>
          </div>
          <button type="button" class="btn btn-primary ws-full" :disabled="creatingTask || !taskTitle.trim()" @click="createTask">{{ creatingTask ? "创建中…" : "派发任务" }}</button>
        </section>

        <section class="card ws-side-card">
          <div class="admin-section-head"><strong>任务</strong><span class="field-hint">{{ tasks.length }}</span></div>
          <div v-if="!tasks.length" class="field-hint">暂无任务</div>
          <div v-for="task in tasks.slice(0, 8)" :key="task.task_id" class="ws-task">
            <div class="ws-task-head"><b>{{ task.title }}</b><span class="obs-status" :class="statusClass(task.status)">{{ statusText(task.status) }}</span></div>
            <small>{{ task.sender_id }} → {{ task.assignee_id || "待定" }} · {{ riskText(task.risk) }}</small>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.ws-head-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ws-error { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 14px; color: #991b1b; background: #fff7f7; border-color: #fecaca; }
.ws-grid { display: grid; grid-template-columns: 250px minmax(0, 1fr) 300px; gap: 12px; margin-top: 14px; align-items: start; }
.ws-rooms { padding: 14px; position: sticky; top: 12px; }
.ws-new-room { display: flex; gap: 5px; margin: 10px 0; }
.ws-new-room input { min-width: 0; flex: 1; height: 32px; padding: 0 8px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); color: var(--text); font-size: 12px; }
.ws-room-item { display: flex; flex-direction: column; gap: 3px; width: 100%; padding: 9px 10px; margin-top: 4px; border: 1px solid transparent; border-radius: 8px; background: transparent; text-align: left; cursor: pointer; }
.ws-room-item:hover { background: var(--surface-2); }
.ws-room-item.is-active { border-color: var(--border); background: var(--surface-2); }
.ws-room-item b { font-size: 12.5px; }
.ws-room-item span { color: var(--muted); font-size: 10.5px; }
.ws-room-tip { margin: 12px 0 0; line-height: 1.6; }
.ws-empty { padding: 22px 8px; }
.ws-chat { padding: 14px; min-height: 520px; display: flex; flex-direction: column; }
.ws-chat-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
.ws-chat-head h3 { margin: 4px 0 0; font-size: 16px; }
.ws-room-id { display: flex; align-items: center; gap: 5px; max-width: 52%; }
.ws-room-id span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); font-family: ui-monospace, Consolas, monospace; font-size: 10px; }
.ws-messages { flex: 1; display: flex; flex-direction: column; gap: 8px; padding: 12px 2px; min-height: 320px; max-height: 540px; overflow-y: auto; }
.ws-message { max-width: 82%; align-self: flex-start; padding: 9px 11px; border: 1px solid var(--border); border-radius: 10px; border-top-left-radius: 3px; background: var(--surface-2); }
.ws-message.is-human { align-self: flex-end; border-top-left-radius: 10px; border-top-right-radius: 3px; background: color-mix(in srgb, var(--primary) 10%, var(--surface)); }
.ws-message-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ws-message-head b { font-size: 11.5px; }
.ws-message-head time { margin-left: auto; color: var(--muted); font-size: 9.5px; }
.ws-kind { padding: 1px 5px; border-radius: 4px; background: var(--surface-3); color: var(--muted); font-size: 9.5px; }
.ws-message p { margin: 5px 0 0; color: var(--text-2); font-size: 12px; line-height: 1.65; white-space: pre-wrap; word-break: break-word; }
.ws-composer { border-top: 1px solid var(--border); padding-top: 10px; }
.ws-composer textarea { width: 100%; padding: 8px 9px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; font-size: 12px; resize: vertical; }
.ws-composer-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; }
.ws-side { display: grid; gap: 10px; }
.ws-side-card { padding: 14px; }
.ws-agent { padding: 8px 0; border-bottom: 1px solid var(--border); }
.ws-agent:last-child { border-bottom: 0; }
.ws-agent-head { display: flex; align-items: baseline; justify-content: space-between; gap: 6px; }
.ws-agent-head b { font-size: 12px; }
.ws-agent-id { color: var(--muted); font-family: ui-monospace, Consolas, monospace; font-size: 9.5px; }
.ws-caps { display: flex; gap: 4px; flex-wrap: wrap; margin: 5px 0; }
.ws-caps span { padding: 1px 5px; border-radius: 4px; background: var(--surface-3); color: var(--text-2); font-size: 9.5px; }
.ws-agent small { color: var(--muted); font-size: 9.5px; }
.ws-field { display: flex; flex-direction: column; gap: 3px; margin-top: 8px; }
.ws-field span { color: var(--muted); font-size: 10px; }
.ws-field input, .ws-field select, .ws-field textarea { width: 100%; padding: 6px 7px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); font: inherit; font-size: 11.5px; resize: vertical; }
.ws-field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.ws-full { width: 100%; margin-top: 10px; }
.ws-task { padding: 7px 0; border-bottom: 1px solid var(--border); }
.ws-task:last-child { border-bottom: 0; }
.ws-task-head { display: flex; align-items: baseline; justify-content: space-between; gap: 6px; }
.ws-task-head b { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11.5px; }
.ws-task small { display: block; margin-top: 2px; color: var(--muted); font-size: 9.5px; }
.obs-status { display: inline-flex; align-items: center; padding: 1px 6px; border-radius: 999px; font-size: 9.5px; font-weight: 600; white-space: nowrap; }
.obs-status.is-ok { color: #166534; background: #e8f5ec; }
.obs-status.is-error { color: #991b1b; background: #fdeaea; }
.obs-status.is-running { color: #92400e; background: #fef3c7; }
@media (max-width: 1100px) {
  .ws-grid { grid-template-columns: 220px minmax(0, 1fr); }
  .ws-side { grid-column: 1 / -1; grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .ws-grid { grid-template-columns: 1fr; }
  .ws-rooms { position: static; }
  .ws-side { grid-template-columns: 1fr; }
  .ws-chat { min-height: 480px; }
  .ws-message { max-width: 94%; }
}
</style>
