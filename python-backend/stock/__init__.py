"""A股行情助手：模拟数据、工具、Agent 编排与护栏。

模块划分：
  data.py        行情 / 指数 / 板块 / K线与分时 模拟数据
  faq.py         A股交易规则知识库
  tools.py       供 Agent 调用的 function_tool
  context.py     会话上下文（StockAgentContext）
  agents.py      6 个 Agent 及 handoff 拓扑
  guardrails.py  相关性与越狱护栏
"""
