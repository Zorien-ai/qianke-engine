/**
 * 轻量 Markdown 渲染（无第三方依赖，逻辑移植自既有 static/markdown.js）。
 *
 * 为什么不用 marked / markdown-it：这是演示系统，依赖越少越好；
 * 回答语法是可控的（标题 / 列表 / 表格 / 代码 / 引用 / 粗斜体 / 行内代码 / 链接），
 * 前端已有实现经过验证，直接以 ES module 形式复用。
 *
 * 安全：先整体做 HTML 转义，再做结构替换，不直通原始 HTML。
 * 流式容错：未闭合的 **粗体** 不匹配；未闭合 ``` 代码块按"到结尾"处理。
 *
 * [来源N] 引用由调用方通过 opts.cite(n) 决定渲染成什么：
 *   返回字符串 → 渲染该 HTML；返回 null → 直接删掉（看不到来源列表的身份）。
 */

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ESC[c]);

const RE_FENCE = /^\s*```([\w+-]*)\s*$/;
const RE_HEADING = /^(#{1,6})\s+(.*)$/;
const RE_HR = /^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/;
const RE_QUOTE = /^\s*>\s?/;
const RE_LIST = /^(\s*)([-*+]|\d+\.)\s+(.*)$/;
const RE_TABLE_SEP = /^\s*\|?[\s:|-]+\|[\s:|-]*$/;

function inline(src, opts) {
  const codes = [];
  let out = esc(src);

  // 行内代码先抽出来：里面的 ** 不该被当加粗
  out = out.replace(/`([^`\n]+)`/g, (m, code) => {
    codes.push(`<code>${code}</code>`);
    return `\u0000${codes.length - 1}\u0000`;
  });

  // 链接只放行 http(s)，避免 javascript:
  out = out.replace(
    /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (m, text, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`
  );

  out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
  out = out.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  out = out.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");

  if (opts.cite) {
    out = out.replace(/\[来源\s*(\d+)\]/g, (m, n) => {
      const html = opts.cite(Number(n));
      return html == null ? "" : html;
    });
  }

  return out.replace(/\u0000(\d+)\u0000/g, (m, i) => codes[Number(i)]);
}

function parseTable(lines, start, opts) {
  const cells = (row) =>
    row.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());

  const head = cells(lines[start]);
  const aligns = cells(lines[start + 1]).map((c) => {
    if (/^:-+:$/.test(c)) return "center";
    if (/^-+:$/.test(c)) return "right";
    if (/^:-+$/.test(c)) return "left";
    return "";
  });

  let i = start + 2;
  const rows = [];
  while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
    rows.push(cells(lines[i]));
    i++;
  }

  const style = (k) => (aligns[k] ? ` style="text-align:${aligns[k]}"` : "");
  const thead =
    "<tr>" + head.map((c, k) => `<th${style(k)}>${inline(c, opts)}</th>`).join("") + "</tr>";
  const tbody = rows
    .map(
      (r) =>
        "<tr>" +
        head.map((_, k) => `<td${style(k)}>${inline(r[k] || "", opts)}</td>`).join("") +
        "</tr>"
    )
    .join("");

  return [
    `<div class="md-table-wrap"><table><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`,
    i,
  ];
}

function parseList(lines, start, opts) {
  const first = lines[start].match(RE_LIST);
  const baseIndent = first[1].length;
  const ordered = /^\d/.test(first[2]);
  const items = [];
  let i = start;

  while (i < lines.length) {
    const m = lines[i].match(RE_LIST);
    if (!m) {
      // 列表项续行（缩进 2 空格以上）：并进上一项，不当新段落
      if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length) {
        items[items.length - 1].text += " " + lines[i].trim();
        i++;
        continue;
      }
      break;
    }
    const indent = m[1].length;
    if (indent < baseIndent) break;
    if (indent > baseIndent) {
      const [sub, next] = parseList(lines, i, opts);
      items[items.length - 1].children += sub;
      i = next;
      continue;
    }
    items.push({ text: m[3], children: "" });
    i++;
  }

  const tag = ordered ? "ol" : "ul";
  const body = items
    .map((it) => `<li>${inline(it.text, opts)}${it.children}</li>`)
    .join("");
  return [`<${tag}>${body}</${tag}>`, i];
}

function parseMermaid(code) {
  const lines = String(code || "").replace(/\r\n?/g, "\n").split("\n");
  const labels = {};
  const children = {};
  const targets = new Set();
  const edges = [];
  const defRe = /\b([A-Za-z][\w-]*)\s*(?:\[([^\]]*)\]|\(([^)]*)\)|\{([^}]*)\})/g;
  const edgeRe = /\b([A-Za-z][\w-]*)\s*(?:-->|---|-.->|==>)\s*(?:\|[^|]*\|\s*)?([A-Za-z][\w-]*)/g;

  for (const line of lines) {
    const source = line.replace(/%%/g, "");
    let m;
    while ((m = defRe.exec(source))) {
      const id = m[1];
      const label = (m[2] ?? m[3] ?? m[4] ?? id).trim();
      if (!labels[id]) labels[id] = label || id;
    }
    while ((m = edgeRe.exec(source))) {
      const from = m[1];
      const to = m[2];
      if (!labels[from]) labels[from] = from;
      if (!labels[to]) labels[to] = to;
      edges.push({ from, to });
      targets.add(to);
      (children[from] ||= []).push(to);
    }
  }

  const ids = Object.keys(labels);
  if (!ids.length) return "";
  const roots = ids.filter((id) => !targets.has(id));
  const hasCycle = (() => {
    const visiting = new Set();
    const visited = new Set();
    const walk = (id) => {
      if (visiting.has(id)) return true;
      if (visited.has(id)) return false;
      visiting.add(id);
      for (const child of children[id] || []) if (walk(child)) return true;
      visiting.delete(id);
      visited.add(id);
      return false;
    };
    return ids.some(walk);
  })();

  const node = (id) => `<span class="mm-node">${esc(labels[id] || id)}</span>`;
  if (roots.length === 1 && edges.length && !hasCycle) {
    const seen = new Set();
    const tree = (id) => {
      if (seen.has(id)) return `<span class="mm-node-wrap">${node(id)}</span>`;
      seen.add(id);
      const kids = (children[id] || []).filter(Boolean);
      if (!kids.length) return `<span class="mm-node-wrap">${node(id)}</span>`;
      const branches = kids
        .map((kid) => `<div class="mm-edge"><span class="mm-arrow">↳</span>${tree(kid)}</div>`)
        .join("");
      return `<span class="mm-node-wrap">${node(id)}<span class="mm-children">${branches}</span></span>`;
    };
    return `<div class="md-mermaid"><div class="mm-caption">流程图</div><div class="mm-tree">${tree(roots[0])}</div></div>`;
  }

  const flat = edges
    .map(
      (edge) =>
        `<div class="mm-edge">${node(edge.from)}<span class="mm-arrow">→</span>${node(edge.to)}</div>`
    )
    .join("");
  return `<div class="md-mermaid"><div class="mm-caption">流程图</div><div class="mm-flat">${flat}</div></div>`;
}

function blocks(text, opts) {
  const lines = String(text == null ? "" : text).replace(/\r\n?/g, "\n").split("\n");
  const html = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    const fence = line.match(RE_FENCE);
    if (fence) {
      const lang = (fence[1] || "").toLowerCase();
      const buf = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        buf.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++; // 跳过结束围栏
      const code = buf.join("\n");
      if (lang === "mermaid") {
        const mermaid = parseMermaid(code);
        if (mermaid) {
          html.push(mermaid);
          continue;
        }
      }
      const cls = lang ? ` class="language-${esc(lang)}"` : "";
      html.push(`<pre class="code-block"><code${cls}>${esc(code)}</code></pre>`);
      continue;
    }

    if (!line.trim()) {
      i++;
      continue;
    }

    const heading = line.match(RE_HEADING);
    if (heading) {
      const lv = heading[1].length;
      html.push(`<h${lv}>${inline(heading[2], opts)}</h${lv}>`);
      i++;
      continue;
    }

    if (RE_HR.test(line)) {
      html.push("<hr>");
      i++;
      continue;
    }

    if (RE_QUOTE.test(line)) {
      const buf = [];
      while (i < lines.length && RE_QUOTE.test(lines[i])) {
        buf.push(lines[i].replace(RE_QUOTE, ""));
        i++;
      }
      html.push(`<blockquote>${inline(buf.join(" "), opts)}</blockquote>`);
      continue;
    }

    if (line.includes("|") && i + 1 < lines.length && RE_TABLE_SEP.test(lines[i + 1])) {
      const [table, next] = parseTable(lines, i, opts);
      html.push(table);
      i = next;
      continue;
    }

    if (RE_LIST.test(line)) {
      const [list, next] = parseList(lines, i, opts);
      html.push(list);
      i = next;
      continue;
    }

    // 段落：吃到空行或下一个块级起点
    const buf = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !RE_FENCE.test(lines[i]) &&
      !RE_HEADING.test(lines[i]) &&
      !RE_QUOTE.test(lines[i]) &&
      !RE_LIST.test(lines[i]) &&
      !RE_HR.test(lines[i])
    ) {
      buf.push(lines[i]);
      i++;
    }
    if (buf.length) html.push(`<p>${inline(buf.join("\n"), opts).replace(/\n/g, "<br>")}</p>`);
  }

  return html.join("\n");
}

/**
 * @param {string} text Markdown 原文
 * @param {{cite?: (n:number)=>string|null}} [opts]
 */
export function renderMarkdown(text, opts = {}) {
  return blocks(text, { cite: null, ...opts });
}
