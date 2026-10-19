"""模拟行情数据源（mock provider）。

这里的价格数据全部是本地模拟的演示数据，不来自任何真实行情源，
不要用于投资决策。用作离线兜底：真实数据源不可用时自动回退到这里。

要接真实数据请看同目录的 live.py。
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from typing import Any

# 数据快照日期，仅用于说明这批模拟数据的时点
AS_OF = "2026-10-06"

# 交易日状态：closed=非交易时段（演示时展示的是上一交易日收盘数据）
MARKET_STATUS = "上一交易日收盘（演示数据）"


_STOCKS: dict[str, dict[str, Any]] = {
    "600519": {
        "name": "贵州茅台",
        "exchange": "上交所",
        "board": "主板",
        "industry": "白酒",
        "price": 1486.30,
        "prev_close": 1462.50,
        "open": 1465.00,
        "high": 1498.80,
        "low": 1460.20,
        "volume": 31245,  # 手
        "amount": 46.32,  # 亿元
        "turnover_rate": 0.25,
        "pe_ttm": 22.4,
        "pb": 7.8,
        "market_cap": 18672.5,  # 亿元，总市值
        "limit_status": "正常",
        "news": [
            "公司发布三季度经营数据：前三季度营业收入同比增长 8.2%，环比改善。",
            "机构调研纪要显示，直营渠道占比继续提升，i茅台平台投放节奏保持平稳。",
        ],
    },
    "300750": {
        "name": "宁德时代",
        "exchange": "深交所",
        "board": "创业板",
        "industry": "锂电池",
        "price": 268.80,
        "prev_close": 275.60,
        "open": 274.00,
        "high": 276.50,
        "low": 266.10,
        "volume": 486210,
        "amount": 131.26,
        "turnover_rate": 1.12,
        "pe_ttm": 19.7,
        "pb": 3.6,
        "market_cap": 11830.2,
        "limit_status": "正常",
        "news": [
            "公司公告：新一代储能电芯将于明年一季度量产，能量密度提升约 12%。",
            "海外工厂产能爬坡进度符合预期，欧洲客户订单已开始交付。",
        ],
    },
    "002594": {
        "name": "比亚迪",
        "exchange": "深交所",
        "board": "主板",
        "industry": "汽车整车",
        "price": 305.60,
        "prev_close": 296.20,
        "open": 297.50,
        "high": 309.90,
        "low": 296.80,
        "volume": 523180,
        "amount": 158.94,
        "turnover_rate": 1.85,
        "pe_ttm": 24.1,
        "pb": 4.9,
        "market_cap": 8897.4,
        "limit_status": "正常",
        "news": [
            "月度销量快报：新能源乘用车销量同比增长 21%，出口占比升至 18%。",
            "公司在投资者互动平台表示，高端品牌渠道建设按计划推进。",
        ],
    },
    "601318": {
        "name": "中国平安",
        "exchange": "上交所",
        "board": "主板",
        "industry": "保险",
        "price": 58.42,
        "prev_close": 58.90,
        "open": 58.95,
        "high": 59.20,
        "low": 58.10,
        "volume": 812340,
        "amount": 47.51,
        "turnover_rate": 0.44,
        "pe_ttm": 7.9,
        "pb": 1.1,
        "market_cap": 10642.8,
        "limit_status": "正常",
        "news": [
            "公司披露月度保费收入，寿险板块新业务价值保持双位数增长。",
            "公司公告回购进展，累计回购金额已达计划的 62%。",
        ],
    },
    "600036": {
        "name": "招商银行",
        "exchange": "上交所",
        "board": "主板",
        "industry": "银行",
        "price": 42.18,
        "prev_close": 41.60,
        "open": 41.70,
        "high": 42.45,
        "low": 41.55,
        "volume": 745120,
        "amount": 31.28,
        "turnover_rate": 0.36,
        "pe_ttm": 6.8,
        "pb": 1.0,
        "market_cap": 10638.9,
        "limit_status": "正常",
        "news": [
            "三季报：净息差环比企稳，财富管理手续费收入同比转正。",
            "公司公告董事会决议，拟续聘会计师事务所。",
        ],
    },
    "688981": {
        "name": "中芯国际",
        "exchange": "上交所",
        "board": "科创板",
        "industry": "半导体",
        "price": 92.35,
        "prev_close": 89.10,
        "open": 89.60,
        "high": 94.20,
        "low": 89.40,
        "volume": 618750,
        "amount": 57.05,
        "turnover_rate": 2.31,
        "pe_ttm": 78.5,
        "pb": 3.2,
        "market_cap": 7352.1,
        "limit_status": "正常",
        "news": [
            "公司指引：四季度产能利用率环比提升，成熟制程需求回暖。",
            "新增产线设备招标完成，资本开支节奏与全年计划一致。",
        ],
    },
    "300059": {
        "name": "东方财富",
        "exchange": "深交所",
        "board": "创业板",
        "industry": "证券",
        "price": 21.46,
        "prev_close": 20.35,
        "open": 20.50,
        "high": 21.88,
        "low": 20.42,
        "volume": 3268410,
        "amount": 69.52,
        "turnover_rate": 2.05,
        "pe_ttm": 33.6,
        "pb": 3.9,
        "market_cap": 3389.7,
        "limit_status": "正常",
        "news": [
            "公司披露基金代销数据，非货基保有量环比小幅回升。",
            "公告：可转债转股进展及股本变动情况。",
        ],
    },
    "000001": {
        "name": "平安银行",
        "exchange": "深交所",
        "board": "主板",
        "industry": "银行",
        "price": 11.28,
        "prev_close": 11.42,
        "open": 11.40,
        "high": 11.46,
        "low": 11.20,
        "volume": 1024560,
        "amount": 11.56,
        "turnover_rate": 0.53,
        "pe_ttm": 5.2,
        "pb": 0.6,
        "market_cap": 2189.3,
        "limit_status": "正常",
        "news": [
            "三季报：不良贷款率环比持平，零售信贷投放仍偏谨慎。",
            "公司公告高管任职资格获批。",
        ],
    },
}

_INDICES: dict[str, dict[str, Any]] = {
    "000001.SH": {
        "name": "上证指数",
        "price": 3286.42,
        "prev_close": 3258.10,
        "high": 3294.75,
        "low": 3255.30,
        "amount": 5124.60,  # 亿元
        "advancers": 1284,
        "decliners": 892,
    },
    "399001.SZ": {
        "name": "深证成指",
        "price": 10428.55,
        "prev_close": 10302.80,
        "high": 10461.20,
        "low": 10298.40,
        "amount": 6782.35,
        "advancers": 1652,
        "decliners": 1128,
    },
    "399006.SZ": {
        "name": "创业板指",
        "price": 2168.34,
        "prev_close": 2124.60,
        "high": 2179.80,
        "low": 2121.15,
        "amount": 2946.80,
        "advancers": 728,
        "decliners": 462,
    },
}


def normalize_symbol(symbol: str) -> str:
    """把用户可能输入的形式统一成内部 key。

    支持：600519 / sh600519 / 600519.SH / 000001.SH / 上证指数 / 深证成指 等。
    """
    raw = (symbol or "").strip().upper()
    if not raw:
        return ""
    if raw in _STOCKS or raw in _INDICES:
        return raw

    # 去掉常见前缀 / 后缀
    candidates = {raw}
    for prefix in ("SH", "SZ", "BJ"):
        if raw.startswith(prefix):
            candidates.add(raw[len(prefix):])
        if raw.endswith("." + prefix):
            candidates.add(raw[: -(len(prefix) + 1)])
        if raw.endswith(prefix):
            candidates.add(raw[: -len(prefix)])

    for candidate in candidates:
        if candidate in _STOCKS or candidate in _INDICES:
            return candidate

    # 指数别名
    if raw in {"上证", "上证指数", "沪指", "SHCOMP"}:
        return "000001.SH"
    if raw in {"深证成指", "深成指", "深指"}:
        return "399001.SZ"
    if raw in {"创业板指", "创业板"}:
        return "399006.SZ"
    return ""


def search(keyword: str) -> list[dict[str, str]]:
    """按代码或名称模糊查找股票与指数。"""
    text = (keyword or "").strip()
    if not text:
        return []
    lowered = text.lower()
    results: list[dict[str, str]] = []
    for code, item in _STOCKS.items():
        if lowered in code.lower() or text in item["name"]:
            results.append(
                {
                    "code": code,
                    "name": item["name"],
                    "kind": "stock",
                    "market": item["exchange"],
                }
            )
    for code, item in _INDICES.items():
        if lowered in code.lower() or text in item["name"]:
            results.append(
                {"code": code, "name": item["name"], "kind": "index", "market": "指数"}
            )
    return results


def get_stock(code: str) -> dict[str, Any] | None:
    item = _STOCKS.get(code)
    return dict(item) if item else None


def get_index(code: str) -> dict[str, Any] | None:
    item = _INDICES.get(code)
    return dict(item) if item else None


def all_symbols() -> list[str]:
    return [*_STOCKS.keys(), *_INDICES.keys()]


def change_pct(price: float, prev_close: float) -> float:
    if not prev_close:
        return 0.0
    return round((price - prev_close) / prev_close * 100, 2)


# --------------------------------------------------------------------------- #
# 走势图数据（K线 / 分时）
#
# 说明：下面同样是「模拟」数据，但生成方式是确定性的——同一只标的每次调用
# 得到完全相同的序列，并且最后一根K线的收盘价/最高/最低会与 _STOCKS 里的
# 实时快照严格对齐，所以图表和行情文字不会互相打架。
#
# 换成真实数据时，只需用真实接口替换 get_series() 的实现，返回同样的结构即可。
# --------------------------------------------------------------------------- #

# 各周期使用的参数：K线根数、单根收益率标准差
_PERIODS: dict[str, dict[str, Any]] = {
    "day": {"bars": 60, "sigma": 0.013, "label": "日K"},
    "week": {"bars": 48, "sigma": 0.031, "label": "周K"},
}

# 分时：A股一个交易日 240 分钟（上午 120 + 下午 120）
_INTRADAY_MINUTES = 240


def _seed_for(code: str) -> int:
    """稳定种子：不受 PYTHONHASHSEED 影响，保证跨进程结果一致。"""
    digest = hashlib.md5(code.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _trading_days(count: int, end: date) -> list[str]:
    """从 end 往前取 count 个交易日（简化：跳过周六周日）。"""
    days: list[str] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.strftime("%Y-%m-%d"))
        cursor -= timedelta(days=1)
    days.reverse()
    return days


def _resolve(code: str) -> dict[str, Any] | None:
    """统一取标的快照，附带 kind 标记。"""
    stock = _STOCKS.get(code)
    if stock:
        return {**stock, "code": code, "kind": "stock"}
    index = _INDICES.get(code)
    if index:
        return {**index, "code": code, "kind": "index"}
    return None


def _backward_closes(
    last: float, prev: float, bars: int, sigma: float, rng: random.Random
) -> list[float]:
    """从最后一根开始往回推收盘价，保证 closes[-1]=last、closes[-2]=prev。"""
    closes: list[float] = [0.0] * bars
    closes[-1] = last
    if bars >= 2:
        closes[-2] = prev
    for i in range(bars - 3, -1, -1):
        step = rng.gauss(0, sigma)
        closes[i] = closes[i + 1] / (1 + step)
    return closes


def _brownian_bridge(
    start: float, end: float, n: int, sigma: float, rng: random.Random
) -> list[float]:
    """布朗桥：路径同时锚定起点与终点，中间是随机游走（用于分时走势）。"""
    if n <= 1:
        return [end]
    walk = [0.0] * n
    for i in range(1, n):
        walk[i] = walk[i - 1] + rng.gauss(0, 1)
    tail = walk[-1]
    scale = sigma * start
    series: list[float] = []
    for i in range(n):
        ratio = i / (n - 1)
        bridged = walk[i] - ratio * tail
        value = start + (end - start) * ratio + scale * bridged
        series.append(max(value, start * 0.5))  # 防止极端值跌成负数
    series[-1] = end
    return series


def get_kline(code: str, period: str = "day") -> dict[str, Any] | None:
    """生成日K / 周K 蜡烛图数据。"""
    item = _resolve(code)
    if not item:
        return None

    period = period if period in _PERIODS else "day"
    cfg = _PERIODS[period]
    bars = cfg["bars"]
    rng = random.Random(_seed_for(f"{code}:kline:{period}"))

    price = float(item["price"])
    prev_close = float(item.get("prev_close") or price)
    closes = _backward_closes(price, prev_close, bars, cfg["sigma"], rng)
    end = date.fromisoformat(AS_OF)
    if period == "week":
        dates = [
            (end - timedelta(weeks=bars - 1 - i)).strftime("%Y-%m-%d")
            for i in range(bars)
        ]
    else:
        dates = _trading_days(bars, end)

    base_volume = float(item.get("volume") or 0) or float(item.get("amount") or 5000) * 100
    candles: list[dict[str, Any]] = []
    for i in range(bars):
        close = closes[i]
        prev = closes[i - 1] if i > 0 else close * (1 - rng.gauss(0, 0.004))
        if i == bars - 1:
            # 最后一根与实时快照严格对齐
            open_ = float(item.get("open") or prev)
            high = float(item.get("high") or max(open_, close))
            low = float(item.get("low") or min(open_, close))
            volume = float(item.get("volume") or base_volume)
        else:
            open_ = prev * (1 + rng.gauss(0, 0.004))
            span_hi = abs(rng.gauss(0, 0.006))
            span_lo = abs(rng.gauss(0, 0.006))
            high = max(open_, close) * (1 + span_hi)
            low = min(open_, close) * (1 - span_lo)
            volume = base_volume * (0.55 + rng.random() * 0.95)
        candles.append(
            {
                "date": dates[i],
                "open": round(open_, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": round(volume, 2),
            }
        )

    return {
        "symbol": code,
        "name": item["name"],
        "kind": item["kind"],
        "period": period,
        "period_label": cfg["label"],
        "prev_close": round(prev_close, 2),
        "price": round(price, 2),
        "change_pct": change_pct(price, prev_close),
        "candles": candles,
        "as_of": AS_OF,
        "market_status": MARKET_STATUS,
    }


def get_intraday(code: str) -> dict[str, Any] | None:
    """生成当日分时数据（240 个分钟点）。"""
    item = _resolve(code)
    if not item:
        return None

    rng = random.Random(_seed_for(f"{code}:min"))
    price = float(item["price"])
    prev_close = float(item.get("prev_close") or price)
    open_ = float(item.get("open") or prev_close * (1 + rng.gauss(0, 0.003)))

    # 从开盘价到现价的分时路径，两端都锚定
    closes = _brownian_bridge(open_, price, _INTRADAY_MINUTES, 0.0012, rng)

    points: list[dict[str, Any]] = []
    cumulative_amount = 0.0
    cumulative_volume = 0.0
    base_volume = (float(item.get("volume") or 0) or 30000) / _INTRADAY_MINUTES
    for i in range(_INTRADAY_MINUTES):
        # 上午 09:31-11:30（120 根）、下午 13:01-15:00（120 根），中间跳过午休
        if i < 120:
            total_minutes = 9 * 60 + 30 + (i + 1)
        else:
            total_minutes = 13 * 60 + (i - 120 + 1)
        volume = base_volume * (0.6 + rng.random() * 0.9)
        cumulative_volume += volume
        cumulative_amount += volume * closes[i]
        avg = cumulative_amount / cumulative_volume if cumulative_volume else closes[i]
        points.append(
            {
                "time": f"{total_minutes // 60:02d}:{total_minutes % 60:02d}",
                "price": round(closes[i], 2),
                "avg": round(avg, 2),
                "volume": round(volume, 2),
            }
        )

    return {
        "symbol": code,
        "name": item["name"],
        "kind": item["kind"],
        "period": "min",
        "period_label": "分时",
        "prev_close": round(prev_close, 2),
        "price": round(price, 2),
        "open": round(open_, 2),
        "change_pct": change_pct(price, prev_close),
        "points": points,
        "as_of": AS_OF,
        "market_status": MARKET_STATUS,
    }


def get_series(code: str, period: str = "day") -> dict[str, Any] | None:
    """图表数据统一入口。period: day | week | min。"""
    normalized = (period or "day").strip().lower()
    if normalized in {"min", "minute", "intraday", "分时"}:
        return get_intraday(code)
    if normalized in {"week", "weekly", "周k", "周K"}:
        return get_kline(code, "week")
    return get_kline(code, "day")


# --------------------------------------------------------------------------- #
# 行业板块（模拟数据）
# --------------------------------------------------------------------------- #

_SECTORS: dict[str, dict[str, Any]] = {
    "白酒": {"change_pct": 1.85, "turnover": 286.4, "leader": "贵州茅台", "leader_pct": 1.63,
             "advancers": 12, "decliners": 6, "note": "高端白酒批价企稳"},
    "锂电池": {"change_pct": -1.92, "turnover": 412.7, "leader": "宁德时代", "leader_pct": -2.47,
               "advancers": 8, "decliners": 21, "note": "储能需求预期分歧加大"},
    "汽车整车": {"change_pct": 2.31, "turnover": 358.9, "leader": "比亚迪", "leader_pct": 3.17,
                 "advancers": 18, "decliners": 7, "note": "月度销量数据超预期"},
    "保险": {"change_pct": -0.64, "turnover": 92.3, "leader": "中国平安", "leader_pct": -0.81,
             "advancers": 3, "decliners": 4, "note": "长端利率下行压制估值"},
    "银行": {"change_pct": 0.42, "turnover": 174.6, "leader": "招商银行", "leader_pct": 1.39,
             "advancers": 26, "decliners": 15, "note": "净息差环比企稳"},
    "半导体": {"change_pct": 3.66, "turnover": 528.1, "leader": "中芯国际", "leader_pct": 3.65,
               "advancers": 41, "decliners": 9, "note": "成熟制程稼动率回升"},
    "证券": {"change_pct": 5.42, "turnover": 486.2, "leader": "东方财富", "leader_pct": 5.45,
             "advancers": 38, "decliners": 2, "note": "市场成交放量带动"},
    "医药生物": {"change_pct": -1.18, "turnover": 341.5, "leader": "恒瑞医药", "leader_pct": -0.92,
                 "advancers": 22, "decliners": 46, "note": "集采预期扰动"},
    "光伏设备": {"change_pct": -2.74, "turnover": 297.8, "leader": "隆基绿能", "leader_pct": -3.05,
                 "advancers": 6, "decliners": 32, "note": "组件价格继续承压"},
    "房地产": {"change_pct": 0.96, "turnover": 203.4, "leader": "万科A", "leader_pct": 1.42,
               "advancers": 31, "decliners": 18, "note": "政策预期回暖"},
}


def _sector_row(name: str, item: dict[str, Any]) -> dict[str, Any]:
    """补齐 code / total 等字段，与真实数据源结构保持一致。"""
    adv = item.get("advancers")
    dec = item.get("decliners")
    total = (adv + dec) if isinstance(adv, int) and isinstance(dec, int) else None
    return {"name": name, "code": f"MOCK-{name}", "total": total, **item}


def list_sectors() -> list[dict[str, Any]]:
    """返回全部板块，按涨跌幅从高到低排序。"""
    rows = [_sector_row(name, item) for name, item in _SECTORS.items()]
    rows.sort(key=lambda r: r["change_pct"], reverse=True)
    return rows


def get_sector(keyword: str) -> dict[str, Any] | None:
    """按板块名称或关键词查找板块。"""
    text = (keyword or "").strip()
    if not text:
        return None
    if text in _SECTORS:
        return _sector_row(text, _SECTORS[text])
    lowered = text.lower()
    for name, item in _SECTORS.items():
        if lowered in name.lower() or name in text:
            return _sector_row(name, item)
        if text in item.get("note", ""):
            return _sector_row(name, item)
    return None


def sector_overview(limit: int = 5) -> dict[str, Any]:
    """板块涨跌概览：涨幅榜 / 跌幅榜 各 limit 个。"""
    rows = list_sectors()
    return {
        "top_gainers": rows[:limit],
        "top_losers": list(reversed(rows[-limit:])),
        "total": len(rows),
        "advancing": sum(1 for r in rows if r["change_pct"] > 0),
        "declining": sum(1 for r in rows if r["change_pct"] < 0),
    }


# --------------------------------------------------------------------------- #
# provider 元信息
# --------------------------------------------------------------------------- #

PROVIDER_NAME = "mock"
IS_LIVE = False
SOURCE_DESCRIPTION = "本地模拟数据（非实时行情）"


def get_news(code: str) -> list[str]:
    """个股近期消息（模拟数据里直接内置在标的信息中）。"""
    item = _STOCKS.get(code)
    if not item:
        return []
    return list(item.get("news") or [])

