/* 轻量 Markdown 渲染（无依赖，离线可用）
 *
 * 为什么自己写而不是引 marked：
 *   这个 demo 是离线部署的，前端没有任何构建流程与第三方包；
 *   引一个库要么走 CDN（内网断网就白屏），要么塞一份 vendor 进来。
 *   这里需要的语法是可控的（LLM 输出的子集），一百多行就够，且行为可预期。
 *
 * 支持：
 *   块级：标题、无序/有序列表（含一层嵌套）、表格（GFM）、代码块、引用、分隔线、段落
 *   行内：**粗体**、*斜体*、~~删除线~~、`行内代码`、[文字](链接)、[来源N] 回调
 *   图表：```mermaid 代码块交给 hydrateMermaid() 渲染（库不在时保留代码块，不报错）
 *
 * 安全：先把整段文本转义，再做结构替换；不直通原始 HTML。
 *
 * 流式渲染的容错：
 *   · 未闭合的 **粗体** 不会被匹配（正则要求成对）
 *   · 未闭合的 ``` 代码块按「到结尾」处理，不会吞掉后面的段落（视觉可接受）
 *   · 表格分隔行还没到达时，先按段落显示，到达后整块重渲染成表格
 */
(function () {
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ESC[c]);

  const RE_FENCE = /^\s*```([\w+-]*)\s*$/;
  const RE_HEADING = /^(#{1,6})\s+(.*)$/;
  const RE_HR = /^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/;
  const RE_QUOTE = /^\s*>\s?/;
  const RE_LIST = /^(\s*)([-*+]|\d+\.)\s+(.*)$/;
  const RE_TABLE_SEP = /^\s*\|?[\s:|-]+\|[\s:|-]*$/;

  /* ---------- 行内 ---------- */
  function inline(src, opts) {
    const codes = [];
    let out = esc(src);

    // 行内代码先抽出来：里面的 ** 不该被当加粗
    out = out.replace(/`([^`\n]+)`/g, (m, code) => {
      codes.push(`<code>${code}</code>`);
      return `\u0000${codes.length - 1}\u0000`;
    });

    // 链接：只放行 http(s)，避免 javascript:
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

  /* ---------- 表格 ---------- */
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
      "<tr>" +
      head.map((c, k) => `<th${style(k)}>${inline(c, opts)}</th>`).join("") +
      "</tr>";
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

  /* ---------- 列表 ---------- */
  function parseList(lines, start, opts) {
    const first = lines[start].match(RE_LIST);
    const baseIndent = first[1].length;
    const ordered = /^\d/.test(first[2]);
    const items = [];
    let i = start;

    while (i < lines.length) {
      const m = lines[i].match(RE_LIST);
      if (!m) {
        // 列表项的续行（缩进 2 空格以上）：并进上一项，不当新段落
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

  /* ---------- 块级 ---------- */
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
          // 存原文，流式结束后由 hydrateMermaid 换成 SVG；
          // 库没加载或渲染失败时，这里就是一块可读的代码，不会白屏
          html.push(
            `<div class="mermaid-block" data-code="${encodeURIComponent(code)}">` +
              `<pre class="code-block"><code class="language-mermaid">${esc(code)}</code></pre>` +
              `</div>`
          );
        } else {
          const cls = lang ? ` class="language-${esc(lang)}"` : "";
          html.push(`<pre class="code-block"><code${cls}>${esc(code)}</code></pre>`);
        }
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

      if (
        line.includes("|") &&
        i + 1 < lines.length &&
        RE_TABLE_SEP.test(lines[i + 1])
      ) {
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

  let mmdSeq = 0;

  /**
   * 把容器里的 ```mermaid 代码块渲染成图
   * 库未加载 / 语法错误时保留原代码块并标记，不抛异常
   */
  function hydrateMermaid(root) {
    if (!root || !window.mermaid) return;
    root.querySelectorAll(".mermaid-block[data-code]").forEach(async (box) => {
      if (box.dataset.rendered === "1") return;
      box.dataset.rendered = "1";
      const code = decodeURIComponent(box.dataset.code || "");
      try {
        const id = `mmd-${++mmdSeq}`;
        const { svg } = await window.mermaid.render(id, code);
        box.innerHTML = svg;
        box.classList.add("is-svg");
      } catch (e) {
        // 渲染失败就把代码块留着，并标出来——比显示半张图好排查
        box.dataset.rendered = "";
        box.classList.add("is-error");
        box.title = "图表渲染失败：" + (e && e.message ? e.message : e);
      }
    });
  }

  /**
   * @param {string} text
   * @param {{cite?: (n:number)=>string|null}} opts
   *        cite 返回该 [来源N] 要替换成的 HTML；返回 null 表示去掉
   */
  function renderMarkdown(text, opts) {
    return blocks(text, opts || {});
  }

  function initMermaid() {
    if (!window.mermaid) return;
    window.mermaid.initialize({
      startOnLoad: false,
      theme: "default",
      securityLevel: "strict",
      fontFamily: "inherit",
    });
  }

  window.renderMarkdown = renderMarkdown;
  window.hydrateMermaid = hydrateMermaid;
  window.escapeHtml = window.escapeHtml || esc;

  if (window.mermaid) initMermaid();
  else document.addEventListener("DOMContentLoaded", initMermaid, { once: true });
})();
