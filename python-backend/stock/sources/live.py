"""真实行情数据源（live provider）——全部使用免 token 的公开接口。

分工：
  - 行情快照 / 日K / 周K / 分时：腾讯（qt.gtimg.cn、web.ifzq.gtimg.cn）
  - 代码搜索 / 行业板块 / 个股公告：东方财富

设计约定：
  - 网络或接口异常时**直接抛出**，由上层 `data.py` 决定是否回退到模拟数据。
  - 唯一例外是 `get_news()`：公告属于非关键信息，失败时返回空列表，
    避免「行情正常但公告接口抖动」导致整轮查询退化。

为什么不用 tushare：其免费额度不提供实时行情（实时需要较高积分），
且必须先注册拿 token；而本文件用的接口零配置即可用。
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from . import base

PROVIDER_NAME = "live"
IS_LIVE = True

_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}
# 东财 suggest 接口需要一个公开的静态 token（官网前端同款）
_EM_SUGGEST_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"

_TIMEOUT = 8
_TRIES = 3


def _http(url: str, encoding: str = "utf-8", referer: str | None = None) -> str:
    """带重试的 GET。失败抛最后一次异常。"""
    headers = dict(_UA)
    if referer:
        headers["Referer"] = referer
    last: Exception | None = None
    for attempt in range(_TRIES):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return resp.read().decode(encoding, "replace")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.5 * (attempt + 1))
    raise last if last else RuntimeError("request failed")


def _http_json(url: str, referer: str | None = None) -> Any:
    return json.loads(_http(url, referer=referer))


def _f(value: Any) -> float | None:
    """把接口里的数字（可能是字符串、'-'、''）转成 float，转不了返回 None。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# 行情快照（腾讯）
# --------------------------------------------------------------------------- #

# 腾讯行情字段下标（v_sh600030="1~名称~代码~现价~昨收~今开~..."）
_T_NAME, _T_CODE, _T_PRICE, _T_PREV, _T_OPEN = 1, 2, 3, 4, 5
_T_HIGH, _T_LOW = 33, 34
_T_VOLUME, _T_AMOUNT = 36, 37  # 手 / 万元
_T_TURNOVER, _T_PE = 38, 39
_T_AMPLITUDE, _T_FLOAT_CAP, _T_TOTAL_CAP, _T_PB = 43, 44, 45, 46
_T_LIMIT_UP, _T_LIMIT_DOWN = 47, 48


def _fetch_tencent_quote(canonical: str) -> list[str] | None:
    symbol = base.tencent_symbol(canonical)
    text = _http(f"https://qt.gtimg.cn/q={symbol}", encoding="gbk")
    if '="' not in text:
        return None
    body = text.split('="', 1)[1].rstrip('";\n\r ')
    fields = body.split("~")
    return fields if len(fields) > _T_LIMIT_DOWN else None


def _limit_status(price: float | None, limit_up: float | None, limit_down: float | None) -> str:
    if price is None:
        return "未知"
    if limit_up and limit_up > 0 and price >= limit_up - 1e-6:
        return "涨停"
    if limit_down and limit_down > 0 and price <= limit_down + 1e-6:
        return "跌停"
    return "正常"


def get_stock(code: str) -> dict[str, Any] | None:
    """个股快照。code 为 canonical 6 位代码。"""
    if base.is_index(code):
        return None
    fields = _fetch_tencent_quote(code)
    if not fields:
        return None

    price = _f(fields[_T_PRICE])
    prev_close = _f(fields[_T_PREV])
    if price is None or not fields[_T_NAME]:
        return None

    amount_wan = _f(fields[_T_AMOUNT])
    return {
        "name": fields[_T_NAME],
        "exchange": base.exchange_of(code),
        "board": base.board_of(code),
        "industry": "",  # 腾讯快照不含行业，留空由工具层省略
        "price": price,
        "prev_close": prev_close or price,
        "open": _f(fields[_T_OPEN]) or price,
        "high": _f(fields[_T_HIGH]) or price,
        "low": _f(fields[_T_LOW]) or price,
        "volume": int(_f(fields[_T_VOLUME]) or 0),
        "amount": round(amount_wan / 10000, 2) if amount_wan else 0.0,  # 万元 -> 亿元
        "turnover_rate": _f(fields[_T_TURNOVER]) or 0.0,
        "pe_ttm": _f(fields[_T_PE]) or 0.0,
        "pb": _f(fields[_T_PB]) or 0.0,
        "market_cap": _f(fields[_T_TOTAL_CAP]) or 0.0,
        "limit_status": _limit_status(price, _f(fields[_T_LIMIT_UP]), _f(fields[_T_LIMIT_DOWN])),
    }


def get_index(code: str) -> dict[str, Any] | None:
    """指数快照。advancers / decliners 腾讯不提供，置 None 由格式化层省略。"""
    if not base.is_index(code):
        return None
    fields = _fetch_tencent_quote(code)
    if not fields:
        return None

    price = _f(fields[_T_PRICE])
    prev_close = _f(fields[_T_PREV])
    if price is None or not fields[_T_NAME]:
        return None

    amount_wan = _f(fields[_T_AMOUNT])
    return {
        "name": fields[_T_NAME],
        "price": price,
        "prev_close": prev_close or price,
        "high": _f(fields[_T_HIGH]) or price,
        "low": _f(fields[_T_LOW]) or price,
        "open": _f(fields[_T_OPEN]) or price,
        "volume": int(_f(fields[_T_VOLUME]) or 0),
        "amount": round(amount_wan / 10000, 2) if amount_wan else 0.0,
        "advancers": None,
        "decliners": None,
    }


def change_pct(price: float, prev_close: float) -> float:
    if not prev_close:
        return 0.0
    return round((price - prev_close) / prev_close * 100, 2)


# --------------------------------------------------------------------------- #
# 代码搜索 / 归一（东方财富 suggest）
# --------------------------------------------------------------------------- #

_KIND_BY_TYPE = {"沪A": "stock", "深A": "stock", "京A": "stock", "指数": "index"}
_MARKET_BY_TYPE = {"沪A": "上交所", "深A": "深交所", "京A": "北交所", "指数": "指数"}


def _suggest(keyword: str) -> list[dict[str, Any]]:
    url = (
        "https://searchapi.eastmoney.com/api/suggest/get?input="
        + urllib.parse.quote(keyword)
        + f"&type=14&count=10&token={_EM_SUGGEST_TOKEN}"
    )
    data = _http_json(url, referer="https://quote.eastmoney.com/")
    return ((data.get("QuotationCodeTable") or {}).get("Data")) or []


def search(keyword: str) -> list[dict[str, str]]:
    """按名称或代码搜索 A股个股与指数。"""
    text = (keyword or "").strip()
    if not text:
        return []
    results: list[dict[str, str]] = []
    seen: set[str] = set()

    # 指数别名优先
    index_hit = base.resolve_index_alias(text)
    if index_hit:
        name = _index_name(index_hit)
        results.append({"code": index_hit, "name": name, "kind": "index", "market": "指数"})
        seen.add(index_hit)

    for item in _suggest(text):
        type_name = item.get("SecurityTypeName") or ""
        kind = _KIND_BY_TYPE.get(type_name)
        if kind is None:
            continue
        code = item.get("Code") or ""
        canonical = base.canonical_from_code(code, str(item.get("MktNum") or ""))
        if not canonical or canonical in seen:
            continue
        if base.is_index(canonical) and canonical not in base.INDEX_ALIASES:
            continue
        seen.add(canonical)
        results.append(
            {
                "code": canonical,
                "name": item.get("Name") or canonical,
                "kind": "index" if base.is_index(canonical) else "stock",
                "market": "指数" if base.is_index(canonical) else _MARKET_BY_TYPE.get(type_name, ""),
            }
        )
    return results


def _index_name(canonical: str) -> str:
    return {
        "000001.SH": "上证指数",
        "399001.SZ": "深证成指",
        "399006.SZ": "创业板指",
    }.get(canonical, canonical)


def normalize_symbol(symbol: str) -> str:
    """把用户输入统一成 canonical 代码。

    支持：600030 / sh600030 / 600030.SH / 000001.SH / 上证指数 / 中信证券（走一次搜索）。
    """
    raw = (symbol or "").strip()
    if not raw:
        return ""

    index_hit = base.resolve_index_alias(raw)
    if index_hit:
        return index_hit

    bare = base.strip_market(raw)
    if len(bare) == 6 and bare.isdigit():
        # 带 .SH/.SZ/.BJ 后缀时尊先后缀
        upper = raw.upper()
        for suffix in (".SH", ".SZ", ".BJ"):
            if upper.endswith(suffix):
                return f"{bare}{suffix}"
        return bare

    # 名称：交给搜索接口解析（取最佳匹配）
    matches = search(raw)
    if matches:
        # 优先完全同名
        for item in matches:
            if item["name"] == raw:
                return item["code"]
        return matches[0]["code"]
    return ""


# --------------------------------------------------------------------------- #
# K线 / 分时（腾讯）
# --------------------------------------------------------------------------- #

_PERIOD_KEY = {"day": "day", "week": "week"}
_BAR_COUNT = {"day": 60, "week": 48}
_PERIOD_LABEL = {"day": "日K", "week": "周K"}


def _fetch_kline(canonical: str, period: str) -> tuple[list[list[str]], dict[str, Any]]:
    symbol = base.tencent_symbol(canonical)
    count = _BAR_COUNT[period]
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={symbol},{_PERIOD_KEY[period]},,,{count},qfq"
    )
    data = _http_json(url, referer="https://gu.qq.com/")
    node = (data.get("data") or {}).get(symbol) or {}
    rows = node.get(f"qfq{period}") or node.get(period) or []
    return rows, node


def get_kline(code: str, period: str = "day") -> dict[str, Any] | None:
    period = period if period in _PERIOD_KEY else "day"
    rows, node = _fetch_kline(code, period)
    candles: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 6:
            continue
        open_, close, high, low, volume = (_f(row[1]), _f(row[2]), _f(row[3]), _f(row[4]), _f(row[5]))
        if None in (open_, close, high, low):
            continue
        candles.append(
            {
                "date": row[0],
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume or 0.0,
            }
        )
    if not candles:
        return None

    quote = get_stock(code) or get_index(code) or {}
    price = quote.get("price") or candles[-1]["close"]
    prev_close = candles[-2]["close"] if len(candles) >= 2 else (quote.get("prev_close") or price)
    name = quote.get("name") or node.get("qt", {}).get(base.tencent_symbol(code), [None, code])[1] or code

    return {
        "symbol": code,
        "name": name,
        "kind": "index" if base.is_index(code) else "stock",
        "period": period,
        "period_label": _PERIOD_LABEL[period],
        "prev_close": round(prev_close, 2),
        "price": round(price, 2),
        "change_pct": change_pct(price, prev_close),
        "candles": candles,
        "as_of": AS_OF,
        "market_status": MARKET_STATUS,
    }


def get_intraday(code: str) -> dict[str, Any] | None:
    """当日分时。腾讯返回含盘后（15:00-15:30），这里只保留连续竞价时段。"""
    symbol = base.tencent_symbol(code)
    data = _http_json(
        f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={symbol}",
        referer="https://gu.qq.com/",
    )
    node = (data.get("data") or {}).get(symbol) or {}
    block = node.get("data") or {}
    rows = block.get("data") or []
    if not rows:
        return None

    quote = get_stock(code) or get_index(code) or {}
    prev_close = _f(block.get("preclose")) or quote.get("prev_close")
    if not prev_close:
        return None

    points: list[dict[str, Any]] = []
    last_cum_volume = 0.0
    for row in rows:
        parts = str(row).split()
        if len(parts) < 4:
            continue
        raw_time = parts[0]
        if not (("0930" <= raw_time <= "1130") or ("1300" <= raw_time <= "1500")):
            continue
        price = _f(parts[1])
        cum_volume = _f(parts[2]) or 0.0
        cum_amount = _f(parts[3]) or 0.0
        if price is None:
            continue
        avg = cum_amount / (cum_volume * 100) if cum_volume else price
        points.append(
            {
                "time": f"{raw_time[:2]}:{raw_time[2:]}",
                "price": round(price, 3),
                "avg": round(avg, 3),
                "volume": max(0.0, round(cum_volume - last_cum_volume, 2)),
            }
        )
        last_cum_volume = cum_volume

    if not points:
        return None

    return {
        "symbol": code,
        "name": quote.get("name") or code,
        "kind": "index" if base.is_index(code) else "stock",
        "period": "min",
        "period_label": "分时",
        "prev_close": round(prev_close, 3),
        "price": round(points[-1]["price"], 3),
        "open": points[0]["price"],
        "change_pct": change_pct(points[-1]["price"], prev_close),
        "points": points,
        "as_of": AS_OF,
        "market_status": MARKET_STATUS,
    }


def get_series(code: str, period: str = "day") -> dict[str, Any] | None:
    normalized = (period or "day").strip().lower()
    if normalized in {"min", "minute", "intraday", "分时", "分时图", "分钟"}:
        return get_intraday(code)
    if normalized in {"week", "weekly", "周k", "周K", "周线"}:
        return get_kline(code, "week")
    return get_kline(code, "day")


# --------------------------------------------------------------------------- #
# 行业板块
# --------------------------------------------------------------------------- #
# 主源用腾讯板块排行（稳），兜底用东方财富 clist。
# 板块分三个层级，用途不同：
#   hy  申万一级行业（31 个）——用于「板块概览」的涨幅/跌幅榜
#   hy2 申万二级行业（124 个）——用户口语里的「白酒」「半导体」「证券」多在这一层
#   gn  概念板块（200 个）——「锂电池」「芯片」等题材
# 查具体板块时按 hy -> hy2 -> gn 顺序匹配，保证常见叫法都查得到。

_QQ_RANK = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank"
_EM_CLIST = "https://push2delay.eastmoney.com/api/qt/clist/get"
_EM_SECTOR_FS = urllib.parse.quote("m:90+t:2")
_EM_SECTOR_FIELDS = "f12,f14,f3,f104,f105,f128,f136"


def _qq_row(item: dict[str, Any]) -> dict[str, Any] | None:
    """把腾讯板块排行的一条记录转成统一结构。"""
    pct = _f(item.get("zdf"))
    if pct is None:
        return None
    leader = item.get("lzg") or {}
    turnover_wan = _f(item.get("turnover"))  # 单位：万元
    # zgb 形如 "上涨家数/总家数"，如 "102/122"
    adv = total = None
    zgb = str(item.get("zgb") or "")
    if "/" in zgb:
        left, right = zgb.split("/", 1)
        adv, total = _f(left), _f(right)
    return {
        "name": item.get("name") or "",
        "code": item.get("code") or "",
        "change_pct": pct,
        "advancers": int(adv) if adv is not None else None,
        "decliners": None,  # 腾讯只给「上涨/总数」，下跌家数无法精确拆出
        "total": int(total) if total is not None else None,
        "leader": leader.get("name") or "",
        "leader_pct": _f(leader.get("zdf")),
        "turnover": round(turnover_wan / 10000, 2) if turnover_wan else None,  # 万元 -> 亿元
        "note": "",
    }


def _qq_sectors(board_type: str) -> list[dict[str, Any]]:
    """腾讯板块排行，按涨跌幅降序。"""
    data = _http_json(
        f"{_QQ_RANK}?board_type={board_type}&sort_type=price&direct=down&offset=0&count=200",
        referer="https://gu.qq.com/",
    )
    raw = ((data.get("data") or {}).get("rank_list")) or []
    rows = [row for row in (_qq_row(item) for item in raw) if row]
    if not rows:
        raise RuntimeError(f"腾讯 {board_type} 板块数据为空")
    rows.sort(key=lambda r: r["change_pct"], reverse=True)
    return rows


def _em_sectors() -> list[dict[str, Any]]:
    """东方财富行业板块（兜底）。"""
    url = (
        f"{_EM_CLIST}?pn=1&pz=200&po=1&np=1&fltt=2&invt=2&fid=f3"
        f"&fs={_EM_SECTOR_FS}&fields={_EM_SECTOR_FIELDS}"
    )
    data = _http_json(url, referer="https://quote.eastmoney.com/")
    diff = ((data.get("data") or {}).get("diff")) or []
    rows: list[dict[str, Any]] = []
    for item in diff:
        pct = _f(item.get("f3"))
        if pct is None:
            continue
        adv = item.get("f104")
        dec = item.get("f105")
        total = (adv + dec) if isinstance(adv, int) and isinstance(dec, int) else None
        rows.append(
            {
                "name": item.get("f14") or "",
                "code": item.get("f12") or "",
                "change_pct": pct,
                "advancers": adv,
                "decliners": dec,
                "total": total,
                "leader": item.get("f128") or "",
                "leader_pct": _f(item.get("f136")),
                "turnover": None,  # 该接口不返回板块成交额
                "note": "",
            }
        )
    if not rows:
        raise RuntimeError("东方财富板块数据为空")
    rows.sort(key=lambda r: r["change_pct"], reverse=True)
    return rows


def list_sectors() -> list[dict[str, Any]]:
    """全部行业板块（申万一级），按涨跌幅降序。腾讯为主、东财兜底。"""
    last: Exception | None = None
    for fetch in (_qq_sectors, _em_sectors):
        try:
            if fetch is _qq_sectors:
                return fetch("hy")
            return fetch()
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise last if last else RuntimeError("板块数据获取失败")


def get_sector(keyword: str) -> dict[str, Any] | None:
    """按板块名匹配：申万一级 -> 申万二级 -> 概念板块。"""
    text = (keyword or "").strip()
    if not text:
        return None
    for board_type in ("hy", "hy2", "gn"):
        try:
            rows = _qq_sectors(board_type)
        except Exception:  # noqa: BLE001
            continue
        for row in rows:
            if text == row["name"] or text in row["name"] or row["name"] in text:
                return row
    return None


def sector_overview(limit: int = 5) -> dict[str, Any]:
    rows = list_sectors()
    return {
        "top_gainers": rows[:limit],
        "top_losers": list(reversed(rows[-limit:])),
        "total": len(rows),
        "advancing": sum(1 for r in rows if r["change_pct"] > 0),
        "declining": sum(1 for r in rows if r["change_pct"] < 0),
    }


# --------------------------------------------------------------------------- #
# 个股公告（东方财富）
# --------------------------------------------------------------------------- #


def get_news(code: str) -> list[str]:
    """个股近期公告。公告是非关键信息，失败时返回空列表而不抛异常。"""
    if base.is_index(code):
        return []
    bare = base.strip_market(code)
    try:
        data = _http_json(
            "https://np-anotice-stock.eastmoney.com/api/security/ann"
            f"?page_size=5&page_index=1&ann_type=A&client_source=web&stock_list={bare}",
            referer="https://data.eastmoney.com/",
        )
    except Exception:  # noqa: BLE001 - 公告失败不影响主流程
        return []

    rows = ((data.get("data") or {}).get("list")) or []
    out: list[str] = []
    for item in rows:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        date = (item.get("notice_date") or "")[:10]
        out.append(f"{date} {title}" if date else title)
    return out


# --------------------------------------------------------------------------- #
# 元信息
# --------------------------------------------------------------------------- #

MARKET_STATUS = "实时行情（腾讯/东方财富公开接口，可能有延迟）"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# 兼容工具层按属性读取；每次访问都取当天日期
AS_OF = _today()
SOURCE_DESCRIPTION = "腾讯/东方财富的公开行情接口（可能有延迟）"
