"""把 docs/diagrams-src/*.html 渲染成 2x 高清 PNG，输出到 docs/assets/。

用法：
    python docs/diagrams-src/build.py

依赖：本机 Chrome（无头模式），无需安装任何第三方包。
改图流程：编辑对应 .html → 跑本脚本 → 覆盖 docs/assets/ 下同名 PNG。
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # 仓库根
OUT_DIR = os.path.join(ROOT, "docs", "assets")
TMP = os.path.join(os.environ.get("TEMP", "/tmp"), "qianke-diagram-build")

CHROME_CANDIDATES = [
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
]

# (源文件, 输出文件, 画布宽, 画布高) —— 宽高必须与 HTML 里 .stage 的宽高一致
JOBS = [
    ("architecture-pipeline.html",       "architecture-pipeline.png",       1300, 700),
    ("architecture-end-to-end.html",     "architecture-end-to-end.png",     1440, 730),
    ("architecture-data-ingestion.html", "architecture-data-ingestion.png", 1300, 485),
]

SCALE = 2  # 2x 输出：渲染尺寸 ×2，GitHub 在 Retina 屏上也不糊


def find_chrome():
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    sys.exit("未找到 Chrome / Edge，请先安装或修改 CHROME_CANDIDATES")


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(33)
    return struct.unpack(">II", head[16:24])


def main():
    chrome = find_chrome()
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(TMP, exist_ok=True)

    for src, dst, w, h in JOBS:
        src_path = os.path.join(HERE, src)
        if not os.path.exists(src_path):
            print(f"SKIP {src}（源文件不存在）")
            continue
        out = os.path.join(OUT_DIR, dst)
        cmd = [
            chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
            "--no-first-run", "--disable-extensions", "--hide-scrollbars",
            f"--force-device-scale-factor={SCALE}",
            f"--user-data-dir={os.path.join(TMP, 'profile_' + dst)}",
            f"--window-size={w},{h}",
            "--virtual-time-budget=5000",
            f"--screenshot={out}",
            "file:///" + src_path.replace("\\", "/"),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
        if os.path.exists(out) and os.path.getsize(out) > 0:
            pw, ph = png_size(out)
            print(f"OK   {dst:34s} {pw}x{ph}  {os.path.getsize(out)/1024:.1f} KB")
        else:
            print(f"FAIL {dst}  rc={proc.returncode}  {proc.stderr.decode('utf-8','replace')[:200]}")


if __name__ == "__main__":
    main()
