"""断言判定：把「期望」和「实际轨迹」比对成一组可数的检查项。

每个断言产出一条 CheckResult，metrics.py 只做计数，不参与判定逻辑 ——
这样指标口径全部收敛在这个文件里，改规则只改一处。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .dataset import Case
from .runner import CaseTrace


@dataclass
class CheckResult:
    case_id: str
    kind: str  # routing / tool / arg / answer / guardrail / runtime
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "kind": self.kind, "passed": self.passed, "detail": self.detail}


def _norm(s: Any) -> str:
    return str(s).strip().lower()


def _match_in(actual: Any, options: list[str]) -> bool:
    """宽松成员匹配：允许带市场后缀/括号注释/大小写差异。

    例：期望集合里有 600519，实际传 600519.SH 也算命中。
    """
    a = _norm(actual)
    if not a:
        return False
    return any(_norm(o) == a or _norm(o) in a or a in _norm(o) for o in options)


def check_case(case: Case, trace: CaseTrace) -> list[CheckResult]:
    checks: list[CheckResult] = []
    expect = case.expect

    # 执行层面直接失败时，所有断言都算不通过（并给出原始错误）
    if trace.error:
        checks.append(
            CheckResult(case.id, "runtime", False, f"执行异常：{trace.error}")
        )
        return checks

    # ---------- 护栏 ----------
    if "guardrail" in expect:
        want_trip = expect["guardrail"] == "trip"
        tripped = trace.guardrail_tripped is not None
        if want_trip:
            checks.append(
                CheckResult(
                    case.id,
                    "guardrail",
                    tripped,
                    f"期望拦截，实际{'拦截（' + str(trace.guardrail_tripped) + '）' if tripped else '放行'}",
                )
            )
        else:
            checks.append(
                CheckResult(
                    case.id,
                    "guardrail",
                    not tripped,
                    "期望放行，实际放行" if not tripped else f"误拦截（{trace.guardrail_tripped}）",
                )
            )

    # ---------- 路由 ----------
    if "final_agent" in expect:
        want = expect["final_agent"]
        got = trace.final_agent
        checks.append(
            CheckResult(case.id, "routing", got == want, f"期望 {want}，实际 {got or '无'}")
        )
    if "final_agent_in" in expect:
        want_list = expect["final_agent_in"]
        got = trace.final_agent
        checks.append(
            CheckResult(
                case.id,
                "routing",
                got in want_list,
                f"期望 {want_list} 之一，实际 {got or '无'}",
            )
        )

    # ---------- 工具选择 ----------
    called = trace.tool_names
    for tool in expect.get("tools_required", []):
        hit = tool in called
        checks.append(
            CheckResult(
                case.id,
                "tool",
                hit,
                f"必须调用 {tool}，实际调用 {called or '无'}",
            )
        )
    for tool in expect.get("tools_forbidden", []):
        hit = tool in called
        checks.append(
            CheckResult(
                case.id,
                "tool",
                not hit,
                f"禁止调用 {tool}，实际{'调用了' if hit else '未调用'}",
            )
        )

    # ---------- 工具参数 ----------
    for spec in expect.get("arg_checks", []):
        tool = spec["tool"]
        param = spec["param"]
        # 同一工具可能被调用多次，任意一次满足即算通过
        candidates = [
            (c.args or {}).get(param)
            for c in trace.tool_calls
            if c.name == tool and isinstance(c.args, dict)
        ]
        candidates = [c for c in candidates if c not in (None, "")]

        if not candidates:
            checks.append(
                CheckResult(
                    case.id,
                    "arg",
                    False,
                    f"{tool}.{param} 未被传值（该工具调用：{[c.args for c in trace.tool_calls if c.name == tool] or '无'}）",
                )
            )
            continue

        ok = False
        for val in candidates:
            if "in" in spec and _match_in(val, spec["in"]):
                ok = True
            elif "equals" in spec and _norm(val) == _norm(spec["equals"]):
                ok = True
            elif "contains" in spec and _norm(spec["contains"]) in _norm(val):
                ok = True
            elif "regex" in spec and re.search(spec["regex"], str(val)):
                ok = True
            if ok:
                break

        target = spec.get("in") or spec.get("equals") or spec.get("contains") or spec.get("regex")
        checks.append(
            CheckResult(
                case.id,
                "arg",
                ok,
                f"{tool}.{param} 实际={candidates}，期望={target}",
            )
        )

    # ---------- 答案要素 ----------
    answer = trace.answer or ""
    low = answer.lower()

    for needle in expect.get("answer_contains", []):
        hit = needle.lower() in low
        checks.append(
            CheckResult(case.id, "answer", hit, f"答案应包含「{needle}」，{'已包含' if hit else '缺失'}")
        )

    any_list = expect.get("answer_contains_any", [])
    if any_list:
        hit_any = any(n.lower() in low for n in any_list)
        checks.append(
            CheckResult(
                case.id,
                "answer",
                hit_any,
                f"答案应至少包含 {any_list} 之一，{'命中' if hit_any else '全部缺失'}",
            )
        )

    for needle in expect.get("answer_not_contains", []):
        hit = needle.lower() in low
        checks.append(
            CheckResult(
                case.id,
                "answer",
                not hit,
                f"答案不应出现「{needle}」，{'却出现了' if hit else '未出现'}",
            )
        )

    if not checks:
        # 数据集里既没写断言也没出错，属于配置疏漏，标记出来
        checks.append(
            CheckResult(case.id, "runtime", False, "该用例没有任何断言，请检查 expect")
        )

    return checks
