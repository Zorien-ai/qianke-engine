"""商家数据层工厂：按名称选择 adapter，并缓存实例。

可替换性在这里落地
------------------
- 内置 ``sqlite``（v1 默认）；未来接真实 OMS/PG 时，写一个实现
  :class:`rag_demo.merchant.repository.MerchantRepository` 协议的类，
  调 :func:`register_repository_backend` 注册即可，**不用改调用方**；
- 后端名默认读环境变量 ``QIANKE_MERCHANT_BACKEND``（缺省 ``sqlite``）；显式传参优先；
- 缓存按「后端 + 数据库位置 + 种子配置」分键：同进程重复 get 不会反复初始化/重复灌种子；
  测试或切换配置时调 :func:`reset_merchant_repository_cache`。

自定义 adapter 工厂的签名约定：
    factory(*, db_path=None, seed=True, seed_dir=None) -> MerchantRepository
（SQLite 之外的后端可以忽略这些参数；真实 OMS 适配器通常从自己的配置读连接信息。）
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Callable, cast

from .errors import MerchantConfigurationError
from .repository import MerchantRepository, MerchantWriteRepository
from .sqlite_repository import SqliteMerchantRepository, default_db_path
from .seeds import default_seed_dir

RepositoryFactory = Callable[..., MerchantRepository]

_ENV_BACKEND = "QIANKE_MERCHANT_BACKEND"

_BACKEND_FACTORIES: dict[str, RepositoryFactory] = {}
_CACHE: dict[tuple[Any, ...], MerchantRepository] = {}
_CACHE_LOCK = threading.RLock()


def register_repository_backend(name: str, factory: RepositoryFactory) -> None:
    """注册/覆盖一个数据后端（测试里的 Fake 或真实 OMS/PG adapter）。

    同名后端允许覆盖：这是**有意的**——测试需要把 ``sqlite`` 临时替换成内存实现，
    真实部署也可以在配置文件加载后覆盖默认实现。调用方不感知。
    """
    key = (name or "").strip().lower()
    if not key:
        raise MerchantConfigurationError("商家数据后端名称不能为空")
    if not callable(factory):
        raise MerchantConfigurationError("factory 必须可调用（callable）")
    with _CACHE_LOCK:
        _BACKEND_FACTORIES[key] = factory


def available_backends() -> list[str]:
    """当前已注册的后端名（排序后返回，便于日志与错误提示）。"""
    with _CACHE_LOCK:
        return sorted(_BACKEND_FACTORIES)


def default_backend() -> str:
    """默认后端：``QIANKE_MERCHANT_BACKEND`` 或 ``sqlite``。"""
    raw = (os.environ.get(_ENV_BACKEND) or "").strip().lower()
    return raw or "sqlite"


def _cache_key(
    name: str,
    db_path: str | Path | None,
    seed: bool,
    seed_dir: str | Path | None,
) -> tuple[Any, ...]:
    if name == "sqlite":
        resolved_db = Path(db_path).expanduser() if db_path else default_db_path()
        resolved_seed = Path(seed_dir).expanduser() if seed_dir else default_seed_dir()
        return (name, str(resolved_db), bool(seed), str(resolved_seed))
    return (name, str(db_path), bool(seed), str(seed_dir))


def get_merchant_repository(
    *,
    backend: str | None = None,
    db_path: str | Path | None = None,
    seed: bool = True,
    seed_dir: str | Path | None = None,
) -> MerchantRepository:
    """按后端名取一个商家数据 Repository（进程内缓存）。

    参数:
        backend:  "sqlite"（默认）/ 已注册的自定义后端；None → 环境变量或 sqlite
        db_path:  SQLite 文件路径；None → ``QIANKE_MERCHANT_DB`` 或 var/merchant_v1.sqlite
        seed:     是否在初始化时灌入种子数据（生产接真实 OMS 时应传 False）
        seed_dir: 种子目录；None → ``QIANKE_MERCHANT_SEED_DIR`` 或 data/merchant
    异常:
        MerchantConfigurationError: 后端名未知（会列出已注册后端）
    """
    name = (backend or default_backend()).strip().lower()
    with _CACHE_LOCK:
        factory = _BACKEND_FACTORIES.get(name)
        known = ", ".join(sorted(_BACKEND_FACTORIES)) or "无"
    if factory is None:
        raise MerchantConfigurationError(
            f"未知商家数据后端: {name!r}（已注册: {known}）。"
            f"接真实 OMS/PG 请实现 MerchantRepository 并用 register_repository_backend 注册"
        )

    key = _cache_key(name, db_path, seed, seed_dir)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        repository = factory(db_path=db_path, seed=seed, seed_dir=seed_dir)
        _CACHE[key] = repository
        return repository


def get_merchant_write_repository(
    *,
    backend: str | None = None,
    db_path: str | Path | None = None,
    seed: bool = True,
    seed_dir: str | Path | None = None,
) -> MerchantWriteRepository:
    """按后端名取一个**带写能力**的商家 Repository（库存预占 / 订单写入）。

    与 :func:`get_merchant_repository` 的区别只在于**能力边界**：只读 adapter 不实现
    ``MerchantWriteRepository`` 时，这里会明确抛 ``MerchantConfigurationError``，
    而不是让写调用在运行期才炸。真实 OMS 的只读账号应保持只读 adapter。

    参数与环境变量同 :func:`get_merchant_repository`。
    """
    repository = get_merchant_repository(
        backend=backend, db_path=db_path, seed=seed, seed_dir=seed_dir
    )
    if not isinstance(repository, MerchantWriteRepository):
        backend_name = getattr(repository, "backend", backend or "unknown")
        raise MerchantConfigurationError(
            f"商家数据后端 {backend_name!r} 只读，未实现 MerchantWriteRepository；"
            f"库存预占/订单写入需要可写 adapter（v1 仅内置 sqlite 支持）"
        )
    return cast(MerchantWriteRepository, repository)


def reset_merchant_repository_cache() -> None:
    """关闭并清空缓存（测试/切换配置用；调用后的下一次 get 会重新初始化）。"""
    with _CACHE_LOCK:
        repositories = list(_CACHE.values())
        _CACHE.clear()
    for repository in repositories:
        try:
            repository.close()
        except Exception:  # noqa: BLE001 adapter 的 close 失败不应阻断清理
            pass


# 内置默认后端：SQLite（v1）
register_repository_backend("sqlite", SqliteMerchantRepository)

__all__ = [
    "RepositoryFactory",
    "available_backends",
    "default_backend",
    "get_merchant_repository",
    "get_merchant_write_repository",
    "register_repository_backend",
    "reset_merchant_repository_cache",
]
