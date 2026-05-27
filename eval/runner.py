"""
Phase-1 model eval: retrieval + guardrails against golden cases × classification factors.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# Project root on path when run as script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eval.classification_factors import (
    ClassificationFactors,
    default_retrieval_grid,
    full_classification_grid,
    iter_factor_grid_from_env,
)
from eval.metrics import check_guardrails, check_retrieval, summarize_assertions

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "cases.jsonl"
ARTIFACTS_DIR = _ROOT / "artifacts" / "eval_runs"


def load_golden_cases(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or GOLDEN_PATH
    cases: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def _run_guardrails_case(
    case: dict[str, Any],
    factors: ClassificationFactors,
) -> dict[str, Any]:
    from martech_agent import evaluate_guardrails

    user_id = case["user_id"]
    actual = evaluate_guardrails(user_id)
    expected = case.get("expect_guardrails") or {}
    assertions = check_guardrails(actual, expected)

    return {
        "case_id": case["id"],
        "suite": "guardrails",
        "user_id": user_id,
        "classification_factors": factors.to_dict(),
        "factor_id": factors.factor_id,
        "factor_scopes_active": factors.active_scopes,
        "llm_kwargs_note": (
            "temperature/top_p not applied in phase-1"
            if not factors.llm_kwargs()
            else factors.llm_kwargs()
        ),
        "actual": actual,
        "assertions": assertions,
        "summary": summarize_assertions(assertions),
    }


def _run_retrieval_case(
    case: dict[str, Any],
    factors: ClassificationFactors,
) -> dict[str, Any]:
    from martech_agent import evaluate_guardrails, search_inventory

    user_id = case["user_id"]
    query = case.get("search_query", "")
    guardrails = evaluate_guardrails(user_id)
    products = search_inventory(
        query,
        user_id=user_id,
        match_count=factors.top_k,
    )

    retrieval_assertions = check_retrieval(
        products,
        expect_skus_in_top_k=case.get("expect_skus_in_top_k"),
        forbid_product_types_in_top_k=case.get("forbid_product_types_in_top_k"),
        top_k=factors.top_k,
    )

    guard_expected = case.get("expect_guardrails") or {}
    guard_assertions = check_guardrails(guardrails, guard_expected) if guard_expected else []

    all_assertions = guard_assertions + retrieval_assertions

    return {
        "case_id": case["id"],
        "suite": "retrieval",
        "user_id": user_id,
        "search_query": query,
        "classification_factors": factors.to_dict(),
        "factor_id": factors.factor_id,
        "factor_scopes_active": factors.active_scopes,
        "retrieval_kwargs_applied": factors.retrieval_kwargs(),
        "llm_kwargs_note": factors.llm_kwargs() or "inactive (phase-1)",
        "guardrails": guardrails,
        "retrieved_count": len(products),
        "retrieved_skus": [p.get("sku") for p in products[: factors.top_k]],
        "assertions": all_assertions,
        "summary": summarize_assertions(all_assertions),
    }


def _suite_for_case(case: dict[str, Any]) -> str:
    if case.get("search_query"):
        return "retrieval"
    return "guardrails"


def run_eval(
    cases: list[dict[str, Any]] | None = None,
    factor_grid: list[ClassificationFactors] | None = None,
    *,
    use_env_grid: bool = False,
) -> dict[str, Any]:
    cases = cases or load_golden_cases()
    if factor_grid is None:
        factor_grid = (
            list(iter_factor_grid_from_env())
            if use_env_grid
            else default_retrieval_grid()
        )

    started = datetime.now(timezone.utc).isoformat()
    run_results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for factors in factor_grid:
        for case in cases:
            suite = _suite_for_case(case)
            try:
                if suite == "retrieval":
                    run_results.append(_run_retrieval_case(case, factors))
                else:
                    run_results.append(_run_guardrails_case(case, factors))
            except Exception as exc:
                errors.append(
                    {
                        "case_id": case.get("id"),
                        "factor_id": factors.factor_id,
                        "error": str(exc),
                    }
                )

    total_assertions = sum(r["summary"]["total"] for r in run_results)
    total_passed = sum(r["summary"]["passed"] for r in run_results)
    factor_ids = sorted({r["factor_id"] for r in run_results})

    report = {
        "eval_phase": "1-retrieval-guardrails",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "golden_cases": len(cases),
        "classification_factor_combos": len(factor_grid),
        "factor_ids": factor_ids,
        "classification_factors_schema": {
            "top_k": "active — maps to semantic_product_search(match_count)",
            "temperature": "recorded — LLM phase 2 only",
            "top_p": "recorded — LLM phase 2 only",
        },
        "results": run_results,
        "errors": errors,
        "overall": {
            "passed": total_passed,
            "failed": total_assertions - total_passed,
            "total": total_assertions,
            "success": len(errors) == 0 and total_passed == total_assertions,
        },
    }
    return report


def save_report(report: dict[str, Any]) -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ARTIFACTS_DIR / f"phase1_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def parse_cli_factor_grid(args: list[str]) -> list[ClassificationFactors]:
    """Parse --top-k 3,5,8 [--temperature 0.1] [--top-p 0.9] from argv tail."""
    top_k_vals = [8]
    temps: list[float | None] = [None]
    top_ps: list[float | None] = [None]

    i = 0
    while i < len(args):
        if args[i] == "--top-k" and i + 1 < len(args):
            top_k_vals = [int(x) for x in args[i + 1].split(",")]
            i += 2
        elif args[i] == "--temperature" and i + 1 < len(args):
            temps = [float(x) for x in args[i + 1].split(",")]
            i += 2
        elif args[i] == "--top-p" and i + 1 < len(args):
            top_ps = [float(x) for x in args[i + 1].split(",")]
            i += 2
        else:
            i += 1

    return full_classification_grid(
        top_k_values=top_k_vals,
        temperatures=temps,
        top_p_values=top_ps,
    )
