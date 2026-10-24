"""指标聚合。

口径说明（写进报告里，避免"指标很好看但不知道在算什么"）：

- pass_rate：**用例级**通过率 —— 一条用例的所有断言全过才算通过。最能反映端到端可用性。
- routing_accuracy：断言级，路由断言通过数 / 路由断言总数。
- tool_recall：对声明了 tools_required 的用例，|命中| / |要求| 的平均（微观平均，按断言累加）。
- tool_precision：对声明了 tools_required 的用例，|命中| / |实际调用去重|。禁止工具违规单独计。
- arg_accuracy：参数断言通过率。
- answer_pass_rate：答案类断言通过率。
- 护栏用混淆矩阵：拦截=正类。recall 高说明该拦的都拦住了，precision 低说明误拦多。
- 延迟取 P50/P95（含所有轮次与工具调用），token 只统计主链路（护栏子 run 不计入）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .checks import CheckResult
from .dataset import Case
from .runner import CaseTrace


@dataclass
class CaseResult:
    case: Case
    trace: CaseTrace
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case.id,
            "category": self.case.category,
            "passed": self.passed,
            "checks": [c.as_dict() for c in self.checks],
            "trace": self.trace.as_dict(),
        }


def _pct(num: float, den: float) -> float:
    return round(num / den * 100, 1) if den else 0.0


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    idx = (len(ordered) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return round(ordered[lo] * (1 - frac) + ordered[hi] * frac, 1)


def _kind_stats(checks: Iterable[CheckResult]) -> tuple[int, int]:
    checks = list(checks)
    return sum(1 for c in checks if c.passed), len(checks)


def aggregate(results: list[CaseResult]) -> dict[str, Any]:
    total = len(results)
    passed_cases = sum(1 for r in results if r.passed)

    all_checks = [c for r in results for c in r.checks]
    by_kind: dict[str, list[CheckResult]] = {}
    for chk in all_checks:
        by_kind.setdefault(chk.kind, []).append(chk)

    routing_pass, routing_total = _kind_stats(by_kind.get("routing", []))
    arg_pass, arg_total = _kind_stats(by_kind.get("arg", []))
    answer_pass, answer_total = _kind_stats(by_kind.get("answer", []))
    tool_pass, tool_total = _kind_stats(by_kind.get("tool", []))

    # ---- 工具集合的 micro precision / recall（只统计声明了 tools_required 的用例）----
    hit_req = 0
    total_req = 0
    total_actual = 0
    total_effective = 0
    forbidden_violations = 0
    forbidden_total = 0
    for r in results:
        req = r.case.expect.get("tools_required") or []
        if req:
            actual = set(r.trace.tool_names)
            allowed = set(r.case.expect.get("tools_allowed") or [])
            hit_req += sum(1 for t in req if t in actual)
            total_req += len(req)
            total_actual += len(actual)
            # 「有效调用」= 命中的必需工具 + 显式允许的辅助工具。
            # 不这么算的话，模型按 prompt 要求先 search_stock 确认代码，
            # 反而会被判成"多余调用"——那是把正确行为算成了错误。
            total_effective += len(actual & (set(req) | allowed))
        forbidden = r.case.expect.get("tools_forbidden") or []
        if forbidden:
            forbidden_total += len(forbidden)
            forbidden_violations += sum(1 for t in forbidden if t in r.trace.tool_names)

    # ---- 护栏混淆矩阵（拦截 = 正类）----
    tp = fp = tn = fn = 0
    for r in results:
        want = r.case.expect.get("guardrail")
        if want is None:
            continue
        tripped = r.trace.guardrail_tripped is not None
        if want == "trip" and tripped:
            tp += 1
        elif want == "trip" and not tripped:
            fn += 1
        elif want == "pass" and tripped:
            fp += 1
        else:
            tn += 1

    # ---- 延迟 / token ----
    latencies = [r.trace.latency_ms for r in results]
    in_tok = sum(r.trace.input_tokens for r in results)
    out_tok = sum(r.trace.output_tokens for r in results)

    # ---- 按类别 ----
    categories: dict[str, dict[str, Any]] = {}
    for r in results:
        bucket = categories.setdefault(
            r.case.category, {"total": 0, "passed": 0, "checks_passed": 0, "checks_total": 0}
        )
        bucket["total"] += 1
        bucket["passed"] += 1 if r.passed else 0
        bucket["checks_passed"] += sum(1 for c in r.checks if c.passed)
        bucket["checks_total"] += len(r.checks)
    for name, b in categories.items():
        b["pass_rate"] = _pct(b["passed"], b["total"])

    # ---- 工具调用分布 ----
    tool_usage: dict[str, int] = {}
    for r in results:
        for t in r.trace.tool_names:
            tool_usage[t] = tool_usage.get(t, 0) + 1

    total_tool_calls = sum(tool_usage.values())

    return {
        "cases": total,
        "passed_cases": passed_cases,
        "failed_cases": total - passed_cases,
        "pass_rate": _pct(passed_cases, total),
        "checks_passed": sum(1 for c in all_checks if c.passed),
        "checks_total": len(all_checks),
        "check_pass_rate": _pct(sum(1 for c in all_checks if c.passed), len(all_checks)),
        "routing": {
            "accuracy": _pct(routing_pass, routing_total),
            "passed": routing_pass,
            "total": routing_total,
        },
        "tools": {
            "recall": _pct(hit_req, total_req),
            "precision": _pct(total_effective, total_actual),
            "f1": _f1(
                total_effective / total_actual if total_actual else 0,
                hit_req / total_req if total_req else 0,
            ),
            "assertions_passed": tool_pass,
            "assertions_total": tool_total,
            "forbidden_violations": forbidden_violations,
            "forbidden_total": forbidden_total,
            "extra_calls": total_actual - total_effective,
            "required_total": total_req,
            "actual_total": total_actual,
            "avg_calls_per_case": round(total_tool_calls / total, 2) if total else 0.0,
            "usage": dict(sorted(tool_usage.items(), key=lambda kv: -kv[1])),
        },
        "args": {"accuracy": _pct(arg_pass, arg_total), "passed": arg_pass, "total": arg_total},
        "answer": {"pass_rate": _pct(answer_pass, answer_total), "passed": answer_pass, "total": answer_total},
        "guardrail": {
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "recall": _pct(tp, tp + fn),
            "precision": _pct(tp, tp + fp),
            "accuracy": _pct(tp + tn, tp + tn + fp + fn),
            "tripped": tp + fp,
            "total": tp + tn + fp + fn,
        },
        "latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 1) if latencies else 0.0,
        },
        "tokens": {
            "input": in_tok,
            "output": out_tok,
            "total": in_tok + out_tok,
            "avg_per_case": round((in_tok + out_tok) / total, 0) if total else 0,
            # 部分中转站/模型不返回 usage，此时 0 不代表"不耗 token"，必须区分
            "available": (in_tok + out_tok) > 0,
        },
        "categories": categories,
    }


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall) * 100, 1)


# 用于回归对比的标量指标：(显示名, 取值路径)
SCALARS: list[tuple[str, tuple[str, ...]]] = [
    ("用例通过率 %", ("pass_rate",)),
    ("断言通过率 %", ("check_pass_rate",)),
    ("路由准确率 %", ("routing", "accuracy")),
    ("工具召回 %", ("tools", "recall")),
    ("工具精确 %", ("tools", "precision")),
    ("工具 F1", ("tools", "f1")),
    ("参数准确率 %", ("args", "accuracy")),
    ("答案通过率 %", ("answer", "pass_rate")),
    ("护栏召回 %", ("guardrail", "recall")),
    ("护栏精确 %", ("guardrail", "precision")),
    ("P50 延迟 ms", ("latency_ms", "p50")),
    ("P95 延迟 ms", ("latency_ms", "p95")),
    ("平均 token", ("tokens", "avg_per_case")),
]


def pluck(summary: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = summary
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node
