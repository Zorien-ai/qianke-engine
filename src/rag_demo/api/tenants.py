"""管理端租户管理 API：租户概览、成员绑定、账号查询。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from rag_demo import auth
from rag_demo.c_end import store
from rag_demo.merchant import MerchantError, get_merchant_repository
from rag_demo.superagent import store as sa_store

router = APIRouter(prefix="/api/admin/tenants", tags=["tenants"])


class TenantIn(BaseModel):
    merchant_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=80)


class MemberIn(BaseModel):
    account_id: int = Field(..., ge=1)
    role: str = Field(default="owner", pattern="^(owner|admin|staff)$")


class ProvisionIn(BaseModel):
    merchant_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=80)
    owner_account_id: int | None = Field(default=None, ge=1)
    owner_username: str = Field(default="", max_length=80)
    compensation_max_amount: float = Field(default=50, ge=0, le=100000)
    refund_max_amount: float = Field(default=1000, ge=0, le=100000)


def _admin() -> dict[str, Any]:
    account = auth.current_account()
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if account.get("status") != auth.STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="账号不可用")
    if not account.get("is_system_admin"):
        raise HTTPException(status_code=403, detail="只有系统管理员可以管理租户")
    return account


def _manage_tenant(merchant_id: str) -> dict[str, Any]:
    account = auth.current_account()
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if account.get("status") != auth.STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="账号不可用")
    if account.get("is_system_admin"):
        return account
    member = store.get_merchant_member(account["id"])
    if member is None or member["merchant_id"] != merchant_id or member["role"] != "owner":
        raise HTTPException(status_code=403, detail="只有系统管理员或租户 owner 可以管理成员")
    return account


def _member_payload(member: dict[str, Any]) -> dict[str, Any]:
    user = auth.find_user_by_id(int(member["account_id"])) or {}
    return {
        "account_id": member["account_id"],
        "username": user.get("username") or f"#{member['account_id']}",
        "display_name": user.get("display_name") or "",
        "role": member["role"],
        "created_at": member["created_at"],
    }


def _tenant_payload(tenant: dict[str, Any]) -> dict[str, Any]:
    merchant_id = tenant["merchant_id"]
    try:
        orders = get_merchant_repository().list_orders(merchant_id, limit=500)
        products = get_merchant_repository().list_products(merchant_id, limit=500)
        backend_error = ""
    except MerchantError as exc:
        orders, products, backend_error = [], [], str(exc)
    items = sa_store.list_work_items(limit=200, merchant_id=merchant_id)
    open_items = sum(
        1 for item in items if item["status"] in {"PENDING", "RUNNING", "WAITING_APPROVAL", "EXECUTING"}
    )
    return {
        **tenant,
        "members": [_member_payload(m) for m in store.list_merchant_members(merchant_id)],
        "policy": store.get_merchant_policy(merchant_id),
        "provisions": store.list_tenant_provisions(merchant_id, limit=5),
        "counts": {
            "orders": len(orders),
            "products": len(products),
            "work_items": len(items),
            "open_work_items": open_items,
        },
        "backend_error": backend_error,
    }


@router.get("")
def list_tenants() -> dict[str, Any]:
    _admin()
    tenants = [_tenant_payload(t) for t in store.list_tenants()]
    return {"tenants": tenants}


@router.post("")
def create_tenant(req: TenantIn) -> dict[str, Any]:
    _admin()
    try:
        tenant = store.create_tenant(req.merchant_id, req.name)
    except store.CStoreError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc
    return {"tenant": _tenant_payload(tenant)}


@router.post("/provision")
def provision_tenant(req: ProvisionIn) -> dict[str, Any]:
    """开通租户：租户 + owner + 默认动作策略，一步完成。"""
    admin = _admin()
    owner = auth.find_user_by_id(req.owner_account_id) if req.owner_account_id else None
    if owner is None and req.owner_username:
        owner = auth.find_user(req.owner_username)
    if owner is None:
        raise HTTPException(status_code=404, detail="owner 账号不存在")
    if owner.get("status") != auth.STATUS_ACTIVE:
        raise HTTPException(status_code=409, detail="owner 账号不可用")
    try:
        result = store.provision_tenant(
            req.merchant_id,
            req.name,
            int(owner["id"]),
            compensation_max_amount=req.compensation_max_amount,
            refund_max_amount=req.refund_max_amount,
            created_by=str(admin.get("username") or ""),
        )
    except store.CStoreError as exc:
        status = 409 if exc.code in {"ACCOUNT_ALREADY_BOUND"} else 400
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from exc
    tenant = store.get_tenant(req.merchant_id)
    assert tenant is not None
    return {
        "provisioned": True,
        "tenant": _tenant_payload(tenant),
        "owner": _member_payload(result["member"]),
        "policy": result["policy"],
    }


@router.get("/accounts")
def search_accounts(q: str = Query(default="", max_length=80)) -> dict[str, Any]:
    _admin()
    needle = q.strip().lower()
    users = auth.list_users()
    matched = [
        {
            "id": user["id"],
            "username": user.get("username"),
            "display_name": user.get("display_name") or "",
            "status": user.get("status"),
        }
        for user in users
        if not needle
        or needle in str(user.get("username") or "").lower()
        or needle in str(user.get("display_name") or "").lower()
    ][:30]
    return {"accounts": matched}


@router.post("/{merchant_id}/members")
def bind_member(merchant_id: str, req: MemberIn) -> dict[str, Any]:
    _manage_tenant(merchant_id)
    tenant = store.get_tenant(merchant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="租户不存在")
    user = auth.find_user_by_id(req.account_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    member = store.bind_merchant_member(req.account_id, merchant_id, role=req.role)
    return {"member": _member_payload(member), "tenant_id": merchant_id}


@router.delete("/{merchant_id}/members/{account_id}")
def unbind_member(merchant_id: str, account_id: int) -> dict[str, Any]:
    _manage_tenant(merchant_id)
    member = store.get_merchant_member(account_id)
    if member is None or member["merchant_id"] != merchant_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    removed = store.unbind_merchant_member(account_id)
    return {"removed": removed, "tenant_id": merchant_id, "account_id": account_id}
