import DefaultTheme from "vitepress/theme";
import { h, nextTick, onMounted, watch } from "vue";
import { useRoute } from "vitepress";
import mermaid from "mermaid";
import "./custom.css";

mermaid.initialize({
  startOnLoad: false,
  securityLevel: "strict",
  theme: "base",
  themeVariables: {
    fontFamily: '"Inter", "PingFang SC", "Microsoft YaHei", sans-serif',
    primaryColor: "#FFFFFF",
    primaryBorderColor: "#D2D2CB",
    primaryTextColor: "#171715",
    lineColor: "#6F8A8C",
    secondaryColor: "#F7F7F5",
    tertiaryColor: "#EFEFEB"
  }
});

async function renderMermaid() {
  if (typeof document === "undefined") return;
  await nextTick();
  const blocks = Array.from(document.querySelectorAll("div.language-mermaid, pre > code.language-mermaid"));
  for (const node of blocks) {
    const wrapper = node.matches("div") ? node : node.parentElement;
    if (!wrapper || wrapper.dataset.mermaidRendered === "1") continue;
    const source = (node.matches("div") ? node.querySelector("pre")?.textContent : node.textContent) || "";
    const id = "mermaid-" + Math.random().toString(36).slice(2);
    try {
      const { svg } = await mermaid.render(id, source);
      const box = document.createElement("div");
      box.className = "handbook-mermaid";
      box.innerHTML = svg;
      wrapper.replaceWith(box);
    } catch (error) {
      wrapper.dataset.mermaidRendered = "1";
      wrapper.classList.add("mermaid-error");
      console.warn("Mermaid render failed", error);
    }
  }
}

const Layout = DefaultTheme.Layout;

export default {
  extends: DefaultTheme,
  enhanceApp() {
    if (typeof window !== "undefined") {
      window.addEventListener("load", renderMermaid);
      setInterval(renderMermaid, 1200);
    }
  },
  Layout: {
    setup() {
      const route = useRoute();
      const run = () => {
        setTimeout(renderMermaid, 80);
      };
      onMounted(run);
      watch(() => route.path, run);
      return () => h(Layout);
    }
  }
};
