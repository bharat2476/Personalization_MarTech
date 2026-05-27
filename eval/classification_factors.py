"""
Classification factors for model eval.

Factors partition experiment results so you can compare runs by hyperparameters.
Phase 1 (retrieval + guardrails): only top_k affects behavior (vector match_count).
Phase 2 (LLM agent): temperature and top_p apply via martech_agent._build_llm().
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator


@dataclass(frozen=True)
class ClassificationFactors:
    """
    Hyperparameters treated as classification dimensions in eval reports.

    - top_k: retrieval ANN depth (semantic_product_search match_count).
             Also reserved for LLM max tool-result candidates in phase 2.
    - temperature: LLM sampling (phase 2 only; ignored in retrieval-only runs).
    - top_p: LLM nucleus sampling (phase 2 only; ignored in retrieval-only runs).
    """

    top_k: int = 8
    temperature: float | None = None
    top_p: float | None = None

    def __post_init__(self) -> None:
        if self.top_k < 1:
            raise ValueError("top_k must be >= 1")
        if self.temperature is not None and not (0.0 <= self.temperature <= 2.0):
            raise ValueError("temperature must be in [0, 2] when set")
        if self.top_p is not None and not (0.0 < self.top_p <= 1.0):
            raise ValueError("top_p must be in (0, 1] when set")

    @property
    def factor_id(self) -> str:
        """Stable key for grouping / pivoting eval results."""
        t = "na" if self.temperature is None else f"{self.temperature:g}"
        p = "na" if self.top_p is None else f"{self.top_p:g}"
        return f"top_k={self.top_k}|temp={t}|top_p={p}"

    @property
    def active_scopes(self) -> list[str]:
        scopes = ["retrieval"]
        if self.temperature is not None or self.top_p is not None:
            scopes.append("llm")
        return scopes

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def retrieval_kwargs(self) -> dict[str, Any]:
        return {"match_count": self.top_k}

    def llm_kwargs(self) -> dict[str, Any]:
        """Kwargs for ChatOpenAI when phase-2 agent eval is enabled."""
        out: dict[str, Any] = {}
        if self.temperature is not None:
            out["temperature"] = self.temperature
        if self.top_p is not None:
            out["top_p"] = self.top_p
        return out


def default_retrieval_grid() -> list[ClassificationFactors]:
    """Default top_k sweep for retrieval eval (temperature/top_p inactive)."""
    return [ClassificationFactors(top_k=k) for k in (3, 5, 8)]


def full_classification_grid(
    top_k_values: list[int] | None = None,
    temperatures: list[float] | None = None,
    top_p_values: list[float] | None = None,
) -> list[ClassificationFactors]:
    """
    Cartesian product of factor levels for stratified eval.

    Phase 1: pass only top_k_values (temperatures/top_p_values default to [None]).
    Phase 2: include temperatures and top_p_values to sweep LLM settings.
    """
    ks = top_k_values or [8]
    temps = temperatures if temperatures is not None else [None]
    ps = top_p_values if top_p_values is not None else [None]

    grid: list[ClassificationFactors] = []
    for k in ks:
        for t in temps:
            for p in ps:
                grid.append(ClassificationFactors(top_k=k, temperature=t, top_p=p))
    return grid


def iter_factor_grid_from_env() -> Iterator[ClassificationFactors]:
    """
    Optional env overrides (comma-separated lists):
      EVAL_TOP_K=3,5,8
      EVAL_TEMPERATURE=0,0.1,0.3
      EVAL_TOP_P=0.9,1.0
    """
    import os

    def _parse_ints(name: str, default: list[int]) -> list[int]:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        return [int(x.strip()) for x in raw.split(",") if x.strip()]

    def _parse_floats_or_none(name: str) -> list[float | None]:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return [None]
        if raw.lower() in ("na", "none", "-"):
            return [None]
        return [float(x.strip()) for x in raw.split(",") if x.strip()]

    return iter(
        full_classification_grid(
            top_k_values=_parse_ints("EVAL_TOP_K", [8]),
            temperatures=_parse_floats_or_none("EVAL_TEMPERATURE"),
            top_p_values=_parse_floats_or_none("EVAL_TOP_P"),
        )
    )


def factors_json_line(factors: ClassificationFactors) -> str:
    return json.dumps(factors.to_dict(), sort_keys=True)
