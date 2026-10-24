"""评测集加载与校验。

数据集是 JSONL：一行一个用例。必填 `id` / `category`，以及 `input` 或 `turns` 二选一。
`expect` 里每个键对应一类断言，具体语义见 checks.py。

设计约定：断言只看**结构性事实**（路由到谁、调了什么工具、参数落在哪个集合、答案含哪些
要素），不硬编码价格或涨跌幅数字 —— 否则行情一变，评测就假失败。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "core.jsonl"

# expect 里允许出现的断言键
KNOWN_EXPECT_KEYS = {
    "final_agent",
    "final_agent_in",
    "tools_required",
    "tools_allowed",
    "tools_forbidden",
    "arg_checks",
    "answer_contains",
    "answer_contains_any",
    "answer_not_contains",
    "guardrail",
}


@dataclass
class Case:
    id: str
    category: str
    turns: list[str]
    expect: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    @property
    def title(self) -> str:
        """用于报告展示的单行标题：多轮用例把每轮用 -> 连起来。"""
        return " -> ".join(self.turns)


class DatasetError(ValueError):
    """数据集格式错误。"""


def load_cases(path: str | Path = DEFAULT_DATASET) -> list[Case]:
    path = Path(path)
    if not path.exists():
        raise DatasetError(f"数据集不存在：{path}")

    cases: list[Case] = []
    seen: set[str] = set()

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        where = f"{path.name}:{lineno}"
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{where} JSON 解析失败：{exc}") from exc

        case = _build_case(obj, where)
        if case.id in seen:
            raise DatasetError(f"{where} id 重复：{case.id}")
        seen.add(case.id)
        cases.append(case)

    if not cases:
        raise DatasetError(f"数据集为空：{path}")
    return cases


def _build_case(obj: dict[str, Any], where: str) -> Case:
    if not isinstance(obj, dict):
        raise DatasetError(f"{where} 每行必须是 JSON 对象")

    cid = obj.get("id")
    if not cid or not isinstance(cid, str):
        raise DatasetError(f"{where} 缺少合法的 id")

    category = obj.get("category") or "uncategorized"

    turns = obj.get("turns")
    single = obj.get("input")
    if turns is not None:
        if not isinstance(turns, list) or not turns or not all(isinstance(t, str) for t in turns):
            raise DatasetError(f"{where} turns 必须是非空字符串数组")
        if single is not None:
            raise DatasetError(f"{where} input 与 turns 不能同时出现")
        turns = [t.strip() for t in turns]
    elif isinstance(single, str) and single.strip():
        turns = [single.strip()]
    else:
        raise DatasetError(f"{where} 必须提供 input 或 turns")

    expect = obj.get("expect") or {}
    if not isinstance(expect, dict):
        raise DatasetError(f"{where} expect 必须是对象")
    unknown = set(expect) - KNOWN_EXPECT_KEYS
    if unknown:
        # 打错键名会让断言静默失效，所以直接报错而不是忽略
        raise DatasetError(f"{where} expect 含未知断言键：{sorted(unknown)}")

    for key in (
        "tools_required",
        "tools_allowed",
        "tools_forbidden",
        "answer_contains",
        "answer_contains_any",
        "answer_not_contains",
    ):
        val = expect.get(key)
        if val is not None and (not isinstance(val, list) or not all(isinstance(v, str) for v in val)):
            raise DatasetError(f"{where} expect.{key} 必须是字符串数组")

    for chk in expect.get("arg_checks") or []:
        if not isinstance(chk, dict) or "tool" not in chk or "param" not in chk:
            raise DatasetError(f"{where} arg_checks 每项需要 tool 与 param")
        if not ({"in", "equals", "contains", "regex"} & set(chk)):
            raise DatasetError(f"{where} arg_checks 需要 in/equals/contains/regex 之一")

    gr = expect.get("guardrail")
    if gr is not None and gr not in {"trip", "pass"}:
        raise DatasetError(f"{where} expect.guardrail 只能是 trip 或 pass")

    return Case(id=cid, category=category, turns=turns, expect=expect, note=obj.get("note", ""))


def filter_cases(cases: list[Case], categories: list[str] | None = None) -> list[Case]:
    if not categories:
        return cases
    wanted = {c.strip() for c in categories if c.strip()}
    return [c for c in cases if c.category in wanted]
