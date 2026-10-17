#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : wizard.py
@Function: 把四步向导的**接口**挂到 8000 的正式服务上（M3 收口：页面迁到 Vue）

分工：
    接口实现 在 rag_demo/mvp/app.py（上传 / 字段识别 / 构建 / 问答 的同一套真实现）
    挂载     在本文件（正式服务的接入点）

页面去哪了（M3 收口）：
    老的四步向导页（mvp/static/wizard.html，原生 JS + 紫色大色块）已冻结，
    页面重写为 Vue 3 的 `/v2/#/setup`（web/src/views/Setup.vue），视觉与交互
    跟 /v2 其余页面统一。所以本模块的 `/wizard` 只剩一个 302：
    老链接、旧 SPA 侧边栏的「数据导入」、书签都还能用，但不再渲染老页面。
    `/api/wizard/*` 一个字段都没变，新页面直接对接同一套接口。

静态挂载：
    M3 收口后本模块**不再挂** `/static/wizard`（老页面的静态资源只在 8002
    独立调试服务里还留着，见 mvp/app.py 自己的 mount）。main.py 里仍保持
    `register_wizard(app)` 在既有 `/static` 挂载之前的位置——现在没有自己的
    静态挂载点了，顺序不再敏感，但保持原顺序，避免以后再加挂载点时又踩
    「先通用后特殊」的坑。
"""
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from rag_demo import auth
from rag_demo.mvp.app import router as wizard_api

# 老页面 → Vue 新版向导。hash 路由的 fragment 在 Location 里浏览器会照常跳转，
# 服务端不需要为 /v2/#/setup 单独注册路由（静态挂载 + 前端路由接管）。
NEW_WIZARD_URL = "/v2/#/setup"


def require_login(request: Request) -> None:
    """
    向导接口的登录闸门（M3）

    挂在 router 级依赖上而不是逐个端点加：10 个端点漏一个就是一次越权，
    而"哪个漏了"在 code review 里极难看出来。

    待审核账号：401/403 分开是有意的——401 让前端跳登录页，
    403 让前端显示"等待审核"，两者用户的下一步动作完全不同。
    """
    if not auth.AUTH_ENABLED:
        return
    account = auth.current_account()
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if account.get("status") != auth.STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="账号待审核：通过后才能上传与查询")


# 页面与接口分两个 router：接口那个（wizard_api）自带 /api/wizard 前缀且
# 带 OpenAPI 标签，页面这条不需要进文档，混在一起会让 /docs 里多出一个空的标签组。
_page = APIRouter()


@_page.get("/wizard", include_in_schema=False)
def wizard_page() -> RedirectResponse:
    """四步向导页：M3 收口后由 Vue 接管（/v2/#/setup），老链接 302 过去

    登录校验交给新版页面的路由守卫：未登录时 /v2/#/setup 会跳 /login，
    这里不重复判断——多一处判断就多一处「两边不一致」的可能。
    """
    return RedirectResponse(NEW_WIZARD_URL, status_code=302)


def register_wizard(app: FastAPI) -> None:
    """把向导的页面（302）与接口注册到正式服务上"""
    app.include_router(_page)
    # 登录闸门：`/api/wizard/*` 全部要求登录态（8002 独立调试服务不走这里）
    app.include_router(wizard_api, dependencies=[Depends(require_login)])
