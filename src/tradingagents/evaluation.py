"""Deterministic comparison records and exports for REQ-TA-FR-007 / PERF-001.

This layer consumes measurements; it does not run agents or change their output.
The module boundary was approved in the local four-round plan on 2026-11-16;
the team's formal architecture ADR is pending (no ADR approval is implied).
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import median
from typing import Literal

UNAVAILABLE = "unavailable"
Variant = Literal["baseline", "enhanced"]


def _number(value: float, name: str) -> None:
    """REQ-TA-FR-007: reject invalid measurements rather than inventing values."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a finite nonnegative number")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")


def _count(value: int, name: str) -> None:
    """REQ-TA-FR-007: counts must be nonnegative integers."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


@dataclass(frozen=True)
class EvaluationCase:
    """REQ-TA-FR-007: identify one stock at one canonical analysis date."""

    ticker: str
    analysis_date: str

    def __post_init__(self):
        # REQ-TA-FR-007: validate before any runner could be called.
        if not isinstance(self.ticker, str) or not self.ticker.strip():
            raise ValueError("ticker must be a nonempty string")
        try:
            parsed = date.fromisoformat(self.analysis_date)
        except (ValueError, TypeError) as exc:
            raise ValueError("analysis_date must be YYYY-MM-DD") from exc
        if parsed.isoformat() != self.analysis_date:
            raise ValueError("analysis_date must be YYYY-MM-DD")


@dataclass(frozen=True)
class TokenPricing:
    """REQ-TA-FR-007: explicit input/output prices per million tokens, in USD.

    The future runner must match this pricing to the model(s) it measures.
    This arithmetic layer makes no provider-price lookup or cost assumption.
    """

    input_per_million: float
    output_per_million: float

    def __post_init__(self):
        # REQ-TA-FR-007: zero prices are valid; missing prices are not inferred.
        _number(self.input_per_million, "input_per_million")
        _number(self.output_per_million, "output_per_million")


@dataclass(frozen=True)
class RunMetrics:
    """REQ-TA-FR-007 / PERF-001: a single observed run, including failures.

    None means unreported. usage_complete is true only when ALL LLM calls
    report both token counts; partial totals must never look like complete ones.
    Confidence is preserved as reported, not derived from the recommendation.
    """

    case: EvaluationCase
    variant: Variant
    repetition: int
    elapsed_seconds: float
    status: Literal["completed", "failed"] = "completed"
    llm_calls: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    usage_complete: bool = False
    debate_rounds: int | None = None
    recommendation: str | None = None
    confidence: str | float | None = None
    pricing: TokenPricing | None = None
    settings: dict = field(default_factory=dict)
    failure_reason: str | None = None

    def __post_init__(self):
        # REQ-TA-FR-007: keep bad telemetry out of exported comparisons.
        if not isinstance(self.case, EvaluationCase):
            raise ValueError("case must be an EvaluationCase")
        if self.variant not in {"baseline", "enhanced"}:
            raise ValueError("variant must be baseline or enhanced")
        _count(self.repetition, "repetition")
        if self.repetition == 0:
            raise ValueError("repetition must be at least 1")
        _number(self.elapsed_seconds, "elapsed_seconds")
        if self.status not in {"completed", "failed"}:
            raise ValueError("status must be completed or failed")
        for name in ("llm_calls", "tokens_in", "tokens_out", "debate_rounds"):
            value = getattr(self, name)
            if value is not None:
                _count(value, name)
        if not isinstance(self.usage_complete, bool):
            raise ValueError("usage_complete must be boolean")
        if self.usage_complete and (self.tokens_in is None or self.tokens_out is None):
            raise ValueError("complete usage requires input and output token counts")
        if self.pricing is not None and not isinstance(self.pricing, TokenPricing):
            raise ValueError("pricing must be TokenPricing or None")
        if self.recommendation is not None and not isinstance(self.recommendation, str):
            raise ValueError("recommendation must be a string or None")
        if self.confidence is not None and not isinstance(self.confidence, str):
            _number(self.confidence, "confidence")

    @property
    def total_tokens(self) -> int | None:
        """REQ-TA-FR-007: incomplete provider usage is never a complete total."""
        if not self.usage_complete:
            return None
        return self.tokens_in + self.tokens_out

    @property
    def estimated_cost_usd(self) -> float | None:
        """REQ-TA-FR-007: estimate only with complete usage and explicit pricing."""
        if self.total_tokens is None or self.pricing is None:
            return None
        cost = (self.tokens_in * self.pricing.input_per_million
                + self.tokens_out * self.pricing.output_per_million) / 1_000_000
        _number(cost, "estimated_cost_usd")
        return cost


def percentage_reduction(baseline: float | None, enhanced: float | None) -> float | None:
    """REQ-TA-FR-007: a slowdown is negative; zero/missing baselines are unknown."""
    for name, value in (("baseline", baseline), ("enhanced", enhanced)):
        if value is not None:
            _number(value, name)
    if baseline is None or enhanced is None or baseline == 0:
        return None
    reduction = (baseline - enhanced) / baseline * 100
    if not math.isfinite(reduction):
        raise ValueError("percentage reduction must be finite")
    return reduction


def _present(value):
    """REQ-TA-FR-007: serialize absent observations explicitly."""
    return UNAVAILABLE if value is None else value


def _run_row(run: RunMetrics) -> dict:
    """REQ-TA-FR-007: export an explicit field allowlist, never a raw config."""
    return {
        "settings": json.dumps(run.settings, sort_keys=True),
        "ticker": run.case.ticker,
        "analysis_date": run.case.analysis_date,
        "repetition": run.repetition,
        "variant": run.variant,
        "status": run.status,
        "failure_reason": _present(run.failure_reason),
        "elapsed_seconds": run.elapsed_seconds,
        "llm_calls": _present(run.llm_calls),
        "tokens_in": _present(run.tokens_in),
        "tokens_out": _present(run.tokens_out),
        "total_tokens": _present(run.total_tokens),
        "usage_status": ("complete" if run.usage_complete else
                         "partial" if run.tokens_in is not None or run.tokens_out is not None
                         else "unavailable"),
        "estimated_cost_usd": _present(run.estimated_cost_usd),
        "debate_rounds": _present(run.debate_rounds),
        "recommendation": _present(run.recommendation),
        "confidence": _present(run.confidence),
    }


@dataclass(frozen=True)
class ComparisonResult:
    """REQ-TA-FR-007: paired raw records and derived comparison exports."""

    runs: tuple[RunMetrics, ...]

    def __post_init__(self):
        # REQ-TA-FR-007: freeze input order and require exactly one run per side.
        object.__setattr__(self, "runs", tuple(self.runs))
        if not self.runs:
            raise ValueError("at least one baseline/enhanced pair is required")
        pairs = defaultdict(set)
        for run in self.runs:
            if not isinstance(run, RunMetrics):
                raise ValueError("runs must contain RunMetrics")
            key = (run.case, run.repetition)
            if run.variant in pairs[key]:
                raise ValueError("duplicate variant for the same case and repetition")
            pairs[key].add(run.variant)
        if any(variants != {"baseline", "enhanced"} for variants in pairs.values()):
            raise ValueError("each case and repetition requires baseline and enhanced")

    def comparison_rows(self) -> list[dict]:
        """REQ-TA-FR-007 / PERF-001: failed pairs never imply an improvement."""
        pairs = defaultdict(dict)
        for run in self.runs:
            pairs[(run.case, run.repetition)][run.variant] = run
        rows = []
        for (case, repetition), pair in pairs.items():
            baseline, enhanced = pair["baseline"], pair["enhanced"]
            comparable = baseline.status == enhanced.status == "completed"
            runtime = percentage_reduction(baseline.elapsed_seconds, enhanced.elapsed_seconds) if comparable else None
            tokens = percentage_reduction(baseline.total_tokens, enhanced.total_tokens) if comparable else None
            rows.append({
                "ticker": case.ticker,
                "analysis_date": case.analysis_date,
                "repetition": repetition,
                "comparison_status": "completed" if comparable else "failed_pair",
                "runtime_reduction_percent": _present(runtime),
                "token_reduction_percent": _present(tokens),
            })
        return rows

    def summary(self) -> dict:
        """REQ-TA-PERF-001: paired successful timings; failures remain visible."""
        rows = self.comparison_rows()
        valid = {(r['ticker'], r['analysis_date'], r['repetition'])
                 for r in rows if r['comparison_status'] == 'completed'}
        result = {'successful_pairs': len(valid), 'failed_pairs': len(rows) - len(valid),
                  'target': 'TBD', 'target_verdict': 'not_assessed'}
        medians = {}
        for variant in ('baseline', 'enhanced'):
            times = [r.elapsed_seconds for r in self.runs if r.variant == variant
                     and (r.case.ticker, r.case.analysis_date, r.repetition) in valid]
            medians[variant] = median(times) if times else None
            result[variant] = {'samples': len(times), 'median_seconds': _present(medians[variant]),
                               'min_seconds': min(times) if times else UNAVAILABLE,
                               'max_seconds': max(times) if times else UNAVAILABLE}
        result['median_runtime_reduction_percent'] = _present(
            percentage_reduction(medians['baseline'], medians['enhanced']))
        return result

    def to_dict(self) -> dict:
        """REQ-TA-FR-007: use the same measurement semantics in both formats."""
        return {
            "format_version": 1,
            "performance_target": "TBD",
            "summary": self.summary(),
            "runs": [_run_row(run) for run in self.runs],
            "comparisons": self.comparison_rows(),
        }


def export_comparison(result: ComparisonResult, destination: str | Path,
                      format: Literal["json", "csv"] = "json") -> Path:
    """REQ-TA-FR-007: export before a human reviews; never overwrite a file.

    JSON carries runs and comparisons; CSV has one row per run with the pair's
    reduction fields alongside it. JSON numbers never contain NaN/Infinity.
    """
    if format not in {"json", "csv"}:
        raise ValueError("format must be json or csv")
    data = result.to_dict()  # Validate/derive everything before opening a file.
    path = Path(destination)
    if format == "json":
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    else:
        paired = {(r["ticker"], r["analysis_date"], r["repetition"]): r
                  for r in data["comparisons"]}
        rows = [{**r, **paired[(r["ticker"], r["analysis_date"], r["repetition"])],
                 "performance_target": "TBD"} for r in data["runs"]]
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return path
