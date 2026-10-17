#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : api_auth.py
@Function: HTTP 工具脚本的登录辅助（M3 起业务接口需要登录态）

为什么需要它
------------
M3 之前脚本可以直接打 `/qa`，因为身份靠请求头自报、缺失时兜底 admin。
现在身份来自 Cookie 会话，未登录一律 401——脚本不改就会「全挂」。

账号从环境变量取，不写死在脚本里：

    RAG_USER      默认 admin
    RAG_PASSWORD  默认取 RAG_ADMIN_PASSWORD，再退 admin123

用法：

    from rag_demo.tools.api_auth import login
    opener = login("http://127.0.0.1:8000")
    opener.open(req)          # 自动带 Cookie
"""
import http.cookiejar
import json
import os
import urllib.error
import urllib.request


def login(
    base: str,
    username: str | None = None,
    password: str | None = None,
) -> urllib.request.OpenerDirector:
    """
    登录并返回带 Cookie 的 opener

    失败直接抛 RuntimeError（脚本是人工跑的，一行明确原因比堆栈有用）。
    """
    user = username or os.environ.get("RAG_USER", "admin")
    pwd = password or os.environ.get("RAG_PASSWORD") or os.environ.get(
        "RAG_ADMIN_PASSWORD", "admin123"
    )
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(
        base.rstrip("/") + "/auth/login",
        data=json.dumps({"username": user, "password": pwd}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with opener.open(req, timeout=15) as resp:
            json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(
            f"登录失败（{e.code}）：{detail}\n"
            f"账号来自 RAG_USER/RAG_PASSWORD，默认 admin/admin123。"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"连不上服务 {base}：{e.reason}") from e
    return opener
