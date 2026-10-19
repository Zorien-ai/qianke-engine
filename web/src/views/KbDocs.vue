<script setup>
/**
 * 文档管理子页面：文档矩阵 + 原文/切片双 Tab 阅读器。
 */
import DocumentReader from "../components/kb/DocumentReader.vue";
</script>

<template>
  <div class="page kb-subpage">
    <div class="kb-subhead">
      <div>
        <RouterLink to="/kb" class="kb-back">← 知识库概况</RouterLink>
        <h2>文档管理</h2>
        <p class="card-sub">
          查看每篇文档的切片规模；点击任意文档，可切换「原文阅读」与「RAG 切片」两种视图。
        </p>
      </div>
      <div class="row-actions">
        <RouterLink class="btn btn-ghost" to="/kb/profiles">查看画像</RouterLink>
      </div>
    </div>
    <DocumentReader />
  </div>
</template>

<style scoped>
.kb-subpage { max-width: 1500px; }
.kb-subhead {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.kb-back {
  display: inline-block;
  margin-bottom: 8px;
  color: var(--primary);
  text-decoration: none;
  font-size: 12px;
}
.kb-back:hover { text-decoration: underline; }
.kb-subhead h2 { margin: 0; font-size: 22px; }
.kb-subhead .card-sub { margin: 7px 0 0; max-width: 760px; }
</style>
