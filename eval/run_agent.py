#!/usr/bin/env python
"""
Phase-2 model eval: LLM agent with temperature, top_p, and top_k classification factors.

Requires OPENAI_API_KEY, Supabase CDP setup, and agent deps in .venv-cdp.

Usage:
  python eval/run_agent.py --demo
  python eval/run_agent.py --top-k 8 --temperature 0,0.1 --top-p 0.9,1.0
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eval.classification_factors import ClassificationFactors, full_classification_grid
from eval.metrics import check_guardrails, summarize_assertions
from eval.runner import parse_cli_factor_grid, save_report

AGENT_GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "agent_cases.jsonl"
ARTIFACTS_DIR = _ROOT / "artifacts" / "eval_runs"


def load_agent_cases(path: Path | None = None) -> list[dict]:
    p = path or AGENT_GOLDEN_PATH
    cases = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def _check_outcome_text(outcome: str, case: dict) -> list[dict]:
    text = outcome.lower()
    assertions: list[dict] = []

    for term in case.get("forbid_terms_in_outcome") or []:
        hit = term.lower() in text
        assertions.append(
            {
                "check": "forbid_term_in_outcome",
                "field": term,
                "passed": not hit,
                "actual": "present" if hit else "absent",
            }
        )

    for sku in case.get("expect_skus_in_outcome") or []:
        passed = sku in outcome
        assertions.append(
            {
                "check": "sku_in_outcome",
                "field": sku,
                "passed": passed,
                "actual": "present" if passed else "absent",
            }
        )

    return assertions


def run_agent_eval(
    cases: list[dict],
    factor_grid: list[ClassificationFactors],
    *,
    demo_mode: bool = False,
) -> dict:
    from martech_agent import evaluate_guardrails, execute_autonomous_campaign, execute_autonomous_campaign_demo

    started = datetime.now(timezone.utc).isoformat()
    results: list[dict] = []
    errors: list[dict] = []

    for factors in factor_grid:
        prev_match = os.environ.get("CDP_MATCH_COUNT")
        os.environ["CDP_MATCH_COUNT"] = str(factors.top_k)
        try:
            for case in cases:
                uid = case["user_id"]
                trigger = case["trigger"]
                try:
                    guardrails = evaluate_guardrails(uid)
                    guard_assertions = []
                    if case.get("expect_guardrails"):
                        guard_assertions = check_guardrails(
                            guardrails, case["expect_guardrails"]
                        )

                    if demo_mode:
                        report = execute_autonomous_campaign_demo(uid, trigger)
                    else:
                        report = execute_autonomous_campaign(
                            uid,
                            trigger,
                            temperature=factors.temperature,
                            top_p=factors.top_p,
                        )

                    outcome_assertions = _check_outcome_text(report, case)
                    all_a = guard_assertions + outcome_assertions
                    results.append(
                        {
                            "case_id": case["id"],
                            "suite": "agent",
                            "user_id": uid,
                            "demo_mode": demo_mode,
                            "classification_factors": factors.to_dict(),
                            "factor_id": factors.factor_id,
                            "llm_kwargs_applied": factors.llm_kwargs(),
                            "retrieval_top_k_env": factors.top_k,
                            "report_excerpt": report[-2000:] if len(report) > 2000 else report,
                            "assertions": all_a,
                            "summary": summarize_assertions(all_a),
                        }
                    )
                except Exception as exc:
                    errors.append(
                        {
                            "case_id": case.get("id"),
                            "factor_id": factors.factor_id,
                            "error": str(exc),
                        }
                    )
        finally:
            if prev_match is None:
                os.environ.pop("CDP_MATCH_COUNT", None)
            else:
                os.environ["CDP_MATCH_COUNT"] = prev_match

    total_passed = sum(r["summary"]["passed"] for r in results)
    total = sum(r["summary"]["total"] for r in results)

    return {
        "eval_phase": "2-llm-agent" if not demo_mode else "2-agent-demo-no-llm",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "golden_cases": len(cases),
        "classification_factor_combos": len(factor_grid),
        "factor_ids": sorted({r["factor_id"] for r in results}),
        "results": results,
        "errors": errors,
        "overall": {
            "passed": total_passed,
            "failed": total - total_passed,
            "total": total,
            "success": len(errors) == 0 and total > 0 and total_passed == total,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase-2 LLM agent model eval")
    parser.add_argument("--golden", type=Path, default=None)
    parser.add_argument("--top-k", default="8")
    parser.add_argument("--temperature", default="0.1")
    parser.add_argument("--top-p", default=None)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Deterministic demo agent (no OpenAI); still sweeps top_k via CDP_MATCH_COUNT",
    )
    args = parser.parse_args()

    cases = load_agent_cases(args.golden)
    cli_args = ["--top-k", args.top_k]
    if args.temperature:
        cli_args.extend(["--temperature", args.temperature])
    if args.top_p:
        cli_args.extend(["--top-p", args.top_p])
    grid = parse_cli_factor_grid(cli_args)

    report = run_agent_eval(cases, grid, demo_mode=args.demo)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "demo" if args.demo else "llm"
    out = ARTIFACTS_DIR / f"phase2_{suffix}_{stamp}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    overall = report["overall"]
    print(f"Agent eval report: {out}")
    print(f"Assertions: {overall['passed']}/{overall['total']} | success={overall['success']}")
    return 0 if overall["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
