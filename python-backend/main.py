from __future__ import annotations as _annotations

import json
import os
from datetime import datetime
from typing import Any, Dict

from dotenv import load_dotenv

# Load OPENAI_API_KEY etc. from python-backend/.env before anything else runs.
load_dotenv()

# --- 可选：指向 OpenAI 兼容中转站 -------------------------------------------
# .env 中设置 OPENAI_BASE_URL=你的中转地址/v1 即可生效。
# 若中转站不支持 /v1/responses（只支持 chat/completions），再设置：
#   OPENAI_API_MODE=chat_completions
_base_url = os.environ.get("OPENAI_BASE_URL")
if _base_url:
    from agents import set_default_openai_api, set_default_openai_client
    from openai import AsyncOpenAI

    set_default_openai_client(
        AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=_base_url,
        )
    )
    if os.environ.get("OPENAI_API_MODE", "responses").strip().lower() == "chat_completions":
        set_default_openai_api("chat_completions")

# --- 关闭 Agents SDK 的遥测上报 ---------------------------------------------
# SDK 默认把 trace 发到 https://api.openai.com/v1/traces/ingest，这个端点是硬编码的，
# 不会跟随 OPENAI_BASE_URL。本项目走第三方中转，上报必然失败，后台每次重试 3 次并刷屏：
#   [non-fatal] Tracing request failed  ×N
#   [non-fatal] Tracing: max retries reached, giving up on this batch.
# 这些日志只是遥测，不影响对话功能，直接关掉以免污染排障输出。
# 注意：当前 SDK 版本不读取 OPENAI_TRACING_DISABLED 环境变量，必须调用函数。
from agents import set_tracing_disabled

set_tracing_disabled(True)

from chatkit.server import StreamingResult
from chatkit.types import (
    AssistantMessageItem,
    ClientEffectEvent,
    InferenceOptions,
    UserMessageItem,
    UserMessageTextContent,
)
from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from stock.agents import (
    market_overview_agent,
    news_disclosure_agent,
    stock_information_agent,
    trading_rules_agent,
    triage_agent,
    watchlist_agent,
)
from stock import data as stock_data
from stock.context import (
    StockAgentChatContext,
    StockAgentContext,
    create_initial_context,
    public_context,
)
from server import StockServer

app = FastAPI()

# CORS configuration (adjust as needed for deployment)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

chat_server = StockServer()


def get_server() -> StockServer:
    return chat_server


@app.post("/chatkit")
async def chatkit_endpoint(
    request: Request, server: StockServer = Depends(get_server)
) -> Response:
    payload = await request.body()
    result = await server.process(payload, {"request": request})
    if isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")
    if hasattr(result, "json"):
        return Response(content=result.json, media_type="application/json")
    return Response(content=result)


@app.get("/chatkit/state")
async def chatkit_state(
    thread_id: str = Query(...),
    server: StockServer = Depends(get_server),
) -> Dict[str, Any]:
    return await server.snapshot(thread_id, {"request": None})


@app.get("/chatkit/bootstrap")
async def chatkit_bootstrap(
    server: StockServer = Depends(get_server),
) -> Dict[str, Any]:
    return await server.snapshot(None, {"request": None})


@app.get("/chatkit/state/stream")
async def chatkit_state_stream(
    thread_id: str = Query(...),
    server: StockServer = Depends(get_server),
):
    thread = await server.ensure_thread(thread_id, {"request": None})
    queue = server.register_listener(thread.id)

    async def event_generator():
        try:
            initial = await server.snapshot(thread.id, {"request": None})
            yield f"data: {json.dumps(initial, default=str)}\n\n"
            while True:
                data = await queue.get()
                yield f"data: {data}\n\n"
        finally:
            server.unregister_listener(thread.id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# 走势图数据接口
# 前端 ui/components/stock-chart.tsx 拉这个接口拿 K线 / 分时 数据来画图。
# 数据走 stock/data.py 门面：默认真实行情（腾讯），失败自动回退模拟数据。
# ---------------------------------------------------------------------------


@app.get("/stock/chart")
async def stock_chart(
    symbol: str = Query(..., description="6 位代码，或带市场后缀的指数代码，也接受名称"),
    period: str = Query("day", description="day=日K, week=周K, min=分时"),
) -> Dict[str, Any]:
    code = stock_data.normalize_symbol(symbol)
    if not code:
        # 也允许直接传名称（如「贵州茅台」），取首个匹配
        matches = stock_data.search(symbol)
        if matches:
            code = matches[0]["code"]
    if not code:
        return {"error": f"未找到标的「{symbol}」", "symbol": symbol, "period": period}
    data = stock_data.get_series(code, period)
    if not data:
        return {"error": f"暂无 {symbol} 的图表数据", "symbol": symbol, "period": period}
    return data


# ---------------------------------------------------------------------------
# 自研聊天接口（不依赖 ChatKit 前端组件，绕开外部 CDN）
# 前端 ui/components/simple-chat-panel.tsx 通过它拿到流式回答与编排状态。
# ---------------------------------------------------------------------------


class SimpleChatRequest(BaseModel):
    thread_id: str | None = None
    message: str


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _status_lines_from_runner_events(raw_events: list[Dict[str, Any]]) -> list[str]:
    """把编排事件转成人话，显示在聊天面板的状态行里。"""
    lines: list[str] = []
    for event in raw_events:
        event_type = event.get("type")
        if event_type == "handoff":
            lines.append(f"已交接：{event.get('content', '')}")
        elif event_type == "tool_call":
            lines.append(f"调用工具：{event.get('content', '')}")
        elif event_type == "context_update":
            changes = (event.get("metadata") or {}).get("changes") or {}
            if changes:
                lines.append(
                    "上下文更新：" + "、".join(f"{k}={v}" for k, v in changes.items())
                )
    return lines


@app.post("/chat/simple")
async def chat_simple(
    payload: SimpleChatRequest, server: StockServer = Depends(get_server)
) -> Response:
    context: Dict[str, Any] = {"request": None}
    thread = await server.ensure_thread(payload.thread_id, context)
    user_message = UserMessageItem(
        id=server.store.generate_item_id("message", thread, context),
        thread_id=thread.id,
        created_at=datetime.now(),
        content=[UserMessageTextContent(text=payload.message)],
        attachments=[],
        inference_options=InferenceOptions(),
    )

    async def event_stream():
        yield _sse({"type": "thread", "thread_id": thread.id})
        # 记录本轮开始前「画过几张图」，用于判断本轮是否新画了走势图
        chart_before = server.chart_for_thread(thread.id) or {}
        chart_before_token = chart_before.get("token", 0)
        # 思考块被剥掉后会留下若干换行，这里丢掉回答开头的空白
        answer_started = False
        try:
            async for event in server.respond(thread, user_message, context):
                event_type = getattr(event, "type", "")

                # 流式文本增量被包在 thread.item.updated 的 update 字段里
                update = getattr(event, "update", None)
                if (
                    update is not None
                    and getattr(update, "type", "")
                    == "assistant_message.content_part.text_delta"
                ):
                    delta = getattr(update, "delta", "") or ""
                    if delta:
                        if not answer_started:
                            delta = delta.lstrip()
                            if delta:
                                answer_started = True
                        if delta:
                            yield _sse({"type": "delta", "text": delta})
                    continue

                if event_type == "thread.item.done":
                    if isinstance(getattr(event, "item", None), AssistantMessageItem):
                        yield _sse({"type": "message_done"})
                elif isinstance(event, ClientEffectEvent):
                    if event.name == "runner_state_update":
                        yield _sse({"type": "state"})
                    elif event.name == "runner_event_delta":
                        data = event.data if isinstance(event.data, dict) else {}
                        for line in _status_lines_from_runner_events(
                            data.get("events") or []
                        ):
                            yield _sse({"type": "status", "text": line})
        except Exception as exc:  # noqa: BLE001 - 把错误回传给前端而不是断流
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

        # 本轮如果调用过走势图工具，就把图表指令推给前端（不依赖模型是否复述）
        chart_after = server.chart_for_thread(thread.id)
        if chart_after and chart_after.get("token", 0) != chart_before_token:
            yield _sse(
                {
                    "type": "chart",
                    "symbol": chart_after["symbol"],
                    "period": chart_after["period"],
                }
            )
        yield _sse({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


__all__ = [
    "StockAgentChatContext",
    "StockAgentContext",
    "app",
    "chat_server",
    "create_initial_context",
    "market_overview_agent",
    "news_disclosure_agent",
    "public_context",
    "stock_information_agent",
    "trading_rules_agent",
    "triage_agent",
    "watchlist_agent",
]
