import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const docsSite = path.resolve(__dirname, "..");
const repo = path.resolve(docsSite, "..");
const handbook = path.join(repo, "docs", "handbook");
const dist = path.join(docsSite, ".vitepress", "dist");
const requireDist = process.argv.includes("--require-dist");

const sections = [
  ["01-agent-architecture", "agent-architecture"],
  ["02-enterprise-governance", "enterprise-governance"],
  ["03-system-architecture", "system-architecture"],
  ["04-data-knowledge", "data-knowledge"],
  ["05-reliability-evaluation", "reliability-evaluation"],
  ["06-architecture-practice", "architecture-practice"]
];

const requiredFrontmatter = [
  "title", "description", "section", "section_order", "order", "slug",
  "doc_status", "implementation_status", "version", "updated"
];

const errors = [];
const warnings = [];
const articles = [];

function fail(message) {
  errors.push(message);
}

function warn(message) {
  warnings.push(message);
}

function parseFrontmatter(text) {
  if (!text.startsWith("---\n")) return null;
  const end = text.indexOf("\n---", 4);
  if (end < 0) return null;
  const block = text.slice(4, end);
  const values = {};
  for (const line of block.split("\n")) {
    const match = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (match) values[match[1]] = match[2].trim().replace(/^"|"$/g, "");
  }
  return values;
}

function countH2(text) {
  let inFence = false;
  let count = 0;
  for (const line of text.split("\n")) {
    if (line.trim().startsWith("```")) {
      inFence = !inFence;
      continue;
    }
    if (!inFence && /^##\s+/.test(line)) count += 1;
  }
  return count;
}

function checkLinks(file, text) {
  const sourceDir = path.dirname(file);
  const linkPattern = /\[[^\]]*\]\(([^)]+)\)/g;
  let match;
  while ((match = linkPattern.exec(text)) !== null) {
    let target = match[1].trim();
    if (!target || target.startsWith("http://") || target.startsWith("https://")) continue;
    if (target.startsWith("#") || target.startsWith("mailto:")) continue;
    if (target.startsWith("/")) continue;
    target = target.split("#")[0].split("?")[0];
    if (!target) continue;
    const resolved = path.resolve(sourceDir, target);
    if (!fs.existsSync(resolved)) {
      fail(`${path.relative(repo, file)}: 链接目标不存在 -> ${match[1]}`);
    }
  }
}

for (const [sourceDir, urlDir] of sections) {
  const dir = path.join(handbook, sourceDir);
  const allFiles = fs.readdirSync(dir).filter((name) => name.endsWith(".md") && name !== "index.md").sort();
  const files = allFiles.filter((name) => name !== "01-enterprise-agent-architecture-v0.5.1.md");
  if (files.length !== 10) fail(`${sourceDir}: 期望 10 篇公开文章，实际 ${files.length}`);
  if (allFiles.includes("01-enterprise-agent-architecture-v0.5.1.md")) {
    warn(`${sourceDir}: V0.5.1 历史文件存在，已从公开清单排除`);
  }
  for (const name of files) {
    const file = path.join(dir, name);
    const text = fs.readFileSync(file, "utf8").replace(/^\uFEFF/, "").replace(/\r\n/g, "\n");
    const fm = parseFrontmatter(text);
    const rel = path.relative(repo, file);
    if (!fm) {
      fail(`${rel}: 缺少 frontmatter`);
      continue;
    }
    for (const key of requiredFrontmatter) {
      if (!fm[key]) fail(`${rel}: frontmatter 缺少 ${key}`);
    }
    if (countH2(text) !== 12) fail(`${rel}: 期望 12 个二级章节，实际 ${countH2(text)}`);
    if (text.includes("READ_ONLY_VIOLATION")) fail(`${rel}: 仍包含旧错误码 READ_ONLY_VIOLATION`);
    if (!text.includes("```mermaid") && !text.includes("flowchart")) warn(`${rel}: 未发现 Mermaid 图`);
    checkLinks(file, text);
    articles.push({ sourceDir, urlDir, name, stem: name.replace(/\.md$/, ""), rel });
  }
}

if (articles.length !== 60) fail(`公开文章总数应为 60，实际 ${articles.length}`);
if (!fs.existsSync(path.join(handbook, "01-agent-architecture", "01-enterprise-agent-architecture-v0.5.2.md"))) {
  fail("缺少 V0.5.2 基线文章");
}
if (!fs.existsSync(path.join(handbook, "01-agent-architecture", "01-enterprise-agent-architecture-v0.5.1.md"))) {
  fail("V0.5.1 历史文件不应被删除");
}
const baseline = path.join(handbook, "01-agent-architecture", "01-enterprise-agent-architecture-v0.5.2.md");
if (!fs.readFileSync(baseline, "utf8").includes("SQL_VALIDATION_ERROR")) {
  fail("V0.5.2 基线缺少 SQL_VALIDATION_ERROR");
}

const config = fs.readFileSync(path.join(docsSite, ".vitepress", "config.mjs"), "utf8");
if (!config.includes("01-enterprise-agent-architecture-v0.5.2")) fail("docs-site 未指向 V0.5.2");
if (!config.includes("01-enterprise-agent-architecture-v0.5.1.md")) fail("docs-site 未排除 V0.5.1 历史文件");

if (requireDist) {
  if (!fs.existsSync(dist)) fail("缺少 docs-site/.vitepress/dist，请先运行 npm run build");
  for (const article of articles) {
    const html = path.join(dist, article.urlDir, `${article.stem}.html`);
    if (!fs.existsSync(html)) fail(`缺少构建页面: ${path.relative(repo, html)}`);
  }
}

console.log(`handbook content check: ${articles.length} articles, ${errors.length} errors, ${warnings.length} warnings`);
if (warnings.length) console.log(warnings.slice(0, 20).join("\n"));
if (errors.length) {
  console.error(errors.slice(0, 50).join("\n"));
  process.exit(1);
}
console.log("handbook content check: PASS");
