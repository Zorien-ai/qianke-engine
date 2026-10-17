<script setup>
/**
 * 第 4 步：提问验证（构建完成后才可进）。
 *
 * GET /api/wizard/examples?upload_id= 拿示例问句（服务端按已确认字段 + 上传文件
 * 里的真实取值生成，前端不写死业务取值）；POST /api/wizard/query 只传
 * {question, upload_id}——dataset 由账号推导，前端不传。
 *
 * 答案渲染复用 lib/markdown.js；正文里的 [来源N] 可点击跳转到下方来源卡片。
 */
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { getJson, postJson } from "../../api";
import { renderMarkdown } from "../../lib/markdown";

const props = defineProps({
  uploadId: { type: String, required: true },
  buildNote: { type: String, default: "" },
});

const emit = defineEmits(["back"]);

const examples = ref([]);
const examplesLoading = ref(false);
const question = ref("");
const asking = ref(false);
const errorText = ref("");
const result = ref(null);
const history = ref([]);
const answerBox = ref(null);

const sources = computed(() => (result.value && result.value.sources) || []);

const answerHtml = computed(() => {
  const text = (result.value && result.value.answer) || "";
  return renderMarkdown(text, {
    cite: (n) =>
      `<button type="button" class="cite" data-cite="${n}" title="跳转到第 ${n} 条来源">[来源${n}]</button>`,
  });
});

const routeMeta = computed(() => {
  const route = (result.value && result.value.route) || "rag";
  const map = {
    rag: { label: "检索问答", cls: "is-primary" },
    chitchat: { label: "闲聊 / 域外", cls: "" },
    error: { label: "检索兜底", cls: "is-warn" },
    llm_error: { label: "模型服务不可用", cls: "is-danger" },
    busy: { label: "数据集忙", cls: "is-warn" },
  };
  return map[route] || { label: String(route).toUpperCase(), cls: "" };
});

const routeHint = computed(() => {
  if (!result.value) return "";
  const route = result.value.route;
  if (route === "error") return "这次没走通检索（数据或索引侧的问题），下面是兜底说明，不是检索出来的结论。";
  if (route === "llm_error") return "检索到的资料没问题，但生成答案的大模型没响应。稍后重问即可，不用重新构建。";
  if (route === "chitchat") return "这句话被判定为闲聊 / 域外，没有去检索你的数据。";
  if (result.value.busy) return "数据集正在重建，本次查询被拒绝——等构建完成后再问。";
  return "";
});

const metaLine = computed(() => {
  const r = result.value;
  if (!r) return "";
  if (r.busy) return "构建进行中 · 本次查询已被拒绝";
  const bits = [];
  bits.push(routeMeta.value.label);
  if (r.cached) bits.push("命中缓存");
  if (typeof r.elapsed_ms === "number") bits.push(`${(r.elapsed_ms / 1000).toFixed(1)} 秒`);
  return bits.join(" · ");
});

const placeholder = computed(() => {
  if (examples.value.length) return `例如：${examples.value[0]}`;
  return "输入一个问题，基于刚构建的数据回答";
});

async function loadExamples() {
  examplesLoading.value = true;
  try {
    const suffix = props.uploadId ? `?upload_id=${encodeURIComponent(props.uploadId)}` : "";
    const data = await getJson(`/api/wizard/examples${suffix}`);
    examples.value = data.questions || [];
  } catch {
    examples.value = [];
  } finally {
    examplesLoading.value = false;
  }
}

function askWith(text) {
  const q = String(text || "").trim();
  if (!q || asking.value) return;
  question.value = q;
  ask(q);
}

async function ask(q) {
  const text = String(q || "").trim();
  if (!text) {
    errorText.value = "先输入一个问题，再点「提问」。";
    return;
  }
  if (asking.value) return;
  asking.value = true;
  errorText.value = "";
  try {
    // 只传 question + upload_id；dataset 由登录账号推导（红线）
    const data = await postJson("/api/wizard/query", {
      question: text,
      upload_id: props.uploadId,
    });
    result.value = data;
    history.value = [
      { question: text, data, time: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) },
      ...history.value,
    ].slice(0, 5);
    await nextTick();
    if (answerBox.value) answerBox.value.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    errorText.value = (e && (e.detail || e.message)) || "提问失败";
  } finally {
    asking.value = false;
  }
}

function onKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    ask(question.value);
  }
}

function onAnswerClick(e) {
  const cite = e.target.closest(".cite");
  if (!cite) return;
  const idx = Number(cite.dataset.cite);
  const node = document.getElementById(`setup-src-${idx}`);
  if (!node) return;
  node.scrollIntoView({ behavior: "smooth", block: "center" });
  node.classList.remove("is-flash");
  void node.offsetWidth;
  node.classList.add("is-flash");
  setTimeout(() => node.classList.remove("is-flash"), 1500);
}

function loadHistory(item) {
  result.value = item.data;
  question.value = item.question;
}

function clearHistory() {
  history.value = [];
}

watch(
  () => props.uploadId,
  () => loadExamples()
);

onMounted(loadExamples);
</script>

<template>
  <section class="step-card">
    <div class="step-head">
      <div>
        <div class="step-kicker">第 4 步 · 提问验证</div>
        <h3 class="step-title">用刚构建的数据当场问一句</h3>
        <p class="step-desc">
          这里是简化版问答：只查本次上传构建出来的数据，用来验证"数据 + 文档"是否真的能被答出来。
          完整的多轮对话、检索过程与权限视图在对话页。
        </p>
      </div>
      <RouterLink to="/chat" class="btn btn-ghost btn-sm">去完整对话页 →</RouterLink>
    </div>

    <div v-if="buildNote" class="alert is-info">{{ buildNote }}</div>

    <div class="ask-examples">
      <span class="ask-examples-label">示例问句</span>
      <template v-if="examplesLoading">
        <span class="skeleton" style="height: 28px; width: 180px; border-radius: 999px" />
        <span class="skeleton" style="height: 28px; width: 140px; border-radius: 999px" />
      </template>
      <template v-else-if="examples.length">
        <button
          v-for="q in examples"
          :key="q"
          type="button"
          class="chip"
          :disabled="asking"
          @click="askWith(q)"
        >
          {{ q }}
        </button>
      </template>
      <span v-else class="field-hint">暂无示例（由服务端按已确认字段动态生成）</span>
    </div>

    <div class="ask-composer">
      <textarea
        v-model="question"
        class="textarea ask-textarea"
        maxlength="200"
        :placeholder="placeholder"
        :disabled="asking"
        @keydown="onKeydown"
      />
      <div class="ask-composer-foot">
        <span class="field-hint">
          <kbd class="kbd">Ctrl</kbd> / <kbd class="kbd">Cmd</kbd> + <kbd class="kbd">Enter</kbd> 发送 ·
          {{ question.length }}/200
        </span>
        <span class="spacer" />
        <button type="button" class="btn btn-primary" :disabled="asking || !question.trim()" @click="ask(question)">
          <span v-if="asking" class="spinner spinner-sm" />
          {{ asking ? "检索并生成中…" : "提问" }}
        </button>
      </div>
      <p v-if="asking" class="field-hint">
        正在检索并生成答案（约 10~25 秒）…真实问答要跑检索、精排与生成，慢是正常的。
      </p>
    </div>

    <div v-if="errorText" class="alert is-error">{{ errorText }}</div>

    <div v-if="result" ref="answerBox" class="ask-result">
      <div class="ask-result-head">
        <span class="badge" :class="routeMeta.cls">{{ routeMeta.label }}</span>
        <span v-if="result.busy" class="badge is-warn">构建中</span>
        <span v-else-if="result.cached" class="badge is-warn">缓存命中</span>
        <span class="field-hint">{{ metaLine }}</span>
        <span class="spacer" />
        <span v-if="result.dataset" class="field-hint" title="本次查询的数据空间由登录账号推导">
          数据空间：{{ result.dataset }}
        </span>
      </div>

      <div v-if="routeHint" class="alert" :class="result.route === 'llm_error' || result.route === 'error' ? 'is-warn' : 'is-info'">
        {{ routeHint }}
      </div>

      <div class="answer-body ask-answer" @click="onAnswerClick" v-html="answerHtml" />

      <div v-if="sources.length" class="ask-sources">
        <div class="detail-section-title">数据来源 <span class="count">共 {{ sources.length }} 条</span></div>
        <div v-for="(s, i) in sources" :id="`setup-src-${i + 1}`" :key="i" class="source-item">
          <div class="source-head">
            <span class="source-index">[来源{{ i + 1 }}]</span>
            <span class="source-name">{{ s.source || "未知来源" }}</span>
          </div>
          <div v-if="s.text" class="source-text">{{ s.text }}</div>
        </div>
      </div>
    </div>

    <div v-if="history.length" class="ask-history">
      <div class="ask-history-head">
        <b>本次提问记录</b>
        <button type="button" class="btn btn-sm btn-ghost" @click="clearHistory">清空</button>
      </div>
      <div class="ask-history-list">
        <button
          v-for="(h, i) in history"
          :key="i"
          type="button"
          class="ask-history-item"
          :title="h.question"
          @click="loadHistory(h)"
        >
          <span class="ask-history-q">{{ h.question }}</span>
          <span class="ask-history-time">{{ h.time }}</span>
        </button>
      </div>
    </div>

    <div class="step-footer">
      <button type="button" class="btn btn-ghost" @click="$emit('back')">← 上一步：构建</button>
      <span class="spacer" />
      <RouterLink to="/chat" class="btn btn-primary">去完整对话页 →</RouterLink>
    </div>
  </section>
</template>
