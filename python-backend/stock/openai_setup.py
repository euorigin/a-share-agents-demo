"""OpenAI 客户端初始化。

被两处共用：`main.py`（Web 服务）和 `evaluation/run.py`（评测）。
抽出来的原因是评测入口如果自己漏配一次 base_url，请求就会打到官方端点，
表现为难以理解的 500 / 校验错误 —— 这类"评测环境和线上环境不一致"的问题最难查。

配置来源都是 python-backend/.env：
    OPENAI_API_KEY    必填
    OPENAI_BASE_URL   可选，第三方中转站（填到 /v1）
    OPENAI_API_MODE   可选，responses | chat_completions
"""

from __future__ import annotations

import os

_configured = False


def configure_openai() -> None:
    """按 .env 配置全局 OpenAI 客户端，并关闭 Agents SDK 的遥测上报。幂等。"""
    global _configured

    if not _configured:
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            from agents import set_default_openai_api, set_default_openai_client
            from openai import AsyncOpenAI

            set_default_openai_client(
                AsyncOpenAI(
                    api_key=os.environ.get("OPENAI_API_KEY"),
                    base_url=base_url,
                )
            )
            if os.environ.get("OPENAI_API_MODE", "responses").strip().lower() == "chat_completions":
                set_default_openai_api("chat_completions")
        _configured = True

    # 关闭遥测：SDK 把 trace 硬编码发往 api.openai.com/v1/traces/ingest，不跟随
    # OPENAI_BASE_URL，走中转站必然失败并反复刷 [non-fatal] Tracing request failed。
    # 注意当前 SDK 只认函数调用，不读 OPENAI_TRACING_DISABLED 环境变量。
    from agents import set_tracing_disabled

    set_tracing_disabled(True)
