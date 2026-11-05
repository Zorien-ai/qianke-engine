"""本地 Webhook 接收端（仅开发联调，不参与生产）。

用法：
    python scripts/dev_webhook_receiver.py
    # 默认监听 127.0.0.1:8099/hook
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        print(f"POST {self.path} auth={self.headers.get('Authorization')}", flush=True)
        try:
            print(json.dumps(json.loads(raw), ensure_ascii=False, indent=2), flush=True)
        except json.JSONDecodeError:
            print(raw, flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--path", default="/hook")
    args = parser.parse_args()
    print(f"Webhook receiver: http://{args.host}:{args.port}{args.path}", flush=True)
    HTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
