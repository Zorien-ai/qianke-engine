/**
 * 向导本地缓存与「给人看的状态文案」。
 *
 * 第三轮修复把 localStorage key 集中在这里，避免 Setup / StepBuild 各写一份字面量。
 * 文案降维：技术值（fresh / stale / unknown）只放在 title 里，正文一律人话。
 */

export const UPLOAD_KEY = "v2-wizard-upload-id";
export const BUILD_TASK_KEY = "v2-wizard-build-task-id";

const FRESHNESS_TEXT = {
  fresh: "已就绪，可随时提问",
  stale: "数据有更新，请重新构建",
  unknown: "尚未构建，建议先构建一次",
};

// 状态说明（正文第二行）：仍然不允许技术词——「索引与源表一致」这种话老板看不懂。
const FRESHNESS_REASON = {
  fresh: "数据与检索索引一致，可以直接提问",
  stale: "源数据有变化，索引还是旧的，请重新构建后再提问",
  unknown: "还没有可用的构建记录",
};

/** 数据状态 → 人话（未知值按"尚未构建"处理，技术值不放正文） */
export function freshnessText(status) {
  return FRESHNESS_TEXT[status] || FRESHNESS_TEXT.unknown;
}

/** 数据状态的补充说明 → 人话（后端 reason 是技术口径，展示前降维） */
export function freshnessReason(status, fallback = "") {
  return FRESHNESS_REASON[status] || String(fallback || "");
}

export function readUploadId() {
  try {
    return localStorage.getItem(UPLOAD_KEY) || "";
  } catch {
    return "";
  }
}

export function writeUploadId(uploadId) {
  try {
    if (uploadId) localStorage.setItem(UPLOAD_KEY, uploadId);
    else localStorage.removeItem(UPLOAD_KEY);
  } catch {
    /* 隐私模式写不了，忽略 */
  }
}

export function readBuildTaskId() {
  try {
    return localStorage.getItem(BUILD_TASK_KEY) || "";
  } catch {
    return "";
  }
}

export function writeBuildTaskId(taskId) {
  try {
    if (taskId) localStorage.setItem(BUILD_TASK_KEY, taskId);
    else localStorage.removeItem(BUILD_TASK_KEY);
  } catch {
    /* 忽略 */
  }
}

export function clearBuildTaskId() {
  writeBuildTaskId("");
}

/**
 * 后端 note 里可能仍带「索引新鲜度 fresh」这类技术词：展示前做一次降维。
 * 只动展示文案，不改服务端返回的数据本身。
 */
export function humanizeStatusText(text) {
  let out = String(text || "");
  out = out.replace(/(?:索引新鲜度|数据状态)\s*[:：]?\s*(fresh|stale|unknown)/gi, (m, status) => {
    return `数据状态：${freshnessText(String(status).toLowerCase())}`;
  });
  out = out.replace(/索引新鲜度/g, "数据状态");
  return out;
}
