"""评测 CLI。

用法（在 python-backend 目录下）：

    python -m evaluation.run                       # 跑全量，默认 mock 数据源
    python -m evaluation.run --limit 3             # 冒烟：只跑前 3 条
    python -m evaluation.run --category guardrail  # 只跑某一类
    python -m evaluation.run --source live         # 用真实行情跑
    python -m evaluation.run --baseline results/before.json   # 与指定基线对比

每次运行都会：
1. 跑完数据集，逐条打印进度与判定；
2. 把完整轨迹写进 JSON（含每条断言的实际值，便于排障）；
3. 写一份 Markdown 报告（可直接贴进 README 或 PR）；
4. 如果 results/latest.json 已存在，自动把它当作基线做回归对比（可用 --baseline 覆盖）。

退出码：0 = 全部通过；1 = 有失败用例；2 = 配置/运行错误（便于接 CI）。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

from .dataset import DEFAULT_DATASET, DatasetError, filter_cases, load_cases

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m evaluation.run",
        description="A股智能助手的可量化评测",
    )
    ap.add_argument("--dataset", default=str(DEFAULT_DATASET), help="JSONL 数据集路径")
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "latest.json"), help="JSON 结果输出路径")
    ap.add_argument("--md", default=os.path.join(RESULTS_DIR, "latest.md"), help="Markdown 报告输出路径")
    ap.add_argument("--baseline", default=None, help="基线 JSON，用于回归对比")
    ap.add_argument("--no-auto-baseline", action="store_true", help="不自动对比上一次的 latest.json")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 条（冒烟测试）")
    ap.add_argument("--category", action="append", default=None, help="只跑指定类别，可重复")
    ap.add_argument("--ids", default=None, help="只跑指定 id，逗号分隔")
    ap.add_argument("--concurrency", type=int, default=3, help="并发用例数（默认 3，避免打爆接口限流）")
    ap.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="整套数据集重复跑 N 轮。模型有随机性，正式评估建议 3 轮看稳定性",
    )
    ap.add_argument(
        "--source",
        choices=["mock", "live", "auto"],
        default="mock",
        help="行情数据源。默认 mock：完全离线且确定性，适合回归；live 用真实行情",
    )
    ap.add_argument("--max-turns", type=int, default=8, help="单轮 agent 最大步数")
    ap.add_argument("--show-passed", action="store_true", help="终端里也列出通过的用例")
    ap.add_argument("--validate-only", action="store_true", help="只校验数据集格式，不调用模型")
    return ap.parse_args(argv)


def _prepare_env(source: str) -> None:
    """数据源必须在 import stock 之前定死（data.py 在 import 时读环境变量）。"""
    load_dotenv()
    os.environ["STOCK_DATA_SOURCE"] = source


async def _run_all(cases, *, concurrency: int, max_turns: int):
    from .checks import check_case
    from .metrics import CaseResult
    from .runner import run_case

    sem = asyncio.Semaphore(max(1, concurrency))
    total = len(cases)
    done = 0
    results: list[CaseResult] = []
    lock = asyncio.Lock()

    async def one(case):
        nonlocal done
        async with sem:
            trace = await run_case(case, max_turns=max_turns)
            checks = check_case(case, trace)
            res = CaseResult(case=case, trace=trace, checks=checks)
            async with lock:
                done += 1
                mark = "✓" if res.passed else "✗"
                print(
                    f"[{done:>2}/{total}] {mark} {case.id:<24} "
                    f"{trace.final_agent or '-':<26} {trace.latency_ms:>7.0f}ms",
                    flush=True,
                )
            return res

    results = await asyncio.gather(*(one(c) for c in cases))
    # gather 保序，与数据集顺序一致，报告更好读
    return list(results)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # 1) 数据集
    try:
        cases = load_cases(args.dataset)
    except DatasetError as exc:
        print(f"数据集错误：{exc}", file=sys.stderr)
        return 2

    cases = filter_cases(cases, args.category)
    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
        cases = [c for c in cases if c.id in wanted]
    if args.limit:
        cases = cases[: args.limit]

    if not cases:
        print("没有匹配到任何用例", file=sys.stderr)
        return 2

    print(f"数据集 {args.dataset}：选中 {len(cases)} 个用例")
    if args.validate_only:
        print("数据集格式校验通过")
        return 0

    # 2) 环境（必须在 import stock 之前）
    _prepare_env(args.source)

    if not os.environ.get("OPENAI_API_KEY"):
        print("缺少 OPENAI_API_KEY，请先在 python-backend/.env 里配置", file=sys.stderr)
        return 2

    # 3) OpenAI 客户端（含中转站 base_url / chat_completions 模式）+ 关闭 tracing。
    #    必须与 main.py 用同一套配置，否则评测请求会打到官方端点。
    from stock.openai_setup import configure_openai

    configure_openai()

    from .metrics import aggregate
    from .report import build_payload, dump_json, load_baseline, render_console, render_markdown
    from stock.agents import MODEL
    from stock import data as stock_data

    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t0 = time.perf_counter()

    print(f"数据源 {args.source}（provider={stock_data.PROVIDER_NAME}）　模型 {MODEL}　并发 {args.concurrency}")
    print("-" * 68)

    try:
        results = []
        summaries: list[dict] = []
        for round_idx in range(max(1, args.repeat)):
            if args.repeat > 1:
                print(f"\n--- 第 {round_idx + 1}/{args.repeat} 轮 ---")
            round_results = asyncio.run(_run_all(cases, concurrency=args.concurrency, max_turns=args.max_turns))
            summaries.append(aggregate(round_results))
            results = round_results  # 明细保留最后一轮，报告里展示的就是这一轮
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 2

    elapsed = time.perf_counter() - t0
    summary = summaries[-1]

    # 多轮时附带稳定性区间：单次 87% 和单次 95% 的差别可能全是噪声，
    # 给出极差才能判断"是不是真的退化了"。
    if len(summaries) > 1:
        rates = [s["pass_rate"] for s in summaries]
        summary = dict(summary)
        summary["stability"] = {
            "runs": len(rates),
            "pass_rates": rates,
            "mean": round(sum(rates) / len(rates), 1),
            "min": min(rates),
            "max": max(rates),
            "spread": round(max(rates) - min(rates), 1),
        }

    meta = {
        "dataset": os.path.basename(args.dataset),
        "cases": len(cases),
        "data_mode": args.source,
        "provider": stock_data.PROVIDER_NAME,
        "model": MODEL,
        "concurrency": args.concurrency,
        "started_at": started_at,
        "elapsed_s": round(elapsed, 1),
    }

    # 4) 基线（默认对比上一次的 latest.json，覆盖前先备份）
    baseline = None
    baseline_path = args.baseline
    if not baseline_path and not args.no_auto_baseline and os.path.exists(args.out):
        prev = os.path.join(os.path.dirname(args.out) or ".", "previous.json")
        try:
            shutil.copyfile(args.out, prev)
            baseline_path = prev
        except OSError:
            baseline_path = None
    if baseline_path:
        baseline = load_baseline(baseline_path)

    # 5) 输出
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(args.md) or ".", exist_ok=True)

    payload = build_payload(summary, results, meta=meta)
    dump_json(payload, args.out)

    console = render_console(
        summary, results, meta=meta, baseline=baseline, show_passed=args.show_passed
    )
    print()
    print(console)

    with open(args.md, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(summary, results, meta=meta, baseline=baseline))

    print(f"JSON  -> {args.out}")
    print(f"MD    -> {args.md}")
    if baseline_path:
        print(f"对比基线 -> {baseline_path}")

    return 0 if summary["failed_cases"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
