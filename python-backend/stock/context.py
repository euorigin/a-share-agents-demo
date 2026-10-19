from __future__ import annotations as _annotations

from chatkit.agents import AgentContext
from pydantic import BaseModel


class StockAgentContext(BaseModel):
    """A股助手在会话中累积的上下文。

    只保留与股票场景相关的字段，前端「Conversation Context」面板会直接展示它们。
    """

    # 最近一次查询过的标的
    stock_code: str | None = None
    stock_name: str | None = None
    stock_price: float | None = None
    stock_change_pct: float | None = None

    # 自选股（存代码，展示时再解析名称）
    watchlist: list[str] | None = None

    # 最近一次查询过的行业板块
    sector: str | None = None

    # 最近一次请求绘制的走势图（token 自增，用于判断「本轮是否新画了图」）
    stock_chart_symbol: str | None = None
    stock_chart_period: str | None = None
    stock_chart_token: int = 0


class StockAgentChatContext(AgentContext[dict]):
    """
    AgentContext wrapper used during ChatKit runs.
    Holds the persisted StockAgentContext in `state`.
    """

    state: StockAgentContext


def create_initial_context() -> StockAgentContext:
    """Factory for a new StockAgentContext. Starts empty; values fill in during the chat."""
    return StockAgentContext()


def public_context(ctx: StockAgentContext) -> dict:
    """Return a filtered view of the context for UI display.

    Only the chart-rendering fields are hidden — everything else is meant to be shown
    in the "Conversation Context" panel.
    """
    data = ctx.model_dump()
    hidden_keys = {
        # 走势图属于内部渲染指令，不必出现在上下文面板里
        "stock_chart_symbol",
        "stock_chart_period",
        "stock_chart_token",
    }
    for key in list(data.keys()):
        if key in hidden_keys:
            data.pop(key, None)
    return data
