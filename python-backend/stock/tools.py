"""A股助手使用的全部工具。

数据统一走 data.py 门面：默认优先真实行情（腾讯/东方财富公开接口），
网络异常时自动回退本地模拟数据；用 STOCK_DATA_SOURCE=live|mock 可强制指定。
工具层不关心数据来自哪里，只依赖 data.py 暴露的同名接口。

工具按职责分成四组，分别挂给不同的 Agent：
  - 行情：search_stock / get_stock_quote / get_stock_chart
  - 大盘板块：get_market_overview / get_sector_overview
  - 消息：get_stock_news
  - 规则与自选：stock_faq_lookup / add_to_watchlist / remove_from_watchlist / list_watchlist
"""

from __future__ import annotations

from agents import RunContextWrapper, function_tool
from chatkit.types import ProgressUpdateEvent

from . import data, faq
from .context import StockAgentChatContext


def _fmt_pct(value: float) -> str:
    return f"{value:+.2f}%"


async def _notify(context: RunContextWrapper[StockAgentChatContext], text: str) -> None:
    """把中间状态推给前端（聊天面板底部状态行）。"""
    try:
        await context.context.stream(ProgressUpdateEvent(text=text))
    except Exception:
        # 状态推送失败不应影响主流程
        pass


def _source_note() -> str:
    return f"（数据说明：{data.MARKET_STATUS}，{data.AS_OF}）"


def _describe(stock: dict, code: str) -> str:
    """标的抬头。真实数据源不含行业字段，为空时自动省略。"""
    market = f"{stock.get('exchange', '')}{stock.get('board', '')}".strip()
    parts = [p for p in (market, stock.get("industry") or "") if p]
    tail = "，".join(parts)
    return f"{stock['name']}（{code}，{tail}）" if tail else f"{stock['name']}（{code}）"


# --------------------------------------------------------------------------- #
# 行情
# --------------------------------------------------------------------------- #


@function_tool(
    name_override="search_stock",
    description_override="按股票代码或名称关键字搜索 A股个股与指数，返回代码、名称、所属市场。",
)
async def search_stock(
    context: RunContextWrapper[StockAgentChatContext], keyword: str
) -> str:
    """按代码或名称模糊搜索标的。"""
    await _notify(context, f"正在搜索「{keyword}」…")
    matches = data.search(keyword)
    if not matches:
        return (
            f"未找到与「{keyword}」匹配的标的。可尝试更完整的名称或 6 位代码，"
            "例如：贵州茅台、600519、宁德时代、上证指数。"
        )
    lines = [
        f"{item['code']} {item['name']}（{item['market']}，{'指数' if item['kind'] == 'index' else '个股'}）"
        for item in matches
    ]
    return "匹配结果：\n" + "\n".join(lines)


@function_tool(
    name_override="get_stock_quote",
    description_override=(
        "查询个股或指数的最新行情：现价、涨跌幅、成交额、换手率、市盈率、总市值等。"
        "支持 6 位代码（600519）、带市场后缀（600519.SH）或指数代码（000001.SH）。"
    ),
)
async def get_stock_quote(
    context: RunContextWrapper[StockAgentChatContext], symbol: str
) -> str:
    """查询实时（演示数据）行情。"""
    await _notify(context, f"正在查询 {symbol} 的行情…")
    code = data.normalize_symbol(symbol)

    if not code:
        matches = data.search(symbol)
        if matches:
            hint = "、".join(f"{m['code']} {m['name']}" for m in matches[:5])
            return f"「{symbol}」不是有效的标的代码，可能你想找的是：{hint}。请确认后重新查询。"
        return f"未找到标的「{symbol}」，请确认代码或名称是否正确。"

    state = context.context.state

    index_item = data.get_index(code)
    if index_item:
        pct = data.change_pct(index_item["price"], index_item["prev_close"])
        state.stock_code = code
        state.stock_name = index_item["name"]
        state.stock_price = index_item["price"]
        state.stock_change_pct = pct
        await _notify(context, f"已获取{index_item['name']}行情")
        lines = [
            f"{index_item['name']}（{code}）",
            f"最新点位：{index_item['price']:.2f}（{_fmt_pct(pct)}）",
            f"昨收：{index_item['prev_close']:.2f}　最高：{index_item['high']:.2f}　最低：{index_item['low']:.2f}",
            f"成交额：{index_item.get('amount') or 0:.2f} 亿元",
        ]
        advancers = index_item.get("advancers")
        decliners = index_item.get("decliners")
        if advancers is not None and decliners is not None:
            lines.append(f"上涨家数 {advancers} / 下跌家数 {decliners}")
        lines.append(_source_note())
        return "\n".join(lines)

    stock = data.get_stock(code)
    if not stock:
        return f"未找到标的「{symbol}」，请确认代码或名称是否正确。"

    pct = data.change_pct(stock["price"], stock["prev_close"])
    state.stock_code = code
    state.stock_name = stock["name"]
    state.stock_price = stock["price"]
    state.stock_change_pct = pct
    await _notify(context, f"已获取{stock['name']}行情")

    lines = [
        _describe(stock, code),
        f"最新价：{stock['price']:.2f} 元（{_fmt_pct(pct)}，昨收 {stock['prev_close']:.2f}）",
        f"今开 {stock['open']:.2f}　最高 {stock['high']:.2f}　最低 {stock['low']:.2f}　状态：{stock['limit_status']}",
        f"成交量：{stock['volume']:,} 手　成交额：{stock['amount']:.2f} 亿元　换手率：{stock['turnover_rate']:.2f}%",
    ]
    # 真实数据源可能缺估值字段，缺什么就整段省略
    valuation = []
    if stock.get("pe_ttm"):
        valuation.append(f"市盈率(TTM)：{stock['pe_ttm']:.1f} 倍")
    if stock.get("pb"):
        valuation.append(f"市净率：{stock['pb']:.2f}")
    if stock.get("market_cap"):
        valuation.append(f"总市值：{stock['market_cap']:.2f} 亿元")
    if valuation:
        lines.append("　".join(valuation))
    lines.append(_source_note())
    return "\n".join(lines)


# 用户可能说「日K / 日线 / 周K / 分时 / 分钟」，统一映射到内部周期
_PERIOD_ALIASES: dict[str, str] = {
    "day": "day",
    "d": "day",
    "daily": "day",
    "日k": "day",
    "日K": "day",
    "日线": "day",
    "week": "week",
    "w": "week",
    "weekly": "week",
    "周k": "week",
    "周K": "week",
    "周线": "week",
    "min": "min",
    "minute": "min",
    "intraday": "min",
    "分时": "min",
    "分钟": "min",
    "分时图": "min",
}


def _normalize_period(period: str) -> str:
    key = (period or "day").strip()
    return _PERIOD_ALIASES.get(key, _PERIOD_ALIASES.get(key.lower(), "day"))


def _chart_summary(series: dict) -> str:
    """把图表数据浓缩成一段文字，供模型组织回答。"""
    name = series["name"]
    code = series["symbol"]
    pct = series["change_pct"]
    if series["period"] == "min":
        points = series["points"]
        prices = [p["price"] for p in points]
        return (
            f"{name}（{code}）分时走势：今开 {series['open']:.2f}，最新 {series['price']:.2f}"
            f"（{_fmt_pct(pct)}），盘中最高 {max(prices):.2f}、最低 {min(prices):.2f}，"
            f"均价 {points[-1]['avg']:.2f}，共 {len(points)} 个分钟点。"
        )
    candles = series["candles"]
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes5 = sum(closes[-5:]) / min(5, len(closes))
    closes10 = sum(closes[-10:]) / min(10, len(closes))
    return (
        f"{name}（{code}）{series['period_label']}数据：共 {len(candles)} 根，区间 "
        f"{candles[0]['date']} ~ {candles[-1]['date']}。最新收盘 {series['price']:.2f}"
        f"（{_fmt_pct(pct)}），区间最高 {max(highs):.2f}、最低 {min(lows):.2f}；"
        f"MA5={closes5:.2f}，MA10={closes10:.2f}。"
        f"（{data.MARKET_STATUS}，{data.AS_OF}）"
    )


@function_tool(
    name_override="get_stock_chart",
    description_override=(
        "生成个股或指数的走势图（日K / 周K / 分时）。"
        "当用户说「画一下走势」「看K线」「分时图」「最近表现怎么样」这类想看图形时调用。"
        "period 取值：day=日K（默认）、week=周K、min=分时。"
        "图表由界面自动绘制在回答下方，你只需要用一两句文字概括走势要点，"
        "不要输出 JSON、代码块或图片链接。"
    ),
)
async def get_stock_chart(
    context: RunContextWrapper[StockAgentChatContext], symbol: str, period: str = "day"
) -> str:
    """生成走势图数据，并把「要画哪张图」记到会话状态里。"""
    period_key = _normalize_period(period)
    await _notify(context, f"正在生成 {symbol} 的走势图…")

    code = data.normalize_symbol(symbol)
    if not code:
        matches = data.search(symbol)
        if matches:
            hint = "、".join(f"{m['code']} {m['name']}" for m in matches[:5])
            return f"「{symbol}」不是有效的标的代码，可能你想找的是：{hint}。请确认后重新生成。"
        return f"未找到标的「{symbol}」，请确认代码或名称是否正确。"

    series = data.get_series(code, period_key)
    if not series:
        return f"暂无 {symbol} 的走势数据。"

    # 记录到会话状态：main.py 的 /chat/simple 会据此把图表事件推给前端
    state = context.context.state
    state.stock_chart_symbol = code
    state.stock_chart_period = series["period"]
    state.stock_chart_token = (state.stock_chart_token or 0) + 1

    await _notify(context, f"已生成{series['name']}{series['period_label']}")
    return _chart_summary(series)


# --------------------------------------------------------------------------- #
# 大盘与板块
# --------------------------------------------------------------------------- #


@function_tool(
    name_override="get_market_overview",
    description_override="查询 A股大盘概况：上证指数、深证成指、创业板指的点位涨跌与两市涨跌家数。",
)
async def get_market_overview(
    context: RunContextWrapper[StockAgentChatContext],
) -> str:
    """查询大盘概况。"""
    await _notify(context, "正在获取大盘概况…")
    lines = []
    total_advancers = 0
    total_decliners = 0
    breadth_available = False
    for code in data.MAIN_INDICES:
        item = data.get_index(code)
        if not item:
            continue
        pct = data.change_pct(item["price"], item["prev_close"])
        lines.append(f"{item['name']}：{item['price']:.2f}（{_fmt_pct(pct)}）")
        advancers = item.get("advancers")
        decliners = item.get("decliners")
        if advancers is not None and decliners is not None:
            total_advancers += advancers
            total_decliners += decliners
            breadth_available = True

    if not lines:
        return "暂时无法获取大盘数据。"

    body = "A股大盘概况：\n" + "\n".join(lines)
    if breadth_available:
        body += f"\n两市合计：上涨 {total_advancers} 家 / 下跌 {total_decliners} 家"
    body += "\n" + _source_note()
    return body


@function_tool(
    name_override="get_sector_overview",
    description_override=(
        "查询行业板块涨跌情况。不传 sector 时返回涨幅榜与跌幅榜概览；"
        "传入板块名（如「白酒」「半导体」「锂电池」）时返回该板块的详细涨跌与领涨股。"
    ),
)
async def get_sector_overview(
    context: RunContextWrapper[StockAgentChatContext], sector: str = ""
) -> str:
    """查询行业板块涨跌。"""
    name = (sector or "").strip()

    if name:
        await _notify(context, f"正在查询「{name}」板块…")
        item = data.get_sector(name)
        if not item:
            available = "、".join(r["name"] for r in data.list_sectors())
            return f"没有找到「{name}」这个板块。目前收录：{available}。"
        context.context.state.sector = item["name"]
        await _notify(context, f"已获取{item['name']}板块数据")
        adv = item.get("advancers")
        dec = item.get("decliners")
        total = item.get("total")
        if adv is not None and dec is not None:
            breadth = f"（上涨 {adv} 家 / 下跌 {dec} 家）"
        elif adv is not None and total is not None:
            breadth = f"（上涨 {adv} 家 / 共 {total} 家）"
        else:
            breadth = ""
        lines = [f"{item['name']}板块：{_fmt_pct(item['change_pct'])}{breadth}"]
        if item.get("turnover"):
            lines.append(f"成交额：{item['turnover']:.2f} 亿元")
        if item.get("leader"):
            leader_pct = item.get("leader_pct")
            suffix = f"（{_fmt_pct(leader_pct)}）" if leader_pct is not None else ""
            lines.append(f"领涨股：{item['leader']}{suffix}")
        if item.get("note"):
            lines.append(f"要点：{item['note']}")
        lines.append(_source_note())
        return "\n".join(lines)

    await _notify(context, "正在获取板块概览…")
    overview = data.sector_overview(limit=5)

    def fmt(row: dict) -> str:
        leader = f"（领涨 {row['leader']}）" if row.get("leader") else ""
        return f"  {row['name']}：{_fmt_pct(row['change_pct'])}{leader}"

    gainers = "\n".join(fmt(r) for r in overview["top_gainers"])
    losers = "\n".join(fmt(r) for r in overview["top_losers"])
    return (
        f"A股行业板块概览（共 {overview['total']} 个板块，"
        f"上涨 {overview['advancing']} / 下跌 {overview['declining']}）：\n"
        f"涨幅榜：\n{gainers}\n"
        f"跌幅榜：\n{losers}\n"
        + _source_note()
    )


# --------------------------------------------------------------------------- #
# 公告与消息面
# --------------------------------------------------------------------------- #


@function_tool(
    name_override="get_stock_news",
    description_override="查询个股最近的相关公告与消息面摘要。",
)
async def get_stock_news(
    context: RunContextWrapper[StockAgentChatContext], symbol: str
) -> str:
    """查询个股消息面。"""
    await _notify(context, f"正在检索 {symbol} 的相关消息…")
    code = data.normalize_symbol(symbol)
    stock = data.get_stock(code) if code else None
    if not stock:
        return f"没有找到「{symbol}」对应的个股，暂时无法提供消息面信息。"

    news = data.get_news(code)
    if not news:
        return (
            f"{stock['name']}（{code}）近期暂无可检索到的公告或消息面信息。\n"
            "（说明：消息面来自公开公告接口，可能有延迟或遗漏，不构成投资建议。）"
        )
    body = "\n".join(f"{idx}. {text}" for idx, text in enumerate(news, start=1))
    return (
        f"{stock['name']}（{code}）近期公告与消息面：\n{body}\n"
        "以上为公开信息摘要，不构成投资建议。"
    )


# --------------------------------------------------------------------------- #
# 交易规则
# --------------------------------------------------------------------------- #


@function_tool(
    name_override="stock_faq_lookup",
    description_override=(
        "查询 A股交易规则与常识：交易时间、T+1、涨跌停限制、手续费构成、最小交易单位、"
        "ST 规则、融资融券、开户与权限、分红除权、集合竞价等。"
        "回答此类问题必须先调用这个工具，不要凭自己的知识作答。"
    ),
)
async def stock_faq_lookup(
    context: RunContextWrapper[StockAgentChatContext], question: str
) -> str:
    """从规则库中检索答案。"""
    await _notify(context, "正在检索交易规则…")
    return faq.lookup(question)


# --------------------------------------------------------------------------- #
# 自选股
# --------------------------------------------------------------------------- #


def _watchlist_lines(codes: list[str]) -> str:
    rows = []
    for code in codes:
        item = data.get_stock(code) or data.get_index(code)
        if not item:
            rows.append(f"  {code}（已失效，建议移除）")
            continue
        pct = data.change_pct(item["price"], item["prev_close"])
        rows.append(f"  {code} {item['name']}：{item['price']:.2f}（{_fmt_pct(pct)}）")
    return "\n".join(rows)


@function_tool(
    name_override="add_to_watchlist",
    description_override="把一只股票或指数加入自选股列表。已存在时不重复添加。",
)
async def add_to_watchlist(
    context: RunContextWrapper[StockAgentChatContext], symbol: str
) -> str:
    """加入自选股。"""
    await _notify(context, f"正在把 {symbol} 加入自选…")
    code = data.normalize_symbol(symbol)
    if not code:
        matches = data.search(symbol)
        if matches:
            hint = "、".join(f"{m['code']} {m['name']}" for m in matches[:5])
            return f"「{symbol}」不是一个明确的标的，可能你想找的是：{hint}。"
        return f"未找到标的「{symbol}」，请确认代码或名称。"

    state = context.context.state
    current = list(state.watchlist or [])
    item = data.get_stock(code) or data.get_index(code) or {}
    if code in current:
        return f"{item.get('name', code)}（{code}）已经在自选股里了。当前自选共 {len(current)} 只。"

    current.append(code)
    state.watchlist = current
    await _notify(context, f"已加入自选：{item.get('name', code)}")
    return (
        f"已把 {item.get('name', code)}（{code}）加入自选股。\n"
        f"当前自选股（{len(current)} 只）：\n{_watchlist_lines(current)}"
    )


@function_tool(
    name_override="remove_from_watchlist",
    description_override="把一只股票或指数从自选股列表里移除。",
)
async def remove_from_watchlist(
    context: RunContextWrapper[StockAgentChatContext], symbol: str
) -> str:
    """移除自选股。"""
    await _notify(context, f"正在从自选移除 {symbol}…")
    code = data.normalize_symbol(symbol) or symbol.strip().upper()

    state = context.context.state
    current = list(state.watchlist or [])
    if code not in current:
        if not current:
            return "当前自选股是空的，没有可移除的标的。"
        return (
            f"{symbol} 不在自选股里。当前自选股：\n{_watchlist_lines(current)}"
        )

    current.remove(code)
    state.watchlist = current
    await _notify(context, "已从自选移除")
    if not current:
        return f"已把 {symbol} 从自选股移除，当前自选股已为空。"
    return (
        f"已把 {symbol} 从自选股移除。\n"
        f"当前自选股（{len(current)} 只）：\n{_watchlist_lines(current)}"
    )


@function_tool(
    name_override="list_watchlist",
    description_override="查看当前自选股列表及各自的最新行情。",
)
async def list_watchlist(
    context: RunContextWrapper[StockAgentChatContext],
) -> str:
    """查看自选股。"""
    await _notify(context, "正在读取自选股…")
    state = context.context.state
    current = list(state.watchlist or [])
    if not current:
        return "当前自选股是空的。可以说「把宁德时代加入自选」来添加。"
    return (
        f"当前自选股（{len(current)} 只）：\n{_watchlist_lines(current)}\n"
        f"（数据说明：{data.MARKET_STATUS}，{data.AS_OF}）"
    )
