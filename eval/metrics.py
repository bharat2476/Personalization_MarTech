"""
Deterministic checks for retrieval + guardrails golden cases.
"""

from __future__ import annotations

from typing import Any


def _get_path(obj: dict[str, Any], dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def check_guardrails(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return list of assertion dicts: {field, expected, actual, passed}."""
    results: list[dict[str, Any]] = []
    for key, exp in expected.items():
        act = actual.get(key)
        passed = act == exp
        results.append(
            {
                "field": key,
                "expected": exp,
                "actual": act,
                "passed": passed,
            }
        )
    return results


def check_retrieval(
    products: list[dict[str, Any]],
    *,
    expect_skus_in_top_k: list[str] | None = None,
    forbid_product_types_in_top_k: list[str] | None = None,
    top_k: int,
) -> list[dict[str, Any]]:
    """Assert SKU presence and forbidden product_type in the retrieved slice."""
    results: list[dict[str, Any]] = []
    slice_products = products[:top_k]
    skus = [str(p.get("sku", "")) for p in slice_products]
    types = [str(p.get("product_type", "")) for p in slice_products]

    if expect_skus_in_top_k:
        for sku in expect_skus_in_top_k:
            passed = sku in skus
            results.append(
                {
                    "check": "sku_in_top_k",
                    "field": sku,
                    "expected": True,
                    "actual": sku in skus,
                    "passed": passed,
                    "retrieved_skus": skus,
                }
            )

    if forbid_product_types_in_top_k:
        for ptype in forbid_product_types_in_top_k:
            hits = [s for s, t in zip(skus, types) if t == ptype]
            passed = len(hits) == 0
            results.append(
                {
                    "check": "forbid_product_type_in_top_k",
                    "field": ptype,
                    "expected": "absent",
                    "actual": hits or "absent",
                    "passed": passed,
                    "retrieved_skus": skus,
                }
            )

    if not expect_skus_in_top_k and not forbid_product_types_in_top_k:
        results.append(
            {
                "check": "non_empty_retrieval",
                "passed": len(slice_products) > 0,
                "actual_count": len(slice_products),
            }
        )

    return results


def summarize_assertions(assertions: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for a in assertions if a.get("passed"))
    total = len(assertions)
    return {
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "success": passed == total and total > 0,
    }
