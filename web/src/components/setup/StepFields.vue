<script setup>
/**
 * 第 2 步：确认字段映射。
 *
 * 字段识别、文档结构、预估分块全部来自上传接口返回的 state（服务端算好的），
 * 这里只负责让用户确认 / 手动改选。关键字段（user_id）未映射时不允许进入构建，
 * 并直接说清"没有它会怎样"——不做"点了才发现"的交互。
 */
import { computed } from "vue";

const props = defineProps({
  analysis: { type: Object, required: true },
  fields: { type: Object, required: true },
});

const emit = defineEmits(["update", "back", "next"]);

const summary = computed(() => props.analysis.summary || {});
const fieldList = computed(() => props.analysis.fields || []);
const docs = computed(() => props.analysis.docs || []);
const warnings = computed(() => props.analysis.warnings || []);
const hasCsv = computed(() => Number(summary.value.csv_count) > 0);
const detectedCount = computed(() => fieldList.value.filter((f) => f.detected).length);

const missingRequired = computed(() =>
  fieldList.value.filter((f) => f.required && !props.fields[f.key])
);

const canNext = computed(() => !hasCsv.value || missingRequired.value.length === 0);

const nextHint = computed(() => {
  if (!hasCsv.value) return "本次没有交易数据：将只构建文档问答，不生成用户画像。";
  if (missingRequired.value.length) {
    const names = missingRequired.value.map((f) => `「${f.label}」`).join("、");
    return `${names}是关键字段，未映射时无法把订单聚合到人身上。`;
  }
  return "字段确认后即可进入构建。";
});

const levelNote = computed(() => {
  const level = props.fields.member_level;
  const amount = props.fields.amount;
  if (level) {
    return { kind: "info", text: `会员等级将使用你映射的「${level}」列，系统不再自动推导。` };
  }
  if (amount) {
    return {
      kind: "warn",
      text: "没有映射会员等级列：将按消费金额自动推导（相对分位，等级名只代表相对位置）。建议映射到你自己的等级列。",
    };
  }
  return null;
});

function statusOf(f) {
  if (props.fields[f.key]) return f.detected ? "已自动识别" : "已手动指定";
  return f.required ? "关键字段未映射" : "未映射";
}

function statusClass(f) {
  if (!props.fields[f.key]) return f.required ? "is-error" : "is-muted";
  return f.detected ? "is-ok" : "is-manual";
}

function onSelect(f, event) {
  emit("update", f.key, event.target.value);
}
</script>

<template>
  <section class="step-card">
    <div class="step-head">
      <div>
        <div class="step-kicker">第 2 步 · 确认字段</div>
        <h3 class="step-title">把系统字段对应到你的数据列</h3>
        <p class="step-desc">
          系统已经按列名词典自动识别。识别不对的可以手动改选；没有的字段保持「不使用」即可，
          标了「关键」的字段必须映射。
        </p>
      </div>
      <div class="step-head-badge">
        已识别 <b>{{ detectedCount }}/{{ fieldList.length }}</b>
      </div>
    </div>

    <div class="summary-row">
      <span class="summary-chip"><b>{{ summary.csv_count }}</b> 个数据文件</span>
      <span class="summary-chip"><b>{{ summary.md_count }}</b> 篇规则文档</span>
      <span class="summary-chip"><b>{{ Number(summary.total_rows || 0).toLocaleString() }}</b> 行交易记录</span>
      <span class="summary-chip"><b>{{ summary.total_chunks }}</b> 个预计分块</span>
    </div>

    <div class="field-map">
      <div class="field-row is-head">
        <span>系统字段</span>
        <span>对应的数据列</span>
        <span>状态</span>
      </div>
      <div v-for="f in fieldList" :key="f.key" class="field-row" :class="{ 'is-missing': !fields[f.key] && f.required }">
        <div class="field-label">
          <span class="field-name">
            {{ f.label }}
            <span v-if="f.required" class="req-badge">关键</span>
          </span>
          <span class="field-hint">{{ f.hint }}</span>
        </div>
        <div class="field-select-wrap">
          <select
            class="select field-select"
            :value="fields[f.key] || ''"
            :aria-label="`${f.label} 对应的数据列`"
            @change="onSelect(f, $event)"
          >
            <option value="">（不使用这个字段）</option>
            <option v-for="c in f.options || []" :key="c" :value="c">{{ c }}</option>
          </select>
          <span v-if="fields[f.key] && f.from_file" class="field-from" :title="f.from_file">
            来自 {{ f.from_file }}
          </span>
        </div>
        <div class="field-status" :class="statusClass(f)">{{ statusOf(f) }}</div>
      </div>
      <div v-if="!hasCsv" class="field-row is-empty">
        没有交易数据，所以没有列可映射。文档问答不需要字段映射，可以直接进入构建。
      </div>
    </div>

    <div v-if="levelNote" class="alert" :class="`is-${levelNote.kind}`">
      {{ levelNote.text }}
    </div>

    <div v-if="warnings.length" class="warn-box">
      <div class="warn-title">上传分析提示</div>
      <div v-for="(w, i) in warnings" :key="i" class="warn-item">
        <span class="warn-mark">!</span>
        <span>{{ w }}</span>
      </div>
    </div>

    <div class="docs-block">
      <div class="docs-head">
        <b>规则文档结构</b>
        <span class="field-hint">标题层级用于切分与定位；预计分块由真实切分器计算</span>
      </div>
      <div v-if="docs.length" class="doc-list">
        <div v-for="d in docs" :key="d.name" class="doc-item" :class="{ 'is-warn': d.warning }">
          <span class="doc-name" :title="d.name">{{ d.name }}</span>
          <span class="doc-headings">
            <span class="htag" :class="{ 'is-zero': !d.h1 }">一级 {{ d.h1 }}</span>
            <span class="htag" :class="{ 'is-zero': !d.h2 }">二级 {{ d.h2 }}</span>
            <span class="htag" :class="{ 'is-zero': !d.h3 }">三级 {{ d.h3 }}</span>
          </span>
          <span class="doc-chunks">{{ d.est_chunks }} 块</span>
          <span class="doc-chars">{{ Number(d.chars || 0).toLocaleString() }} 字</span>
        </div>
      </div>
      <div v-else class="file-empty">
        没有上传规则文档——本次构建后只能做数据类问答。可以回到上一步补充 .md 文档。
      </div>
    </div>

    <div class="step-footer">
      <button type="button" class="btn btn-ghost" @click="$emit('back')">← 上一步</button>
      <span class="spacer" />
      <span class="field-hint" :class="{ 'is-error-text': !canNext }">{{ nextHint }}</span>
      <button type="button" class="btn btn-primary" :disabled="!canNext" @click="$emit('next')">
        下一步：开始构建 →
      </button>
    </div>
  </section>
</template>
