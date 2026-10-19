"""行情数据源 provider。

  base.py   共用工具（代码归一、市场前缀、板块归属）
  mock.py   本地模拟数据，离线兜底
  live.py   真实行情（腾讯 + 东方财富，免 token）

上层只依赖 data.py 这个门面，不直接 import 这里的模块。
"""
