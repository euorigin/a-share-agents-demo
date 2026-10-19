"""数据源共用工具：代码归一、市场前缀、板块归属。

统一约定的「canonical 代码」形式：
  - 个股：6 位数字，如 "600030"
  - 指数：6 位数字 + 市场后缀，如 "000001.SH" / "399001.SZ" / "399006.SZ"
    （必须带后缀，否则无法区分「上证指数 000001」和「平安银行 000001」）
"""

from __future__ import annotations

# 三大指数及其别名
INDEX_ALIASES: dict[str, list[str]] = {
    "000001.SH": ["上证指数", "上证", "沪指", "上证综指", "上证综合指数", "sh000001", "SHCOMP"],
    "399001.SZ": ["深证成指", "深成指", "深指", "深证指数", "sz399001"],
    "399006.SZ": ["创业板指", "创业板指数", "创业板", "sz399006"],
}

MAIN_INDICES: list[str] = ["000001.SH", "399001.SZ", "399006.SZ"]


def strip_market(code: str) -> str:
    """去掉 sh/sz/bj 前缀与 .SH/.SZ/.BJ 后缀，返回纯 6 位部分。"""
    raw = (code or "").strip().upper()
    for prefix in ("SH", "SZ", "BJ"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
        if raw.endswith("." + prefix):
            raw = raw[: -(len(prefix) + 1)]
    return raw.strip(".")


def market_prefix(canonical: str) -> str:
    """canonical 代码 -> 腾讯行情用的市场前缀 sh / sz / bj。"""
    raw = (canonical or "").strip().upper()
    for prefix, suffix in (("sh", ".SH"), ("sz", ".SZ"), ("bj", ".BJ")):
        if raw.endswith(suffix):
            return prefix
    bare = strip_market(raw)
    if bare.startswith(("60", "68", "90", "11", "13", "50", "51", "52")):
        return "sh"
    if bare.startswith(("00", "30", "20", "12", "15", "16", "18")):
        return "sz"
    if bare.startswith(("43", "83", "87", "88", "92")):
        return "bj"
    return "sh"


def tencent_symbol(canonical: str) -> str:
    """canonical 代码 -> 腾讯 symbol，如 sh600030 / sh000001。"""
    return f"{market_prefix(canonical)}{strip_market(canonical)}"


def exchange_of(canonical: str) -> str:
    """交易所 / 市场名称。"""
    if canonical in INDEX_ALIASES:
        return "指数"
    return {"sh": "上交所", "sz": "深交所", "bj": "北交所"}[market_prefix(canonical)]


def board_of(canonical: str) -> str:
    """板块归属。"""
    if canonical in INDEX_ALIASES:
        return "指数"
    bare = strip_market(canonical)
    if canonical.endswith(".BJ") or bare.startswith(("43", "83", "87", "88", "92")):
        return "北交所"
    if bare.startswith("68"):
        return "科创板"
    if bare.startswith("30"):
        return "创业板"
    return "主板"


def is_index(canonical: str) -> bool:
    return canonical in INDEX_ALIASES


def resolve_index_alias(text: str) -> str:
    """把「上证指数 / 沪指 / sh000001」等解析成 canonical 指数代码，解析不到返回 ""。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper in INDEX_ALIASES:
        return upper
    for canonical, aliases in INDEX_ALIASES.items():
        for alias in aliases:
            if raw == alias or upper == alias.upper():
                return canonical
    # 形如 000001.SH / sh000001
    for canonical in INDEX_ALIASES:
        if upper == canonical or upper == tencent_symbol(canonical).upper():
            return canonical
    return ""


def canonical_from_code(code: str, market_num: str = "") -> str:
    """把 6 位代码 + 东财 MktNum 转成 canonical 代码。"""
    bare = strip_market(code)
    if len(bare) != 6 or not bare.isdigit():
        return ""
    # 指数：上证 000001 / 深证 399xxx
    if bare == "000001" and market_num in ("1", ""):
        return "000001.SH"
    if bare.startswith("399") and bare in ("399001", "399006"):
        return f"{bare}.SZ"
    if bare.startswith("399"):
        return f"{bare}.SZ"
    if market_num == "1":
        return f"{bare}.SH" if bare.startswith(("60", "68", "90")) else bare
    if market_num == "0":
        return bare
    return bare
