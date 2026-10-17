/**
 * 规则文档模板（纯前端 Blob 下载）
 *
 * 文本沿用老向导 static/wizard.js 的 DOC_TEMPLATE：它已经在真实数据上验证过
 * 标题层级与切分口径，搬过来即可，不在 Vue 版另写一份会被改漏的副本。
 */
export const DOC_TEMPLATE = `# 标签定义

> 说明：一个 # 是一级标题，## 是二级标题，### 是三级标题。
> 系统按标题切分文档，标题写得越清楚，答案引用得越准。

## 高价值客户

判定条件：近 90 天下单 ≥ 3 次，且客单价 ≥ 500 元。

### 与会员等级的区别

会员等级按成长值划分，与本标签不互为充分条件。

## 流失预警

判定条件：近 60 天无下单，且历史下单次数 ≥ 2 次。

## 沉睡用户

判定条件：近 180 天无下单、无登录行为。
`;

export function downloadDocTemplate() {
  const blob = new Blob([DOC_TEMPLATE], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "规则文档模板.md";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // 立刻 revoke 在部分浏览器会打断下载，延后一拍即可
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
