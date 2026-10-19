<script setup>
/**
 * 画像浏览子页面：独占整屏宽度展示卡牌墙。
 */
import ProfileWall from "../components/kb/ProfileWall.vue";
</script>

<template>
  <div class="page kb-subpage">
    <div class="kb-subhead">
      <div>
        <RouterLink to="/kb" class="kb-back">← 知识库概况</RouterLink>
        <h2>用户画像浏览</h2>
        <p class="card-sub">
          当前数据空间的结构化用户画像。卡片字段只读，姓名已由后端脱敏；每页 20 位。
        </p>
      </div>
      <div class="row-actions">
        <RouterLink class="btn btn-ghost" to="/kb/docs">查看文档池</RouterLink>
      </div>
    </div>
    <ProfileWall />
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
.kb-subhead .card-sub { margin: 7px 0 0; max-width: 720px; }
</style>
