"""可量化评测环节。

跑法见 evaluation/run.py 的文档字符串，或直接在 python-backend 下：

    python -m evaluation.run --limit 3

模块分工：
    dataset.py  加载并校验 JSONL 评测集
    runner.py   执行用例，采集 handoff / 工具调用 / 参数 / 答案 / 护栏 / 延迟 / token
    checks.py   把期望与实际比对成一组可通过/失败的检查项
    metrics.py  聚合指标（含护栏混淆矩阵、工具 P/R/F1）
    report.py   终端摘要、Markdown 报告、基线回归对比
    run.py      CLI 入口
"""

from __future__ import annotations

__all__ = ["dataset", "runner", "checks", "metrics", "report"]
