"""评测执行器：跑单个用例，并把可量化的事实采集出来。

一次 `run_case` 只做「执行 + 采集」，不做判定 —— 判定在 checks.py，聚合在 metrics.py。
这样拆开的好处是同一份轨迹可以复算不同指标，也方便以后接入别的判定器。

关键点：
- 每个用例用全新的 store / thread / context，用例之间不串味；
- 多轮用例复用 `result.to_input_list()` 作为下一轮输入（与 server.py 的真实链路一致），
  第二轮起始 agent 取上一轮的 `last_agent`，复现真实会话里的接力行为；
- 护栏触发是**异常**而不是返回值，必须显式捕获；
- 轨迹记录每一轮，最终判定只看最后一轮（多轮用例关注"用户最后那句话"是否被正确处理）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agents import (
    HandoffOutputItem,
    InputGuardrailTripwireTriggered,
    ItemHelpers,
    MessageOutputItem,
    Runner,
    ToolCallItem,
    ToolCallOutputItem,
)
from agents.exceptions import MaxTurnsExceeded
from chatkit.types import ThreadMetadata

from memory_store import MemoryStore
from stock.agents import triage_agent
from stock.context import create_initial_context, public_context, StockAgentChatContext

from .dataset import Case


@dataclass
class ToolCall:
    name: str
    args: Any
    agent: str
    output_preview: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "args": self.args,
            "agent": self.agent,
            "output_preview": self.output_preview,
        }


@dataclass
class CaseTrace:
    """一个用例的完整可观测事实。"""

    id: str
    turns: list[str]
    # 每一轮的结束 agent，最后一项即"最终路由结果"
    agent_per_turn: list[str] = field(default_factory=list)
    handoffs: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    answer: str = ""
    guardrail_tripped: str | None = None
    error: str | None = None
    latency_ms: float = 0.0
    turns_used: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    # 最终态上下文（评测"上下文是否被正确更新"时可直接用）
    context_after: dict[str, Any] = field(default_factory=dict)

    @property
    def final_agent(self) -> str:
        return self.agent_per_turn[-1] if self.agent_per_turn else ""

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self.tool_calls]

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "turns": self.turns,
            "final_agent": self.final_agent,
            "agent_per_turn": self.agent_per_turn,
            "handoffs": self.handoffs,
            "tool_calls": [t.as_dict() for t in self.tool_calls],
            "answer": self.answer,
            "guardrail_tripped": self.guardrail_tripped,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 1),
            "turns_used": self.turns_used,
            "tokens": {"input": self.input_tokens, "output": self.output_tokens},
            "context_after": self.context_after,
        }


def _guardrail_name(exc: InputGuardrailTripwireTriggered) -> str:
    try:
        gr = exc.guardrail_result.guardrail
        return getattr(gr, "get_name", lambda: "guardrail")() or getattr(gr, "name", "guardrail")
    except Exception:  # noqa: BLE001 - 护栏名字取不到也不该让评测崩
        return "guardrail"


# 部分模型（如 MiniMax M 系列）会把思维链以 <think>...</think> 混在正文里。
# 评测答案必须剥掉它：否则思维过程里的"建议买入"之类措辞会污染答案断言，
# 造成"答案明明合规却被判违规"的假失败。
_THINK_BLOCK_RE = re.compile(r"<think[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)


def clean_answer(text: str) -> str:
    if not isinstance(text, str):
        return ""
    cleaned = _THINK_BLOCK_RE.sub("", text)
    # 兜底：只有闭合标签、没有起始标签的情况，取最后一个 </think> 之后的内容
    if "</think>" in cleaned.lower():
        parts = re.split(r"</think>", cleaned, flags=re.IGNORECASE)
        cleaned = parts[-1]
    return cleaned.strip()


def _parse_args(raw: Any) -> Any:
    """工具参数在 SDK 里是 JSON 字符串，这里解析成对象方便断言。解析失败就原样保留。"""
    if isinstance(raw, str):
        import json

        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return raw
    return raw


async def _new_context() -> StockAgentChatContext:
    store = MemoryStore()
    thread = ThreadMetadata(
        id=store.generate_thread_id({}),
        created_at=datetime.now(),
    )
    await store.save_thread(thread, {})
    return StockAgentChatContext(
        thread=thread,
        store=store,
        request_context={},
        state=create_initial_context(),
    )


async def run_case(case: Case, *, max_turns: int = 8) -> CaseTrace:
    trace = CaseTrace(id=case.id, turns=list(case.turns))
    ctx = await _new_context()

    input_items: list[Any] = [{"role": "user", "content": case.turns[0]}]
    starting_agent = triage_agent
    started = time.perf_counter()

    for idx, _text in enumerate(case.turns):
        if idx > 0:
            # 与真实会话一致：上一轮的完整记录（含工具调用）+ 新的用户消息
            input_items = prev_items + [{"role": "user", "content": _text}]

        try:
            # 用流式 API 而不是 Runner.run()，理由有二：
            # 1) 生产链路（server.py）就是 run_streamed，评测口径必须与线上一致；
            # 2) 部分中转站的 usage 字段是 null，非流式分支会把它原样塞进 Usage 导致
            #    pydantic 校验失败（openai_chatcompletions.py:289），流式分支有 `or 0` 兜底。
            result = Runner.run_streamed(
                starting_agent,
                input_items,
                context=ctx,
                max_turns=max_turns,
            )
            async for _event in result.stream_events():
                pass
        except InputGuardrailTripwireTriggered as exc:
            trace.guardrail_tripped = _guardrail_name(exc)
            trace.turns_used = idx + 1
            break
        except MaxTurnsExceeded:
            trace.error = "MaxTurnsExceeded"
            trace.turns_used = idx + 1
            break
        except Exception as exc:  # noqa: BLE001 - 评测要记录失败而不是中断整轮
            trace.error = f"{type(exc).__name__}: {exc}"
            trace.turns_used = idx + 1
            break

        # --- 采集本轮的 handoff / 工具调用 / 回答 ---
        messages: list[str] = []
        for item in result.new_items:
            if isinstance(item, HandoffOutputItem):
                trace.handoffs.append(f"{item.source_agent.name} -> {item.target_agent.name}")
            elif isinstance(item, ToolCallItem):
                trace.tool_calls.append(
                    ToolCall(
                        name=getattr(item.raw_item, "name", "") or "",
                        args=_parse_args(getattr(item.raw_item, "arguments", None)),
                        agent=item.agent.name,
                    )
                )
            elif isinstance(item, ToolCallOutputItem):
                # 把输出回填到最近一次同名工具调用上，便于排障时看工具到底返回了什么
                for call in reversed(trace.tool_calls):
                    if not call.output_preview:
                        call.output_preview = str(item.output)[:300]
                        break
            elif isinstance(item, MessageOutputItem):
                text = clean_answer(ItemHelpers.text_message_output(item))
                if text:
                    messages.append(text)

        trace.agent_per_turn.append(result.last_agent.name)
        trace.answer = messages[-1] if messages else trace.answer
        trace.turns_used = idx + 1

        for resp in getattr(result, "raw_responses", []) or []:
            usage = getattr(resp, "usage", None)
            if usage is not None:
                trace.input_tokens += getattr(usage, "input_tokens", 0) or 0
                trace.output_tokens += getattr(usage, "output_tokens", 0) or 0

        prev_items = result.to_input_list()
        starting_agent = result.last_agent

    trace.latency_ms = (time.perf_counter() - started) * 1000
    trace.context_after = public_context(ctx.state)
    return trace
