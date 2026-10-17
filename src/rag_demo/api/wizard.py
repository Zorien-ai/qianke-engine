#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : wizard.py
@Function: 把四步向导挂到 8000 的正式服务上（M2）

分工：
    实现 在 rag_demo/mvp/app.py（M2 的迭代区：mock 逐步换成真实实现）
    挂载 在本文件（正式服务的接入点）

为什么拆开而不是让 main.py 直接 include：
    main.py 已经很长（问答、检索、权限、缓存全在里面）。向导是**另一条业务线**
    （上传 → 确认 → 构建 → 查询），它跟问答共用服务，但不共用逻辑。
    单独一个接入模块，既让 main.py 只多一行，也给 M2 后续的向导专用配置
    （CORS、上传大小限制、任务队列开关）留了落点。

静态资源挂载顺序（**别调换**）：
    main.py 里已有 `app.mount("/static", api/static)`。Starlette 按注册顺序匹配
    前缀，且 Mount 命中后不会再落给后面的路由——也就是说，若先注册了 `/static`，
    那么 `/static/wizard/wizard.css` 会被 api/static 那个挂载点吃掉并 404。
    所以本模块的 `/static/wizard` 必须**先**注册，main.py 里那一行
    `register_wizard(app)` 因此放在既有静态挂载之前。

与 8001 的关系：
    8001 跑的是冻结快照（prototype/m1_mock/），与本文件无关。
    本文件只服务 8000，改这里不会影响任何测试者。
"""
import os

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from rag_demo import auth
from rag_demo.mvp.app import STATIC_DIR as WIZARD_STATIC_DIR
from rag_demo.mvp.app import router as wizard_api


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
def wizard_page() -> Response:
    """四步向导页（上传 → 确认 → 构建 → 查询）；未登录先登录"""
    if auth.AUTH_ENABLED and auth.current_account() is None:
        return RedirectResponse("/login", status_code=302)
    return FileResponse(os.path.join(WIZARD_STATIC_DIR, "wizard.html"))


def register_wizard(app: FastAPI) -> None:
    """把向导的页面、静态资源与接口注册到正式服务上（调用顺序见模块 docstring）"""
    app.mount(
        "/static/wizard",
        StaticFiles(directory=WIZARD_STATIC_DIR),
        name="wizard-static",
    )
    app.include_router(_page)
    # 登录闸门：`/api/wizard/*` 全部要求登录态（独立调试服务 8002 不走这里）
    app.include_router(wizard_api, dependencies=[Depends(require_login)])
