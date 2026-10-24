"""A股助手的多智能体编排。

6 个 Agent：
  Triage Agent          分诊，把请求路由给下面 5 个专家
  Stock Information     个股/指数行情、估值、走势图
  Market Overview       大盘指数与行业板块
  News and Disclosure   公告与消息面
  Trading Rules         交易规则与费用等常识
  Watchlist             自选股管理
"""

from __future__ import annotations as _annotations

import os

from agents import Agent, RunContextWrapper
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from . import data
from .context import StockAgentChatContext
from .guardrails import jailbreak_guardrail, relevance_guardrail
from .tools import (
    add_to_watchlist,
    get_market_overview,
    get_sector_overview,
    get_stock_chart,
    get_stock_news,
    get_stock_quote,
    list_watchlist,
    remove_from_watchlist,
    search_stock,
    stock_faq_lookup,
)

# 可用 .env 里的 AGENT_MODEL 覆盖，避免每次换模型都改代码
MODEL = os.environ.get("AGENT_MODEL", "gpt-4.1")

# 数据来源说明随当前数据源（真实/模拟）动态生成，避免话术与事实不符
if data.IS_LIVE:
    _DATA_NOTE = (
        "数据来源：腾讯行情与东方财富的公开接口，可能有延迟，不是交易所官方实时行情；"
        "被问到数据来源或时效时如实说明。"
    )
else:
    _DATA_NOTE = "数据来源：本地模拟数据，仅供演示，不是实时行情；被问到时如实说明。"

# 所有 Agent 共用的一段合规要求
_COMPLIANCE = (
    "合规红线：不提供投资建议、不预测涨跌、不推荐买卖。"
    "用户要求荐股或问「能不能买」时，只陈述公开数据并提示风险，不要给出买卖结论。"
    + _DATA_NOTE
    + "严禁臆测：查不到标的或查不到某个字段时，如实说明「暂未检索到」，"
    "并提示可能是名称/代码不符或该信息未覆盖；"
    "绝对不要自行推断「已退市」「已停牌」「被收购」这类结论——"
    "也包括「可能已退市」「疑似停牌」「或许已被收购」这类推测性说法，一律不要写，"
    "查不到就只陈述查不到，把判断交给用户。"
    "只有当工具返回值里明确包含该信息时才可照实转述。"
)

_EFFICIENCY = (
    "效率要求：同一轮里可以连续调用多个工具，最后最多发起一次 handoff，"
    "不要每调一个工具就停下来等用户回复。"
)


# --------------------------------------------------------------------------- #
# 1. 个股行情与走势图
# --------------------------------------------------------------------------- #


def stock_information_instructions(
    run_context: RunContextWrapper[StockAgentChatContext], agent: Agent[StockAgentChatContext]
) -> str:
    ctx = run_context.context.state
    last_symbol = ctx.stock_name or "[尚未查询]"
    last_code = ctx.stock_code or "[尚未查询]"
    return (
        f"{RECOMMENDED_PROMPT_PREFIX}\n"
        "你是「个股行情助手」，负责个股与指数的行情、估值和走势图。\n"
        "重要：接到问题后必须实际调用工具拿到数据再回答，不要在没调用任何工具的情况下"
        "只回一句「已转接」就结束。\n"
        f"1. 当前会话最近查询过的标的是 {last_symbol}（{last_code}）。用户说「它」「这只股票」时沿用该标的，"
        "不要重复追问；如果还没有查询记录，请先确认标的。\n"
        "2. 用户给名称或代码不确定时先用 search_stock 确认；给出 6 位代码时直接用 get_stock_quote。\n"
        "3. 用户想看走势、K线、分时图、近期表现（如「画一下」「看看走势」「分时怎么样」）时调用 get_stock_chart，"
        "period 取 day/week/min。图表由界面自动画在回答下方，你只用一两句话概括走势要点，"
        "不要输出 JSON、代码块或图片链接。\n"
        "4. 回答必须包含标的名称与代码、最新价、涨跌幅。涨跌幅写成「+1.23%」或「-2.47%」"
        "（或「上涨 1.23%」/「下跌 2.47%」），不要写成「跌幅-2.47%」这类双重表述。数字不要省略。\n"
        "5. 如果用户紧接着问公告、消息面，交回 Triage Agent 或直接交给 News and Disclosure Agent。\n"
        + _COMPLIANCE
        + "\n"
        + _EFFICIENCY
    )


stock_information_agent = Agent[StockAgentChatContext](
    name="Stock Information Agent",
    model=MODEL,
    handoff_description=(
        "个股与指数的行情、涨跌幅、成交额、估值与 K线/分时走势图。"
        "Handles A-share quotes, valuation, and price charts."
    ),
    instructions=stock_information_instructions,
    tools=[search_stock, get_stock_quote, get_stock_chart],
    input_guardrails=[relevance_guardrail, jailbreak_guardrail],
)


# --------------------------------------------------------------------------- #
# 2. 大盘与板块
# --------------------------------------------------------------------------- #


market_overview_instructions = (
    f"{RECOMMENDED_PROMPT_PREFIX}\n"
    "你是「大盘与板块助手」，负责指数与行业板块层面的大势问题。\n"
    "1. 用户问「大盘怎么样」「指数」「今天行情」「成交量」时调用 get_market_overview，"
    "给出三大指数的点位与涨跌幅、两市涨跌家数。\n"
    "2. 用户问「哪个板块强」「板块涨跌」「行业表现」时调用 get_sector_overview；"
    "用户点名某个板块（如「白酒」「半导体」）时把板块名作为参数传入。\n"
    "3. 用户追问某个具体个股的表现时，交给 Stock Information Agent 处理。\n"
    "4. 涨跌幅写成「+0.87%」或「-1.92%」这种形式，数字不要省略。\n"
    + _COMPLIANCE
    + "\n"
    + _EFFICIENCY
)

market_overview_agent = Agent[StockAgentChatContext](
    name="Market Overview Agent",
    model=MODEL,
    handoff_description=(
        "大盘指数与行业板块的涨跌概览。"
        "Covers index performance and sector rotation."
    ),
    instructions=market_overview_instructions,
    tools=[get_market_overview, get_sector_overview],
    input_guardrails=[relevance_guardrail, jailbreak_guardrail],
)


# --------------------------------------------------------------------------- #
# 3. 公告与消息面
# --------------------------------------------------------------------------- #


news_disclosure_instructions = (
    f"{RECOMMENDED_PROMPT_PREFIX}\n"
    "你是「公告与消息助手」，负责个股的公告、消息面与事件梳理。\n"
    "重要：接到问题后必须实际调用工具拿到数据再回答，不要只回一句「已为您转接」"
    "或「正在查询…」就结束——用户看到那句会以为卡住了。\n"
    "1. 用户问某只股票的公告、消息、利好利空、近期发生了什么时，调用 get_stock_news。\n"
    "2. 标的名称不确定时先用 search_stock 确认，再查消息。\n"
    "3. 回答时逐条列出消息，并注明这是消息面摘要；如果用户同时关心股价，"
    "可以说一句「如需要我可以转给行情助手看当前报价」。\n"
    "4. 严禁把消息面解读成买卖建议，也不要预测消息会带来多大涨跌。\n"
    + _COMPLIANCE
    + "\n"
    + _EFFICIENCY
)

news_disclosure_agent = Agent[StockAgentChatContext](
    name="News and Disclosure Agent",
    model=MODEL,
    handoff_description=(
        "个股公告与消息面摘要。Summarizes company announcements and recent news."
    ),
    instructions=news_disclosure_instructions,
    tools=[search_stock, get_stock_news],
    input_guardrails=[relevance_guardrail, jailbreak_guardrail],
)


# --------------------------------------------------------------------------- #
# 4. 交易规则
# --------------------------------------------------------------------------- #


trading_rules_instructions = (
    f"{RECOMMENDED_PROMPT_PREFIX}\n"
    "你是「交易规则助手」，负责 A股交易规则与常识性问题。\n"
    "1. 用户问交易时间、T+1、涨跌停、手续费、最小交易单位、ST、融资融券、开户权限、"
    "分红除权、集合竞价等，必须先调用 stock_faq_lookup 拿答案，不要凭自己的知识作答。\n"
    "2. 用工具返回的内容为准，可以整理得更易读，但不要编造数字或费率。\n"
    "3. 如果用户其实是在问某只股票的行情（比如「茅台今天涨了多少」），交回 Triage Agent。\n"
    + _COMPLIANCE
    + "\n"
    + _EFFICIENCY
)

trading_rules_agent = Agent[StockAgentChatContext](
    name="Trading Rules Agent",
    model=MODEL,
    handoff_description=(
        "A股交易规则：交易时间、T+1、涨跌停、手续费、开户权限等。"
        "Answers trading-rule and market-mechanics questions."
    ),
    instructions=trading_rules_instructions,
    tools=[stock_faq_lookup],
    input_guardrails=[relevance_guardrail, jailbreak_guardrail],
)


# --------------------------------------------------------------------------- #
# 5. 自选股
# --------------------------------------------------------------------------- #


def watchlist_instructions(
    run_context: RunContextWrapper[StockAgentChatContext], agent: Agent[StockAgentChatContext]
) -> str:
    ctx = run_context.context.state
    current = "、".join(ctx.watchlist or []) or "[空]"
    return (
        f"{RECOMMENDED_PROMPT_PREFIX}\n"
        "你是「自选股助手」，负责维护用户的自选股列表。\n"
        f"1. 当前自选股：{current}。\n"
        "2. 用户说「加入自选」「关注一下」「收藏」时调用 add_to_watchlist；"
        "说「取消关注」「移除自选」时调用 remove_from_watchlist；"
        "说「我的自选」「看看自选」时调用 list_watchlist。\n"
        "3. 名称不明确时先用 search_stock 确认代码，再加/删，避免加错标的。\n"
        "4. 如果用户接着想看某只自选股的详情或走势，交给 Stock Information Agent。\n"
        + _COMPLIANCE
        + "\n"
        + _EFFICIENCY
    )


watchlist_agent = Agent[StockAgentChatContext](
    name="Watchlist Agent",
    model=MODEL,
    handoff_description=(
        "管理自选股列表：加入、移除、查看自选及其行情。"
        "Manages the user's watchlist."
    ),
    instructions=watchlist_instructions,
    tools=[search_stock, add_to_watchlist, remove_from_watchlist, list_watchlist],
    input_guardrails=[relevance_guardrail, jailbreak_guardrail],
)


# --------------------------------------------------------------------------- #
# 6. 分诊
# --------------------------------------------------------------------------- #


triage_agent = Agent[StockAgentChatContext](
    name="Triage Agent",
    model=MODEL,
    handoff_description=(
        "分诊入口，把请求路由给合适的专家 Agent"
        "（个股行情、大盘板块、公告消息、交易规则、自选股）。"
    ),
    instructions=(
        f"{RECOMMENDED_PROMPT_PREFIX} "
        "你是一个 A股助手的分诊 Agent，负责把用户请求转给最合适的专家：\n"
        "• Stock Information —— 个股/指数行情、股价、涨跌幅、估值、走势图/K线/分时"
        "（出现「股价」「多少钱」「涨了还是跌了」「画一下走势」都归它）\n"
        "• Market Overview —— 大盘、指数整体表现、成交量、行业板块涨跌\n"
        "• News and Disclosure —— 公告、消息面、利好利空、近期发生了什么\n"
        "• Trading Rules —— 交易规则、交易时间、手续费、T+1、涨跌停、开户\n"
        "• Watchlist —— 加自选、删自选、查看自选股\n"
        "如果请求已经足够明确，立刻 handoff，不要反问确认。"
        "转接时请直接调用 handoff，不要输出「已为您转接…」这类面向用户的说明文字——"
        "接手的那位专家会直接给用户完整回答。"
        "每条消息最多发起一次 handoff。"
    ),
    tools=[],
    handoffs=[],
    input_guardrails=[relevance_guardrail, jailbreak_guardrail],
)


# --------------------------------------------------------------------------- #
# Handoff 拓扑
# --------------------------------------------------------------------------- #

triage_agent.handoffs = [
    stock_information_agent,
    market_overview_agent,
    news_disclosure_agent,
    trading_rules_agent,
    watchlist_agent,
]

# 每个专家都能交回分诊，并在语义相关时互相串门
stock_information_agent.handoffs.extend([news_disclosure_agent, triage_agent])
market_overview_agent.handoffs.extend([stock_information_agent, triage_agent])
news_disclosure_agent.handoffs.extend([stock_information_agent, triage_agent])
trading_rules_agent.handoffs.append(triage_agent)
watchlist_agent.handoffs.extend([stock_information_agent, triage_agent])
