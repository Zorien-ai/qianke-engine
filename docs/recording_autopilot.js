/*
 * 千客引擎 · 录屏 Auto-Pilot（控制台版）
 * ------------------------------------------------------------------
 * 用法：登录 admin → 打开 /v2/#/setup → F12 Console → 粘贴本文件 → 回车
 *
 *   await qkPilot.setupSample()  // 示例数据 → 确认字段 → 全量构建（首次）
 *   await qkPilot.ask()          // 对话页输入问题 → 提问 → 展开数据来源
 *   await qkPilot.kb()           // 知识库页刷新
 *   await qkPilot.run()          // 串起来跑（构建最长等 15 分钟）
 *
 * 注意：
 * - 这是“排练/对时”工具，不修改任何源码，也不写数据库之外的业务数据；
 * - 它用按钮「用示例数据填满」，不替代系统文件选择器（所以不能自动拖真实 CSV）；
 * - 它默认执行「覆盖重建」以得到可重复的首次构建；增量演示请手动上传新 CSV；
 * - 运行期间不要手动点页面；出问题刷新页面重来即可。
 */
(() => {
  const QUESTION = "最近一次购买超过30天的美妆高客单女性用户有哪些？给一个挽回方案。";
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const buttons = () => Array.from(document.querySelectorAll("button"));
  const findButton = (re) => buttons().find((b) => re.test((b.textContent || "").trim()));
  const bodyText = () => document.body.innerText || "";
  const log = (...args) => console.log("%c[千客演示]", "color:#f2a45c;font-weight:700", ...args);

  async function waitFor(predicate, label, timeout = 20000, interval = 300) {
    const started = Date.now();
    while (Date.now() - started < timeout) {
      try {
        const value = predicate();
        if (value) return value;
      } catch (_) {
        /* 页面切换中忽略 */
      }
      await sleep(interval);
    }
    throw new Error(`等待超时：${label}`);
  }

  async function clickButton(re, label, timeout = 20000) {
    const button = await waitFor(() => findButton(re), label, timeout);
    if (button.disabled) throw new Error(`按钮不可用：${label}`);
    button.click();
    log("点击", label);
    return button;
  }

  async function go(hash) {
    if (location.hash !== hash) {
      location.hash = hash;
      await sleep(500);
    }
    await waitFor(() => document.querySelector(".app-shell") || document.querySelector(".landing"), "页面外壳");
  }

  function setTextarea(el, value) {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  async function setupSample() {
    log("开始 setup：示例数据 → 确认字段 → 覆盖重建");
    await go("#/setup");
    await waitFor(() => findButton(/用示例数据填满/), "上传页");
    if (bodyText().includes("正在恢复上次的上传批次")) {
      await waitFor(() => !bodyText().includes("正在恢复上次的上传批次"), "恢复上传", 30000);
    }

    // 如果当前上传批次已有文件，示例按钮仍会创建新批次；录屏建议先清空/刷新到干净状态
    await clickButton(/用示例数据填满/, "用示例数据填满", 30000);
    await waitFor(() => !bodyText().includes("正在填充示例数据"), "示例数据填充", 120000);
    await sleep(1200);

    await clickButton(/下一步：确认字段/, "下一步：确认字段", 30000);
    await waitFor(() => findButton(/下一步：开始构建/), "字段映射页", 30000);
    await sleep(700);
    await clickButton(/下一步：开始构建/, "下一步：开始构建", 30000);

    await waitFor(() => findButton(/开始构建|重新构建/), "构建页", 30000);
    await sleep(800);

    // 首次构建没有基线：选择「覆盖重建」，避免依赖增量预检
    const modeCards = Array.from(document.querySelectorAll("button.mode-card"));
    if (modeCards.length >= 2) {
      modeCards[1].click();
      log("选择 覆盖重建");
      await sleep(300);
    }
    await clickButton(/^开始构建$|^重新构建$/, "开始构建", 30000);
    await sleep(500);
    const confirm = findButton(/确认覆盖重建/);
    if (confirm) {
      confirm.click();
      log("确认覆盖重建");
    }

    log("构建已启动，等待完成（最长 15 分钟）…");
    const started = Date.now();
    let lastPercent = -1;
    await waitFor(
      () => {
        const btn = findButton(/下一步：提问验证/);
        const percentMatch = bodyText().match(/(\d{1,3})%/);
        const percent = percentMatch ? Number(percentMatch[1]) : -1;
        if (percent !== lastPercent && percent >= 0) {
          lastPercent = percent;
          log("构建进度", `${percent}%`);
        }
        return btn && !btn.disabled;
      },
      "构建完成",
      900000,
      1000,
    );
    log("构建完成，用时", `${Math.round((Date.now() - started) / 1000)}s`);
    return true;
  }

  async function ask(question = QUESTION) {
    log("开始对话：", question);
    await go("#/chat");
    const textarea = await waitFor(() => document.querySelector("textarea"), "对话输入框", 20000);
    setTextarea(textarea, question);
    await sleep(400);
    await clickButton(/^提问$/, "提问", 20000);

    await waitFor(
      () => document.querySelector(".detail-panel") && !document.querySelector(".answer-body.is-streaming"),
      "回答结束",
      180000,
      500,
    );
    log("回答结束，展开来源");
    const expand = findButton(/展开过程/);
    if (expand) {
      expand.click();
      log("已展开数据来源");
    } else {
      log("未找到「展开过程」按钮（可能当前等级看不到来源）");
    }
    return true;
  }

  async function kb() {
    log("打开知识库");
    await go("#/kb");
    await waitFor(() => bodyText().includes("知识库概况"), "知识库页", 20000);
    const refresh = findButton(/刷新/);
    if (refresh) {
      refresh.click();
      log("已点击刷新");
    }
    await sleep(1200);
    return true;
  }

  async function run() {
    await setupSample();
    await ask();
    await kb();
    log("Auto-Pilot 完成。可以开始正式录屏（本脚本不录制，只驱动页面）");
  }

  window.qkPilot = { setupSample, ask, kb, run, QUESTION, sleep };
  log("已就绪：qkPilot.setupSample() / qkPilot.ask() / qkPilot.kb() / qkPilot.run()");
})();
