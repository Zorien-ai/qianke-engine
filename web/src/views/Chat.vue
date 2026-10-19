<script setup>
/**
 * 对话页：POST /qa/stream 流式问答。
 *
 * 关键点（与既有 static/app.js 的事件处理保持一致）：
 * - SSE 事件：stage / meta / delta / reasoning / replace / done / error；
 * - `replace` 必须**整体覆盖**已渲染正文（服务端后置审查命中时下发固定文案）；
 *   delta 是逐片到达的，[来源N] 的清理只能在前端做（切片会切断标记）；
 * - 显隐全部看 /whoami.can：topk / SQL 原文 / trace / 来源 / 思考模式；
 * - 前端不传 dataset / tenant：读哪个库由登录账号推导。
 */
import { computed, nextTick, onBeforeUnmount, reactive, ref } from "vue";
import { ApiError, apiFetch, detailMessage, readBody } from "../api";
import { hasCap, store, toast } from "../store";
import { renderMarkdown } from "../lib/markdown";

/* 示例问句只给"问法"，不写具体取值（城市名 / 等级名 / 品类名）。
 * 具体取值由当前数据决定，换一份数据后这些问法依然成立。 */
const EXAMPLE_QUESTIONS = [
  "高价值用户怎么定义的",
  "流失预警的判定标准",
  "用户说优惠券过期了怎么办",
  "客单价最高的用户有什么共同点",
  "用户主要分布在哪些城市",
  "各会员等级的用户分别有多少",
];

const question = ref("");
const sending = ref(false);
const phase = ref("idle"); // idle | retrieving | generating | reasoning | done | error | stopped
const answer = ref("");
const reasoning = ref("");
const reasoningOpen = ref(true);
const errorText = ref("");
const guardNotice = ref("");
const elapsed = ref(0);
const firstCharSec = ref(null);
const topk = ref("");
const thinking = ref(false);
const showDetail = ref(true);
const answerCard = ref(null);

const meta = reactive({
  route: "",
  sources: [],
  sql: "",
  rowsCount: null,
  sqlRows: [],
  sqlError: null,
  trace: null,
  cached: false,
  deepThinking: false,
});

const canAsk = computed(() => hasCap("ask"));
const canTopk = computed(() => hasCap("topk"));
const canSources = computed(() => hasCap("sources"));
const canSql = computed(() => hasCap("sql"));
const canInternals = computed(() => hasCap("internals"));
const canFlow = computed(() => hasCap("trace_flow"));

const streaming = computed(() => sending.value && ["retrieving", "generating", "reasoning"].includes(phase.value));

const phaseText = computed(() => {
  switch (phase.value) {
    case "retrieving":
      return "检索中…";
    case "reasoning":
      return "深度思考中…";
    case "generating":
      return "生成中…";
    case "done":
      return `完成 · 首字 ${firstCharSec.value != null ? firstCharSec.value.toFixed(1) + "s · " : ""}总计 ${elapsed.value.toFixed(1)}s`;
    case "stopped":
      return "已停止";
    case "error":
      return "出错了";
    default:
      return "";
  }
});

const routeLabel = computed(() => {
  const map = {
    rag: "RAG 检索问答",
    chitchat: "闲聊",
    error: "检索不可用",
    sql: "结构化查询",
    busy: "数据集忙",
  };
  return map[meta.route] || (meta.route ? String(meta.route).toUpperCase() : "RAG");
});

const answerHtml = computed(() =>
  renderMarkdown(answer.value, {
    cite: (n) => (canSources.value ? `<span class="cite">[来源${n}]</span>` : null),
  })
);

/* ---------- 来源 ---------- */
function sourceType(s) {
  const name = String((s && s.source) || "");
  if (name === "user_profile" || name.includes("画像")) return { key: "profile", label: "画像" };
  if (/\.md(#|$)/i.test(name) || name.includes("文档")) return { key: "wiki", label: "文档" };
  return { key: "other", label: "其他" };
}

const sourcesVisible = computed(() => (canSources.value ? meta.sources || [] : []));

/* ---------- 检索过程 trace ---------- */
const trace = computed(() => meta.trace || null);
const variants = computed(() => (trace.value && trace.value.variants) || []);
const totalHits = computed(() => variants.value.reduce((n, v) => n + (v.hit_count ?? 0), 0));
const flowLimits = computed(() => (trace.value && trace.value.limits) || {});

/* ---------- SQL / 查询结果 ---------- */
const showSqlText = computed(() => canSql.value && !!meta.sql);
const showSqlSection = computed(
  () => showSqlText.value || (meta.sqlRows && meta.sqlRows.length > 0) || (canSql.value && !!meta.sqlError)
);
const sqlTotal = computed(() =>
  typeof meta.rowsCount === "number" ? meta.rowsCount : (meta.sqlRows || []).length
);

const showDetailPanel = computed(() => {
  if (sourcesVisible.value.length) return true;
  if (showSqlSection.value) return true;
  if (canInternals.value && (trace.value || variants.value.length)) return true;
  return false;
});

/* ---------- 流式解析 ---------- */
let controller = null;
let renderTimer = null;
let pendingAnswer = "";
let t0 = 0;
let firstDeltaAt = null;

function scheduleAnswer() {
  if (renderTimer) return;
  renderTimer = setTimeout(() => {
    renderTimer = null;
    answer.value = pendingAnswer;
  }, 70);
}

function flushAnswer() {
  if (renderTimer) {
    clearTimeout(renderTimer);
    renderTimer = null;
  }
  answer.value = pendingAnswer;
}

function handleChunk(part) {
  let event = "message";
  const dataLines = [];
  for (const rawLine of part.split("\n")) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return;
  let data;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    return;
  }

  if (event === "stage") {
    phase.value = data.stage === "generating" ? "generating" : "retrieving";
  } else if (event === "meta") {
    meta.route = data.route || meta.route;
    meta.sources = data.sources || [];
    meta.sql = data.sql || "";
    meta.rowsCount = data.rows_count ?? null;
    meta.sqlRows = data.sql_rows || [];
    meta.sqlError = data.sql_error ?? null;
    meta.trace = data.trace || null;
    meta.cached = !!data.cached;
    meta.deepThinking = !!data.deep_thinking;
    if (data.cached) toast("命中缓存：以下来源与过程是上一次的检索结果", "info");
  } else if (event === "reasoning") {
    phase.value = "reasoning";
    reasoningOpen.value = true;
    reasoning.value += data.delta || "";
  } else if (event === "delta") {
    if (firstDeltaAt == null) {
      firstDeltaAt = performance.now();
      firstCharSec.value = (firstDeltaAt - t0) / 1000;
      // 正文开始到达：把思维链收起来，否则会把回答顶出视口
      if (reasoning.value) reasoningOpen.value = false;
    }
    phase.value = "generating";
    pendingAnswer += data.delta || "";
    scheduleAnswer();
  } else if (event === "replace") {
    // 后置审查命中：此前下发的正文作废，整体覆盖
    pendingAnswer = data.answer || "";
    flushAnswer();
    guardNotice.value = "回答涉及预测性内容，已被安全策略整体替换为固定说明。";
    toast("回答已被安全策略替换", "warn");
  } else if (event === "error") {
    const err = new Error(data.message || "服务端错误");
    err.kind = data.kind || "";
    err.detail = data.message || "服务端错误";
    throw err;
  }
}

async function submit() {
  const text = question.value.trim();
  if (!text) {
    toast("请先输入问题", "warn");
    return;
  }
  if (!canAsk.value) {
    toast("当前账号没有提问能力，请联系管理员", "error");
    return;
  }
  if (sending.value) return;

  // 重置上一轮
  answer.value = "";
  pendingAnswer = "";
  reasoning.value = "";
  reasoningOpen.value = true;
  errorText.value = "";
  guardNotice.value = "";
  elapsed.value = 0;
  firstCharSec.value = null;
  firstDeltaAt = null;
  Object.assign(meta, {
    route: "",
    sources: [],
    sql: "",
    rowsCount: null,
    sqlRows: [],
    sqlError: null,
    trace: null,
    cached: false,
    deepThinking: false,
  });

  phase.value = "retrieving";
  sending.value = true;
  t0 = performance.now();
  controller = new AbortController();

  try {
    const payload = { question: text };
    if (canTopk.value && topk.value !== "") {
      const n = Number(topk.value);
      if (Number.isFinite(n)) payload.top_k = n;
    }
    if (thinking.value) payload.deep_thinking = true;

    const res = await apiFetch("/qa/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!res.ok) {
      const data = await readBody(res);
      throw new ApiError(res.status, detailMessage(data, res.status), data);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split(/\r?\n\r?\n/);
      buffer = parts.pop();
      for (const part of parts) handleChunk(part);
    }
    flushAnswer();
    if (phase.value !== "error") phase.value = "done";
    elapsed.value = (performance.now() - t0) / 1000;
    await nextTick();
    if (answerCard.value && answerCard.value.scrollIntoView) {
      answerCard.value.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (e) {
    if (e && e.name === "AbortError") {
      phase.value = "stopped";
      toast("已停止本次生成", "info");
    } else {
      phase.value = "error";
      errorText.value =
        e && e.kind === "llm_unavailable"
          ? "模型服务暂时不可用（LLM 接口调用失败），请稍后重试。检索是正常的——你的问题和资料都没问题。"
          : (e && (e.detail || e.message)) || "请求失败";
      // 错误已经在回答区下方完整展示；不再 toast 原始报错——
      // LLM 故障的 message 可能带上游 key/请求细节，不该出现在浮层里。
      if (e && e.kind !== "llm_unavailable" && e.status === 403) {
        toast(e.detail || e.message || "当前身份无权提问", "error", 5000);
      }
    }
    flushAnswer();
    elapsed.value = (performance.now() - t0) / 1000;
  } finally {
    sending.value = false;
    controller = null;
  }
}

function stop() {
  if (controller) controller.abort();
}

function resetAll() {
  if (sending.value) stop();
  question.value = "";
  answer.value = "";
  pendingAnswer = "";
  reasoning.value = "";
  errorText.value = "";
  guardNotice.value = "";
  phase.value = "idle";
  elapsed.value = 0;
  firstCharSec.value = null;
  reasoningOpen.value = true;
  Object.assign(meta, {
    route: "",
    sources: [],
    sql: "",
    rowsCount: null,
    sqlRows: [],
    sqlError: null,
    trace: null,
    cached: false,
    deepThinking: false,
  });
}

function useExample(q) {
  question.value = q;
}

function onKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    submit();
  }
}

onBeforeUnmount(() => {
  if (controller) controller.abort();
  if (renderTimer) clearTimeout(renderTimer);
});
</script>

<template>
  <div class="page">
    <!-- 提问框 -->
    <section class="composer">
      <textarea
        v-model="question"
        :disabled="sending || !canAsk"
        :placeholder="
          canAsk
            ? '问点什么，比如业务规则、用户分布、客单价……（Ctrl / Cmd + Enter 发送）'
            : '当前账号没有提问能力'
        "
        @keydown="onKeydown"
      ></textarea>

      <div class="composer-foot">
        <span class="composer-hint"><kbd class="kbd">Ctrl</kbd> / <kbd class="kbd">Cmd</kbd> + <kbd class="kbd">Enter</kbd> 发送</span>

        <label v-if="canTopk" class="topk-control">
          返回用户数
          <input
            v-model="topk"
            type="number"
            :min="store.topkRange.min"
            :max="store.topkRange.max"
            placeholder="默认"
          />
          <span class="field-hint">{{ store.topkRange.min }}~{{ store.topkRange.max }}</span>
        </label>

        <label class="toggle">
          <input v-model="thinking" type="checkbox" :disabled="sending" />
          <span class="toggle-track"></span>
          深度思考
        </label>

        <span class="spacer"></span>

        <button v-if="sending" type="button" class="btn btn-ghost" @click="stop">停止</button>
        <button v-else type="button" class="btn btn-primary" :disabled="!canAsk || !question.trim()" @click="submit">
          提问
        </button>
      </div>

      <div class="examples">
        <button
          v-for="q in EXAMPLE_QUESTIONS"
          :key="q"
          type="button"
          class="chip"
          :disabled="sending || !canAsk"
          @click="useExample(q)"
        >
          {{ q }}
        </button>
      </div>

      <p v-if="canTopk" class="field-hint" style="margin-top: 10px">
        「返回用户数」只影响画像召回的候选上限，由后端按权限再次夹取；留空用系统默认。
      </p>
    </section>

    <!-- 首屏空态 -->
    <section v-if="phase === 'idle' && !answer && !errorText" class="card" style="margin-top: 16px">
      <div class="empty-state">
        <div class="empty-emoji">✨</div>
        <div class="empty-title">向你的企业知识库提问</div>
        <div class="empty-desc">
          回答会流式生成，并附带来源与检索过程（可见范围取决于账号等级）。
          数据来自当前登录账号的数据空间，前端不会传数据集参数。
        </div>
        <div class="row-actions">
          <span class="badge" v-if="!canSources">来源列表：当前等级不可见</span>
          <span class="badge" v-if="canSources">来源列表：可见</span>
          <span class="badge" v-if="canInternals">检索过程：可见</span>
          <span class="badge" v-if="canSql">SQL 原文：可见</span>
        </div>
      </div>
    </section>

    <div class="chat-stream" style="margin-top: 16px">
      <!-- 错误态 -->
      <div v-if="errorText" class="alert is-error">
        <div>
          <strong>请求失败：</strong>{{ errorText }}
          <div class="row-actions" style="margin-top: 10px">
            <button type="button" class="btn btn-sm btn-ghost" @click="submit">重试</button>
            <button type="button" class="btn btn-sm btn-ghost" @click="resetAll">清空</button>
          </div>
        </div>
      </div>

      <!-- 回答 -->
      <section v-if="answer || phase === 'retrieving' || phase === 'reasoning'" ref="answerCard" class="answer-card">
        <div class="answer-head">
          <span class="badge is-primary">{{ routeLabel }}</span>
          <span class="answer-status">
            <span v-if="streaming" class="spinner spinner-sm" />
            <span class="status-dot" :class="{ 'is-running': streaming, 'is-done': phase === 'done', 'is-error': phase === 'error' }" v-else></span>
            {{ phaseText }}
          </span>
          <span v-if="meta.cached" class="badge is-warn">缓存命中</span>
          <span v-if="guardNotice" class="badge is-warn">已按安全策略替换</span>
          <span class="spacer"></span>
          <button v-if="!sending && answer" type="button" class="btn btn-sm btn-ghost" @click="resetAll">新对话</button>
        </div>

        <div v-if="reasoning" class="reasoning-box">
          <div class="reasoning-head" @click="reasoningOpen = !reasoningOpen">
            <span>{{ reasoningOpen ? "▾" : "▸" }}</span>
            <span>思维链</span>
            <span class="badge">{{ reasoning.length }} 字</span>
            <span class="spacer"></span>
            <span class="field-hint">仅展示，不属于回答，不参与 [来源N] 引用</span>
          </div>
          <div v-show="reasoningOpen" class="reasoning-body">{{ reasoning }}</div>
        </div>

        <div
          v-if="guardNotice"
          class="alert is-warn"
          style="margin-bottom: 12px"
        >
          {{ guardNotice }}
        </div>

        <div v-if="answer" class="answer-body" :class="{ 'is-streaming': streaming }" v-html="answerHtml"></div>
        <div v-else-if="phase === 'retrieving'" class="empty-desc">
          正在检索知识库与用户画像，返回用户数较多时检索会慢一点…
        </div>
        <div v-else-if="phase === 'reasoning'" class="empty-desc">
          模型正在深度推理（首字可能要等 20~45 秒），推理完成后正文会开始流式输出。
        </div>
        <div v-if="guardNotice" class="cache-note" style="margin-top: 8px">{{ guardNotice }}</div>
      </section>

      <!-- 溯源与过程 -->
      <section v-if="showDetailPanel && !errorText" class="detail-panel">
        <div class="detail-section">
          <div class="detail-section-title">
            数据来源
            <span class="count" v-if="sourcesVisible.length">共 {{ sourcesVisible.length }} 条</span>
            <span class="spacer"></span>
            <button type="button" class="btn btn-sm btn-ghost" @click="showDetail = !showDetail">
              {{ showDetail ? "收起过程" : "展开过程" }}
            </button>
          </div>

          <div v-if="meta.cached" class="cache-note" style="margin-bottom: 10px">
            本次命中缓存、未重新检索：以下内容均为缓存中的上一次结果。
          </div>

          <template v-if="showDetail">
            <!-- 来源列表：can.sources 才渲染 -->
            <div v-if="sourcesVisible.length" class="source-list">
              <div v-for="s in sourcesVisible" :key="s.index" class="source-item">
                <div class="source-head">
                  <span class="source-index">[来源{{ s.index }}]</span>
                  <span class="source-name">{{ s.source || "未知来源" }}</span>
                  <span class="tag" :class="`is-${sourceType(s).key}`">{{ sourceType(s).label }}</span>
                  <span v-if="s.expanded" class="tag">
                    {{ s.expand_scope === "section" ? "章节回填" : "全文扩展" }}
                  </span>
                  <span v-for="st in s.strategies || []" :key="st" class="tag">{{ st }}</span>
                  <span class="source-score" v-if="typeof s.rerank_score === 'number'">
                    精排 {{ s.rerank_score.toFixed(4) }}
                  </span>
                </div>
                <div v-if="s.from_query" class="source-from">命中检索式：{{ s.from_query }}</div>
                <div v-if="s.text" class="source-text">{{ s.text }}</div>
                <div v-if="(s.images || []).length" class="source-images">
                  <a
                    v-for="(img, i) in s.images.filter((x) => x && x.url)"
                    :key="img.key || i"
                    :href="img.url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <img :src="img.url" :alt="img.alt || '资料配图'" loading="lazy" />
                  </a>
                </div>
              </div>
            </div>
            <div v-else-if="!sourcesVisible.length && canSources" class="tp-empty field-hint">
              本次没有返回来源（闲聊或检索兜底时为空）。
            </div>

            <!-- 检索过程：can.internals -->
            <div v-if="canInternals" class="detail-section" style="margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border)">
              <div class="detail-section-title">检索过程</div>
              <div class="trace-chips">
                <span class="trace-chip">检索路 <b>{{ variants.length }}</b> 条</span>
                <template v-if="trace">
                  <span class="trace-chip" :class="{ 'is-warn': !trace.need_sql }">
                    LLM 判定：{{ trace.need_sql ? "需要 SQL" : "不需要 SQL" }}
                  </span>
                  <span v-if="trace.question" class="trace-chip">原问题：{{ trace.question }}</span>
                </template>
                <span v-else class="trace-chip is-warn">本次未产生检索过程数据</span>
              </div>

              <div v-if="variants.length" class="trace-variants">
                <div v-for="(v, i) in variants" :key="i" class="trace-variant">
                  <div class="trace-variant-head">
                    <span class="trace-strategy">{{ v.strategy || "-" }}</span>
                    <span class="trace-count">
                      召回 {{ v.hit_count ?? 0 }} 条 · 画像入池 {{ v.profile_candidates ?? 0 }} · 文档留 {{ v.kept_count ?? 0 }} 条
                    </span>
                  </div>
                  <div class="trace-query">检索式：{{ v.query || "" }}</div>
                  <div class="trace-src-list">
                    <span v-for="name in v.sources || []" :key="name" class="trace-src">{{ name }}</span>
                    <span v-if="!(v.sources || []).length" class="trace-src">无命中</span>
                  </div>
                  <div v-if="v.error" class="cache-note" style="margin-top: 6px">{{ v.error }}</div>
                </div>
              </div>

              <!-- 融合与精排：can.trace_flow -->
              <div v-if="canFlow && trace" class="trace-flow" style="margin-top: 12px">
                <span class="trace-node">各路并行召回 <b>{{ totalHits }}</b></span>
                <span class="trace-arrow">→</span>
                <span class="trace-node">
                  画像池统一精排
                  <b v-if="flowLimits.profile_pool != null">{{ trace.profile_pool_count ?? 0 }}→{{ flowLimits.profile_pool }}</b>
                </span>
                <span class="trace-arrow">→</span>
                <span class="trace-node">
                  文档池每路
                  <b v-if="flowLimits.wiki_per_route != null">{{ flowLimits.wiki_per_route }}</b>
                </span>
                <span class="trace-arrow">→</span>
                <span class="trace-node">合并去重 <b>{{ trace.fused_count ?? 0 }}</b></span>
                <span class="trace-arrow">→</span>
                <span class="trace-node is-final">入上下文 <b>{{ sourcesVisible.length }}</b></span>
              </div>
            </div>

            <!-- SQL 原文（can.sql）+ 查询结果（业务事实，所有人可见） -->
            <div v-if="showSqlSection" class="detail-section" style="margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border)">
              <div class="detail-section-title">
                查询结果
                <span class="count" v-if="sqlTotal != null">共 {{ sqlTotal }} 行</span>
              </div>
              <pre v-if="showSqlText" class="sql-block">{{ meta.sql }}</pre>
              <p v-if="canSql && meta.sqlError" style="color: var(--danger); font-size: 12px; margin: 8px 0">
                执行失败：{{ meta.sqlError }}
              </p>
              <div v-if="meta.sqlRows && meta.sqlRows.length" class="table-wrap" style="margin-top: 10px">
                <table class="table sql-table">
                  <tbody>
                    <tr v-for="(row, i) in meta.sqlRows" :key="i">
                      <td v-for="(cell, j) in row" :key="j">{{ cell }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p v-else class="field-hint" style="margin-top: 8px">
                {{ canSql && meta.sqlError ? "查询执行失败，详见上方错误。" : "（空结果）" }}
              </p>
              <p v-if="!canSql" class="field-hint" style="margin-top: 8px">
                SQL 原文属于「SQL 原文」能力（默认 L4 可见）；查询结果行是业务事实，所有能提问的账号都能看到。
              </p>
            </div>
          </template>
        </div>
      </section>
    </div>
  </div>
</template>
