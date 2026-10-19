"""行情数据门面（facade）。

上层工具（tools.py）与接口（main.py）只依赖这里，不关心数据到底是真实行情
还是本地模拟。切换方式见环境变量 `STOCK_DATA_SOURCE`：

  auto （默认）  优先真实行情；任何一次网络/接口异常都自动回退到模拟数据
  live           只用真实行情；失败就把异常抛出去
  mock           只用本地模拟数据（完全离线，用于演示兜底）

真实数据源见 sources/live.py（腾讯行情 + 东方财富，免 token）。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from .sources import base, live, mock

logger = logging.getLogger(__name__)

DATA_MODE = (os.environ.get("STOCK_DATA_SOURCE") or "auto").strip().lower()
if DATA_MODE not in {"auto", "live", "mock"}:
    DATA_MODE = "auto"

MAIN_INDICES = base.MAIN_INDICES
INDEX_ALIASES = base.INDEX_ALIASES


def _select_providers() -> tuple[Any, Any | None]:
    """返回 (主 provider, 兜底 provider)。"""
    if DATA_MODE == "mock":
        return mock, None
    if DATA_MODE == "live":
        return live, None
    return live, mock


_PRIMARY, _FALLBACK = _select_providers()

IS_LIVE = bool(getattr(_PRIMARY, "IS_LIVE", False))
PROVIDER_NAME = _PRIMARY.PROVIDER_NAME


def _call(name: str, *args: Any, **kwargs: Any) -> Any:
    """调用主 provider；auto 模式下失败则回退到模拟数据。"""
    try:
        return getattr(_PRIMARY, name)(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        if _FALLBACK is None:
            raise
        logger.warning("行情源 %s.%s 失败，回退模拟数据：%s", _PRIMARY.PROVIDER_NAME, name, exc)
        return getattr(_FALLBACK, name)(*args, **kwargs)


# --------------------------------------------------------------------------- #
# 对外 API（与 provider 同名同签名）
# --------------------------------------------------------------------------- #


def normalize_symbol(symbol: str) -> str:
    return _call("normalize_symbol", symbol)


def search(keyword: str) -> list[dict[str, str]]:
    return _call("search", keyword)


def get_stock(code: str) -> dict[str, Any] | None:
    return _call("get_stock", code)


def get_index(code: str) -> dict[str, Any] | None:
    return _call("get_index", code)


def get_news(code: str) -> list[str]:
    return _call("get_news", code)


def get_series(code: str, period: str = "day") -> dict[str, Any] | None:
    return _call("get_series", code, period)


def list_sectors() -> list[dict[str, Any]]:
    return _call("list_sectors")


def get_sector(keyword: str) -> dict[str, Any] | None:
    return _call("get_sector", keyword)


def sector_overview(limit: int = 5) -> dict[str, Any]:
    return _call("sector_overview", limit)


def change_pct(price: float, prev_close: float) -> float:
    """纯计算，不需要走 provider。"""
    if not prev_close:
        return 0.0
    return round((price - prev_close) / prev_close * 100, 2)


# --------------------------------------------------------------------------- #
# 动态元信息
# --------------------------------------------------------------------------- #
# 下面三个属性随当前 provider / 当天日期变化，所以用模块级 __getattr__ 提供，
# 而不是在 import 时定死一个常量。


def __getattr__(name: str) -> Any:
    if name == "AS_OF":
        return datetime.now().strftime("%Y-%m-%d")
    if name == "MARKET_STATUS":
        return _PRIMARY.MARKET_STATUS
    if name == "SOURCE_DESCRIPTION":
        return _PRIMARY.SOURCE_DESCRIPTION
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def describe() -> str:
    """给日志/调试用的可读描述。"""
    parts = [f"mode={DATA_MODE}", f"provider={PROVIDER_NAME}"]
    if _FALLBACK is not None:
        parts.append(f"fallback={_FALLBACK.PROVIDER_NAME}")
    return " ".join(parts)
