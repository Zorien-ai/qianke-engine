<script setup>
/**
 * 工作台：/whoami 账号与能力 + /stats 数据概况（can.stats 才有）+ 数据空间 + 快捷入口。
 * 所有数字都来自接口，页面上没有写死的业务事实。
 */
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api";
import { hasCap, isManager, store, toastError } from "../store";

const stats = ref(null);
const statsLoading = ref(false);
const statsError = ref("");
const overview = ref(null);
const overviewError = ref("");

const account = computed(() => store.account || {});
const welcome = computed(() => {
  const name = account.value.display_name || account.value.username || "你好";
  const hour = new Date().getHours();
  const prefix = hour < 6 ? "夜深了" : hour < 12 ? "早上好" : hour < 18 ? "下午好" : "晚上好";
  return `${prefix}，${name}`;
});
const enterprise = computed(() => {
  const ent = account.value.enterprise;
  if (ent) return ent.name;
  return account.value.is_system_admin ? "平台方（系统管理员）" : "未绑定企业";
});
const dataset = computed(() => {
  const ent = account.value.enterprise;
  if (ent && ent.dataset) return ent.dataset;
  return account.value.is_system_admin ? "demo（演示数据集）" : "（未开通）";
});

const capKeys = [
  ["ask", "回答"],
  ["sources", "来源列表"],
  ["topk", "返回用户数"],
  ["internals", "检索过程"],
  ["trace_flow", "融合与精排"],
  ["sql", "SQL 原文"],
  ["stats", "数据概况"],
  ["raw_search", "召回对比"],
  ["ops", "运维 / 权限"],
  ["tenant", "成员管理"],
];
const caps = computed(() => capKeys.map(([key, label]) => ({ key, label, on: hasCap(key) })));

const statCards = computed(() => {
  if (!stats.value) return [];
  const s = stats.value;
  const levels = s.member_levels || {};
  const top = Object.entries(levels)[0];
  const ratio = top ? (s.level_ratio || {})[top[0]] : null;
  return [
    {
      value: Number(s.users || 0).toLocaleString(),
      label: "用户画像",
      extra: `结构化字段 ${s.profiles_columns ?? "-"} 个`,
    },
    {
      value: Number(s.chunks || 0).toLocaleString(),
      label: "知识库切片",
      extra: `来自 ${s.docs ?? "-"} 篇文档`,
    },
    {
      value: Number(s.cities || 0).toLocaleString(),
      label: "覆盖城市",
      extra: `商品品类 ${s.categories ?? "-"} 类`,
    },
    {
      value: ratio || "—",
      label: top ? `${top[0]}占比` : "会员等级占比",
      extra: top ? `${top[0]} ${top[1]} 人` : "暂无等级分布",
    },
  ];
});

const levelRows = computed(() => {
  const s = stats.value;
  if (!s) return [];
  const levels = s.member_levels || {};
  const total = Number(s.users || 0) || 1;
  return Object.entries(levels).map(([name, count]) => ({
    name,
    count,
    pct: Math.round((Number(count) / total) * 1000) / 10,
  }));
});

const quickLinks = computed(() => {
  const links = [
    {
      title: "开始提问",
      desc: "基于企业知识库与用户画像问答",
      icon: "💬",
      to: "/chat",
    },
    {
      title: "知识库",
      desc: "概况、文档矩阵、重建与清空",
      icon: "📚",
      to: "/kb",
    },
  ];
  if (isManager()) {
    links.push({
      title: "数据导入",
      desc: "上传 CSV / 文档并构建索引",
      icon: "📥",
      to: "/setup",
    });
  }
  if (isManager()) {
    links.push({
      title: "员工管理",
      desc: "审核成员、改角色、邀请码",
      icon: "🧑‍💼",
      to: "/staff",
    });
  }
  if (hasCap("ops")) {
    links.push({
      title: "权限配置",
      desc: "等级 × 能力矩阵与角色默认等级",
      icon: "⚙️",
      to: "/settings",
    });
  }
  return links;
});

const quickCapHint = computed(() => {
  if (hasCap("ask")) return "";
  if (account.value.status === "rejected")
    return "注册申请未通过审核，请联系管理员；通过后即可提问。";
  if (account.value.status && account.value.status !== "active")
    return `账号${account.value.status_label || "待审核"}：审核通过后即可提问。`;
  return "当前账号没有提问能力，请联系企业管理员调整等级。";
});

const freshness = computed(() => {
  const f = (overview.value && overview.value.freshness) || null;
  if (!f) return { status: "unknown", label: "未知", reason: "暂无新鲜度数据", cls: "is-unknown", pct: 0 };
  const map = {
    fresh: { label: "索引新鲜", cls: "is-fresh", pct: 100 },
    stale: { label: "索引已过期", cls: "is-warn", pct: 55 },
    unknown: { label: "无基线", cls: "is-unknown", pct: 12 },
  };
  const m = map[f.status] || map.unknown;
  return { status: f.status, ...m, reason: f.reason || "" };
});

const modeLabel = computed(() => {
  const mode = overview.value && overview.value.mode;
  if (mode === "demo") return "演示数据集（只读）";
  if (mode === "enterprise") return "企业数据空间";
  return "—";
});

onMounted(async () => {
  if (hasCap("stats")) {
    statsLoading.value = true;
    try {
      stats.value = await getJson("/stats");
    } catch (e) {
      statsError.value = e.detail || e.message || "数据概况加载失败";
    } finally {
      statsLoading.value = false;
    }
  }
  try {
    overview.value = await getJson("/api/kb/overview");
  } catch (e) {
    overviewError.value = e.detail || e.message || "知识库概况加载失败";
  }
});
</script>

<template>
  <div class="page">
    <section class="hero">
      <div class="hero-top">
        <div>
          <h2 class="hero-greet">
            {{ welcome }}，<span class="grad-text">今天想了解什么？</span>
          </h2>
          <p class="hero-sub">
            当前以 <b>{{ store.roleLabel || "未知角色" }}</b> 身份登录（{{ enterprise }}），
            可用等级 <b>{{ store.levelLabel || "—" }}</b>。能看到的范围由账号等级决定，
            页面只渲染你被允许使用的能力。
          </p>
          <div class="hero-meta">
            <span v-for="c in caps" :key="c.key" class="cap-chip" :class="c.on ? 'is-on' : 'is-off'">
              {{ c.on ? "可用" : "未开通" }} · {{ c.label }}
            </span>
          </div>
        </div>
        <div class="row-actions">
          <RouterLink v-if="hasCap('ask')" to="/chat" class="btn btn-primary">开始提问</RouterLink>
          <RouterLink v-if="isManager()" to="/setup" class="btn btn-ghost">数据导入</RouterLink>
        </div>
      </div>
      <p v-if="quickCapHint" class="alert is-warn" style="margin-top: 16px">
        {{ quickCapHint }}
      </p>
    </section>

    <!-- 数据概况：仅 can.stats（默认 L4 / 系统管理员） -->
    <template v-if="hasCap('stats')">
      <div v-if="statsLoading" class="stat-grid">
        <div v-for="i in 4" :key="i" class="stat-card">
          <div class="skeleton" style="height: 34px; width: 60%"></div>
          <div class="skeleton" style="height: 12px; width: 40%; margin-top: 10px"></div>
        </div>
      </div>
      <div v-else-if="statsError" class="alert is-error" style="margin-bottom: 20px">
        <div>
          <strong>数据概况加载失败：</strong>{{ statsError }}
        </div>
      </div>
      <div v-else class="stat-grid">
        <div v-for="card in statCards" :key="card.label" class="stat-card">
          <div class="stat-value">{{ card.value }}</div>
          <div class="stat-label">{{ card.label }}</div>
          <div class="stat-extra">{{ card.extra }}</div>
        </div>
      </div>
    </template>
    <div v-else class="alert is-info" style="margin-bottom: 20px">
      当前等级看不到 /stats 数据概况（需要「数据概况」能力）。这是权限裁剪，不是数据为空。
    </div>

    <div class="two-col">
      <!-- 我的数据空间 -->
      <section class="card">
        <div class="card-title">
          <span class="dot"></span>我的数据空间
          <span class="spacer"></span>
          <RouterLink to="/kb" class="btn btn-sm btn-ghost">查看知识库</RouterLink>
        </div>

        <div v-if="overviewError" class="alert is-info">
          知识库概况暂不可用：{{ overviewError }}
        </div>
        <template v-else-if="!overview">
          <div class="skeleton" style="height: 120px"></div>
        </template>
        <template v-else>
          <div class="meta-list">
            <div class="meta-row">
              <dt>数据集</dt>
              <dd><span class="kb-dataset">{{ overview.dataset }}</span></dd>
            </div>
            <div class="meta-row">
              <dt>空间类型</dt>
              <dd>{{ modeLabel }}</dd>
            </div>
            <div class="meta-row">
              <dt>文档 / 切片 / 画像</dt>
              <dd>
                <template v-if="overview.ready">
                  {{ overview.totals?.docs ?? 0 }} 篇 ·
                  {{ overview.totals?.chunks ?? 0 }} 切片 ·
                  {{ overview.totals?.profiles ?? 0 }} 画像
                </template>
                <template v-else>尚未构建</template>
              </dd>
            </div>
            <div class="meta-row">
              <dt>最近构建</dt>
              <dd>{{ overview.built_at || "—" }}</dd>
            </div>
            <div class="meta-row">
              <dt>索引新鲜度</dt>
              <dd>
                <span class="status-dot" :class="freshness.cls"></span>
                {{ freshness.label }}
              </dd>
            </div>
            <div class="meta-row" v-if="overview.readonly_reason">
              <dt>只读说明</dt>
              <dd>{{ overview.readonly_reason }}</dd>
            </div>
          </div>
          <div class="progress" style="margin-top: 14px" :class="{ 'is-success': freshness.status === 'fresh', 'is-warn': freshness.status === 'stale', 'is-muted': freshness.status === 'unknown' }">
            <div class="progress-fill" :style="{ width: `${freshness.pct}%` }"></div>
          </div>
          <p class="card-sub" style="margin-top: 7px">{{ freshness.reason }}</p>

          <div v-if="!overview.ready" class="alert is-warn" style="margin-top: 14px">
            数据空间还没构建。去
            <RouterLink to="/setup">数据导入向导</RouterLink>
            上传数据并完成构建后，这里才会有内容。
          </div>
        </template>
      </section>

      <!-- 等级分布 / 能力说明 -->
      <section class="card">
        <div class="card-title"><span class="dot"></span>会员等级分布</div>
        <template v-if="hasCap('stats')">
          <div v-if="levelRows.length" class="level-bars">
            <div v-for="row in levelRows" :key="row.name" class="level-bar-row">
              <span class="level-bar-name" :title="row.name">{{ row.name }}</span>
              <div class="progress">
                <div class="progress-fill" :style="{ width: `${row.pct}%` }"></div>
              </div>
              <span class="level-bar-value">{{ row.count }} 人</span>
            </div>
          </div>
          <div v-else-if="stats" class="empty-state" style="padding: 24px 8px">
            <div class="empty-desc">当前数据集没有会员等级分布（member_level 列可能为空）。</div>
          </div>
          <div v-else class="skeleton" style="height: 120px"></div>
        </template>
        <div v-else class="empty-state" style="padding: 24px 8px">
          <div class="empty-emoji">🔒</div>
          <div class="empty-title">数据概况不可见</div>
          <div class="empty-desc">
            该区域展示会员等级分布，属于「数据概况」能力（默认仅 L4 可见）。
            <RouterLink to="/settings" v-if="hasCap('ops')">去权限配置</RouterLink>
          </div>
        </div>
      </section>
    </div>

    <section class="card">
      <div class="card-title"><span class="dot"></span>快捷入口</div>
      <div class="quick-grid">
        <template v-for="item in quickLinks" :key="item.title">
          <RouterLink v-if="item.to" :to="item.to" class="quick-card">
            <span class="quick-icon">{{ item.icon }}</span>
            <span>
              <span class="quick-title">{{ item.title }}</span>
              <span class="quick-desc" style="display: block">{{ item.desc }}</span>
            </span>
          </RouterLink>
          <a v-else :href="item.href" class="quick-card">
            <span class="quick-icon">{{ item.icon }}</span>
            <span>
              <span class="quick-title">{{ item.title }}</span>
              <span class="quick-desc" style="display: block">{{ item.desc }}</span>
            </span>
          </a>
        </template>
      </div>
      <p v-if="store.notes" class="card-sub" style="margin-top: 16px; border-top: 1px solid var(--border); padding-top: 12px">
        {{ store.notes }}
      </p>
    </section>
  </div>
</template>
