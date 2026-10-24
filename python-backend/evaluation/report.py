"""报告渲染：终端摘要 / Markdown / 基线回归对比。

只做格式化，不做计算 —— 数字全部来自 metrics.aggregate()。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .metrics import CaseResult, SCALARS, pluck

# --------------------------------------------------------------------------- #
# 宽度对齐（中文按 2 列算，否则表格会歪）
# --------------------------------------------------------------------------- #


def _w(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def _pad(text: str, width: int, align: str = "left") -> str:
    gap = max(0, width - _w(text))
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def _pct(value: Any) -> str:
    one = float(value or 0)
    return f"{one:.1f}"


def _show(value: Any, denominator: Any) -> str:
    """分母为 0 时显示占位符：0.0% 会让人误以为"跑得很差"，其实是"这类断言没出现"。"""
    return "—" if not denominator else _pct(value)


# --------------------------------------------------------------------------- #
# 终端
# --------------------------------------------------------------------------- #


def render_console(
    summary: dict[str, Any],
    results: list[CaseResult],
    *,
    meta: dict[str, Any],
    baseline: dict[str, Any] | None = None,
    show_passed: bool = False,
) -> str:
    out: list[str] = []
    add = out.append

    add("=" * 68)
    add("A股智能助手 · 可量化评测报告")
    add("=" * 68)
    add(
        f"数据集 {meta.get('dataset')}   用例 {summary['cases']}   数据源 {meta.get('data_mode')}   "
        f"模型 {meta.get('model')}"
    )
    add(f"时间 {meta.get('started_at')}   耗时 {meta.get('elapsed_s')}s   并发 {meta.get('concurrency')}")
    add("")

    # ---- 端到端 ----
    add("【端到端】")
    add(f"  用例通过        {summary['passed_cases']}/{summary['cases']}  ({_pct(summary['pass_rate'])}%)")
    add(
        f"  断言通过        {summary['checks_passed']}/{summary['checks_total']}  "
        f"({_pct(summary['check_pass_rate'])}%)"
    )
    st = summary.get("stability")
    if st:
        rates = " / ".join(_pct(r) for r in st["pass_rates"])
        add(
            f"  多轮稳定性      {st['runs']} 轮：{rates}  "
            f"均值 {st['mean']}%  极差 {st['spread']}%"
        )
    add("")

    # ---- 能力维度 ----
    add("【能力维度】")
    rows = [
        ("路由准确率", _show(summary["routing"]["accuracy"], summary["routing"]["total"]),
         f"{summary['routing']['passed']}/{summary['routing']['total']}"),
        ("工具召回", _show(summary["tools"]["recall"], summary["tools"]["required_total"]),
         "required 命中率"),
        ("工具精确", _show(summary["tools"]["precision"], summary["tools"]["actual_total"]),
         "实际调用中有效占比"),
        ("工具 F1", _show(summary["tools"]["f1"], summary["tools"]["actual_total"]), ""),
        ("参数准确率", _show(summary["args"]["accuracy"], summary["args"]["total"]),
         f"{summary['args']['passed']}/{summary['args']['total']}"),
        ("答案通过率", _show(summary["answer"]["pass_rate"], summary["answer"]["total"]),
         f"{summary['answer']['passed']}/{summary['answer']['total']}"),
    ]
    for name, val, note in rows:
        add(f"  {_pad(name, 14)}{_pad(val, 8, 'right')}{('  ' + note) if note else ''}")

    viol = summary["tools"]["forbidden_violations"]
    add(
        f"  {_pad('越权工具调用', 14)}{_pad(str(viol), 8, 'right')}  "
        f"（共 {summary['tools']['forbidden_total']} 条禁止规则）"
    )
    add(f"  {_pad('平均工具调用', 14)}{_pad(str(summary['tools']['avg_calls_per_case']), 8, 'right')}  次/用例")
    add("")

    # ---- 护栏 ----
    g = summary["guardrail"]
    add("【护栏】")
    add(
        f"  TP {g['tp']}  FP {g['fp']}  TN {g['tn']}  FN {g['fn']}   "
        f"召回 {_pct(g['recall'])}%   精确 {_pct(g['precision'])}%   准确 {_pct(g['accuracy'])}%"
    )
    add("  TP=正确拦截  FP=误拦正常问题  FN=漏拦越界请求")
    add("")

    # ---- 效率 ----
    lat = summary["latency_ms"]
    tok = summary["tokens"]
    add("【效率与成本】")
    add(f"  P50 {lat['p50']} ms   P95 {lat['p95']} ms   均值 {lat['mean']} ms   最慢 {lat['max']} ms")
    if tok.get("available"):
        add(f"  token 合计 {tok['total']}（输入 {tok['input']} / 输出 {tok['output']}），平均 {int(tok['avg_per_case'])}/用例")
    else:
        add("  token 用量不可用（当前模型/中转站未返回 usage 字段）")
    add("")

    # ---- 分类 ----
    add("【按类别】")
    for name, b in sorted(summary["categories"].items()):
        ratio = f"{b['passed']}/{b['total']}"
        add(f"  {_pad(name, 18)}{_pad(ratio, 8, 'right')}  ({_pct(b['pass_rate'])}%)")
    add("")

    # ---- 工具分布 ----
    if summary["tools"]["usage"]:
        add("【工具调用分布】")
        add("  " + "  ".join(f"{k}×{v}" for k, v in summary["tools"]["usage"].items()))
        add("")

    # ---- 基线对比 ----
    if baseline:
        add("【对比基线】")
        for label, path in SCALARS:
            cur = pluck(summary, path)
            old = pluck(baseline, path)
            if cur is None or old is None:
                continue
            delta = float(cur) - float(old)
            # 延迟和 token 是"越低越好"，其余越高越好
            lower_better = label.endswith("ms") or "token" in label
            if abs(delta) < 0.05:
                mark = "="
            elif (delta > 0) != lower_better:
                mark = "↑ 改善"
            else:
                mark = "↓ 退化"
            add(f"  {_pad(label, 16)}{_pad(_pct(old), 8, 'right')} -> {_pad(_pct(cur), 8, 'right')}"
                f"  {delta:+.1f}  {mark}")
        add("")

    # ---- 失败明细 ----
    failed = [r for r in results if not r.passed]
    add(f"【失败用例】{len(failed)} 条")
    if not failed:
        add("  无 🎉")
    for r in failed:
        add(f"  ✗ {r.case.id}  [{r.case.category}]  {r.case.title}")
        if r.trace.error:
            add(f"      运行错误：{r.trace.error}")
        for chk in r.failed_checks():
            add(f"      {chk.kind}: {chk.detail}")
    add("")

    if show_passed:
        add("【通过用例】")
        for r in results:
            if r.passed:
                add(f"  ✓ {r.case.id}  {r.trace.final_agent}  工具={r.trace.tool_names}")
        add("")

    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #


def render_markdown(
    summary: dict[str, Any],
    results: list[CaseResult],
    *,
    meta: dict[str, Any],
    baseline: dict[str, Any] | None = None,
) -> str:
    g = summary["guardrail"]
    lat = summary["latency_ms"]
    tok = summary["tokens"]
    md: list[str] = []

    md.append("# A股智能助手 · 评测报告")
    md.append("")
    md.append(f"- 数据集：`{meta.get('dataset')}`（{summary['cases']} 个用例）")
    md.append(f"- 数据源：`{meta.get('data_mode')}`　模型：`{meta.get('model')}`")
    md.append(f"- 运行时间：{meta.get('started_at')}　总耗时：{meta.get('elapsed_s')}s　并发：{meta.get('concurrency')}")
    md.append("")
    md.append("## 总体")
    md.append("")
    md.append("| 指标 | 数值 |")
    md.append("| --- | --- |")
    md.append(f"| 用例通过率 | **{_pct(summary['pass_rate'])}%**（{summary['passed_cases']}/{summary['cases']}） |")
    md.append(f"| 断言通过率 | {_pct(summary['check_pass_rate'])}%（{summary['checks_passed']}/{summary['checks_total']}） |")
    st = summary.get("stability")
    if st:
        rates = " / ".join(_pct(r) for r in st["pass_rates"])
        md.append(f"| 多轮稳定性 | {st['runs']} 轮：{rates}；均值 {st['mean']}%，极差 {st['spread']}% |")
    md.append(f"| 路由准确率 | {_pct(summary['routing']['accuracy'])}%（{summary['routing']['passed']}/{summary['routing']['total']}） |")
    md.append(f"| 工具召回 / 精确 / F1 | {_pct(summary['tools']['recall'])}% / {_pct(summary['tools']['precision'])}% / {_pct(summary['tools']['f1'])} |")
    md.append(f"| 参数准确率 | {_pct(summary['args']['accuracy'])}%（{summary['args']['passed']}/{summary['args']['total']}） |")
    md.append(f"| 答案通过率 | {_pct(summary['answer']['pass_rate'])}%（{summary['answer']['passed']}/{summary['answer']['total']}） |")
    md.append(f"| 护栏召回 / 精确 / 准确 | {_pct(g['recall'])}% / {_pct(g['precision'])}% / {_pct(g['accuracy'])}% |")
    md.append(f"| 越权工具调用 | {summary['tools']['forbidden_violations']} / {summary['tools']['forbidden_total']} 条规则 |")
    md.append(f"| 延迟 P50 / P95 | {lat['p50']} ms / {lat['p95']} ms |")
    if tok.get("available"):
        md.append(f"| token 合计（均） | {tok['total']}（{int(tok['avg_per_case'])}/用例） |")
    else:
        md.append("| token 合计 | 不可用（供应商未返回 usage） |")
    md.append("")

    md.append("## 按类别")
    md.append("")
    md.append("| 类别 | 通过 | 通过率 |")
    md.append("| --- | --- | --- |")
    for name, b in sorted(summary["categories"].items()):
        md.append(f"| {name} | {b['passed']}/{b['total']} | {_pct(b['pass_rate'])}% |")
    md.append("")

    md.append("## 护栏混淆矩阵")
    md.append("")
    md.append("| | 实际拦截 | 实际放行 |")
    md.append("| --- | --- | --- |")
    md.append(f"| 应拦截 | TP {g['tp']} | FN {g['fn']} |")
    md.append(f"| 应放行 | FP {g['fp']} | TN {g['tn']} |")
    md.append("")

    if summary["tools"]["usage"]:
        md.append("## 工具调用分布")
        md.append("")
        md.append("| 工具 | 次数 |")
        md.append("| --- | --- |")
        for k, v in summary["tools"]["usage"].items():
            md.append(f"| `{k}` | {v} |")
        md.append("")

    if baseline:
        md.append("## 对比基线")
        md.append("")
        md.append("| 指标 | 基线 | 本次 | 变化 |")
        md.append("| --- | --- | --- | --- |")
        for label, path in SCALARS:
            cur = pluck(summary, path)
            old = pluck(baseline, path)
            if cur is None or old is None:
                continue
            delta = float(cur) - float(old)
            lower_better = label.endswith("ms") or "token" in label
            trend = "持平" if abs(delta) < 0.05 else ("改善" if (delta > 0) != lower_better else "退化")
            md.append(f"| {label} | {_pct(old)} | {_pct(cur)} | {delta:+.1f} {trend} |")
        md.append("")

    md.append("## 用例明细")
    md.append("")
    md.append("| 用例 | 类别 | 结果 | 最终 Agent | 工具调用 | 延迟 ms |")
    md.append("| --- | --- | --- | --- | --- | --- |")
    for r in results:
        mark = "✅" if r.passed else "❌"
        tools = ", ".join(r.trace.tool_names) or "—"
        agent = r.trace.final_agent or "—"
        if r.trace.guardrail_tripped:
            agent = f"护栏拦截（{r.trace.guardrail_tripped}）"
        md.append(
            f"| `{r.case.id}` | {r.case.category} | {mark} | {agent} | {tools} | {r.trace.latency_ms:.0f} |"
        )
    md.append("")

    failed = [r for r in results if not r.passed]
    if failed:
        md.append("## 失败明细")
        md.append("")
        for r in failed:
            md.append(f"### `{r.case.id}` — {r.case.title}")
            md.append("")
            if r.trace.error:
                md.append(f"- 运行错误：`{r.trace.error}`")
            for chk in r.failed_checks():
                md.append(f"- **{chk.kind}**：{chk.detail}")
            if r.trace.answer:
                snippet = r.trace.answer.replace("\n", " ")[:200]
                md.append(f"- 实际回答：{snippet}")
            md.append("")

    md.append("---")
    md.append("")
    md.append(f"_由 `python -m evaluation.run` 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
    return "\n".join(md)


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #


def build_payload(
    summary: dict[str, Any],
    results: list[CaseResult],
    *,
    meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "meta": meta,
        "summary": summary,
        "results": [r.as_dict() for r in results],
    }


def dump_json(payload: dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def load_baseline(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("summary")
    except Exception:  # noqa: BLE001 - 基线读不到就当作没有，不阻断评测
        return None
