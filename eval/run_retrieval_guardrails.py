#!/usr/bin/env python
"""
Run phase-1 model eval (retrieval + guardrails) with classification factor sweeps.

Usage (from project root, CDP venv active):
  .venv-cdp/Scripts/python.exe eval/run_retrieval_guardrails.py
  .\.venv-cdp\Scripts\python.exe eval/run_retrieval_guardrails.py --top-k 3,5,8
  .\.venv-cdp\Scripts\python.exe eval/run_retrieval_guardrails.py --top-k 8 --temperature 0,0.1 --top-p 0.9,1.0
  .\.venv-cdp\Scripts\python.exe eval/run_retrieval_guardrails.py --use-env-grid

Requires: SUPABASE_URL, SUPABASE_KEY, migration + seed + embedding backfill.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eval.runner import load_golden_cases, parse_cli_factor_grid, run_eval, save_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase-1 retrieval + guardrails model eval")
    parser.add_argument(
        "--golden",
        type=Path,
        default=None,
        help="Path to cases.jsonl (default: eval/golden/cases.jsonl)",
    )
    parser.add_argument(
        "--top-k",
        default="8",
        help="Comma-separated retrieval top_k values (classification factor)",
    )
    parser.add_argument(
        "--temperature",
        default=None,
        help="Comma-separated LLM temperatures (recorded in phase 1; active in phase 2)",
    )
    parser.add_argument(
        "--top-p",
        default=None,
        help="Comma-separated LLM top_p values (recorded in phase 1; active in phase 2)",
    )
    parser.add_argument(
        "--use-env-grid",
        action="store_true",
        help="Use EVAL_TOP_K, EVAL_TEMPERATURE, EVAL_TOP_P from environment",
    )
    args = parser.parse_args()

    cases = load_golden_cases(args.golden) if args.golden else load_golden_cases()

    if args.use_env_grid:
        report = run_eval(cases=cases, use_env_grid=True)
    else:
        cli_args: list[str] = ["--top-k", args.top_k]
        if args.temperature is not None:
            cli_args.extend(["--temperature", args.temperature])
        if args.top_p is not None:
            cli_args.extend(["--top-p", args.top_p])
        grid = parse_cli_factor_grid(cli_args)
        report = run_eval(cases=cases, factor_grid=grid)

    out_path = save_report(report)
    overall = report["overall"]
    print(f"Eval report: {out_path}")
    print(
        f"Assertions: {overall['passed']}/{overall['total']} passed | "
        f"success={overall['success']} | errors={len(report['errors'])}"
    )
    for fid in report.get("factor_ids", []):
        subset = [r for r in report["results"] if r["factor_id"] == fid]
        ok = all(r["summary"]["success"] for r in subset)
        print(f"  factor_id={fid} -> {'PASS' if ok else 'FAIL'} ({len(subset)} case-runs)")

    if report["errors"]:
        for err in report["errors"]:
            print(f"  ERROR {err['case_id']} @ {err['factor_id']}: {err['error']}")
        return 1
    return 0 if overall["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
