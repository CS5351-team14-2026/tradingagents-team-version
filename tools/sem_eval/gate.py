"""Gate 4 gate-decision logic (offline, Phase 3B).

Turns an archived baseline report into a merge-gate decision, reusing the
existing report fields (``audit_status``, per-claim ``source`` /
``observation_date`` / ``attributed`` / ``reasons``, ``observation_notes``,
``evaluator_exception``). The baseline evidence is read-only input; this module
never rewrites it.

Decision vocabulary (per run, then aggregated):

- ``INFRASTRUCTURE_ERROR`` — the run could not be evaluated (``evaluator_exception``
  or a redacted ``error``). This is a gate-correctness failure, not a model verdict.
- ``FAIL`` — the run contains a hard defect:
    * an **unfounded market date**: a market claim dated when the source had no
      date (flagged ``date basis unverified``); or
    * an **unresolvable evidence source**: a claim whose resolved ``source`` is
      ``UNKNOWN``.
- ``REVIEW`` — evidence is thin (e.g. DOWNGRADED with unattributed claims) but
  there is **no** hard defect. This is recorded as an observation, not a block.
- ``PASS`` — every claim is attributed to a real source with grounded dates.

Numeric thresholds remain **TBD**: this module labels each finding block vs
observe, but nothing is wired to CI or branch protection and nothing blocks yet.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# Unfounded market-date signal emitted by the replay adapter.
DATE_BASIS_NOTE = "date basis unverified"
# Fixed marker for an unresolvable evidence source (display only).
UNKNOWN_SOURCE = "UNKNOWN"
# The audit reason code that actually proves a source is unresolvable.
UNKNOWN_SOURCE_CODE = "UNKNOWN_SOURCE"

# Decision levels, most severe first.
DECISIONS = ("INFRASTRUCTURE_ERROR", "FAIL", "REVIEW", "PASS")

# Which decision blocks a merge once thresholds are approved. Thresholds are
# TBD, so nothing actually blocks in this version; this table is the agreed
# *intent* for the team to ratify.
BLOCKS_MERGE = {"INFRASTRUCTURE_ERROR": True, "FAIL": True, "REVIEW": False, "PASS": False}


def _unfounded_market_date(run: Mapping[str, Any]) -> bool:
    return DATE_BASIS_NOTE in (run.get("observation_notes") or [])


def _has_unknown_source(run: Mapping[str, Any]) -> bool:
    """Whether the audit reported ``UNKNOWN_SOURCE`` for this run.

    This is decided from the **audit reason codes**, not from the display marker
    ``source == "UNKNOWN"``: a claim whose source is merely shown as ``UNKNOWN``
    (e.g. an undated market claim) is not an unresolvable-source failure.
    """
    if UNKNOWN_SOURCE_CODE in (run.get("observed_reasons") or []):
        return True
    return any(
        UNKNOWN_SOURCE_CODE in (claim.get("reasons") or [])
        for claim in run.get("claims", [])
    )


# Fields every complete run record must carry to be judged at all.
_REQUIRED_RUN_FIELDS = (
    "repetition",
    "audit_status",
    "claims_total",
    "claims_attributed",
    "final_rating",
    "evaluator_exception",
)


def _missing_required_fields(run: Mapping[str, Any]) -> bool:
    """Whether a run record is missing required fields (incomplete/infra)."""
    return any(field not in run for field in _REQUIRED_RUN_FIELDS)


def _explicit_review_zero_claims(run: Mapping[str, Any]) -> bool:
    """A complete report where the model explicitly returned REVIEW, no claims.

    This is a valid model outcome (it declined to commit), not a data problem:
    ``final_rating == "REVIEW"`` with ``claims_total == 0`` on an otherwise
    complete record.
    """
    return run.get("final_rating") == "REVIEW" and (run.get("claims_total") or 0) == 0


def decide_run(run: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one run into a gate finding (see module docstring).

    Returns ``{"decision", "reasons", "blocks_merge"}``. ``reasons`` is a list of
    fixed, safe codes (never raw claim text).

    A run missing required fields, or with no usable claims and no explicit
    REVIEW, is an INFRASTRUCTURE_ERROR — never a default PASS. But a *complete*
    report where the model explicitly returned REVIEW with zero claims is a
    valid model outcome and is judged REVIEW, not an infrastructure error.
    """
    # Missing required fields: the record is incomplete -> infrastructure error.
    if _missing_required_fields(run):
        return {
            "decision": "INFRASTRUCTURE_ERROR",
            "reasons": ["EMPTY_REPORT"],
            "blocks_merge": BLOCKS_MERGE["INFRASTRUCTURE_ERROR"],
        }
    if run.get("evaluator_exception") or run.get("error"):
        return {
            "decision": "INFRASTRUCTURE_ERROR",
            "reasons": ["evaluator_exception"],
            "blocks_merge": BLOCKS_MERGE["INFRASTRUCTURE_ERROR"],
        }

    # Complete record, but the model explicitly declined (REVIEW, no claims):
    # a valid observation, not a data problem.
    if _explicit_review_zero_claims(run):
        return {
            "decision": "REVIEW",
            "reasons": ["EXPLICIT_REVIEW"],
            "blocks_merge": BLOCKS_MERGE["REVIEW"],
        }

    # A complete record with no claims and no explicit REVIEW cannot be judged.
    if not run.get("claims"):
        return {
            "decision": "INFRASTRUCTURE_ERROR",
            "reasons": ["EMPTY_REPORT"],
            "blocks_merge": BLOCKS_MERGE["INFRASTRUCTURE_ERROR"],
        }

    reasons: list[str] = []
    if _unfounded_market_date(run):
        reasons.append("UNFOUNDED_MARKET_DATE")
    if _has_unknown_source(run):
        reasons.append("UNRESOLVABLE_SOURCE")

    if reasons:
        return {"decision": "FAIL", "reasons": reasons, "blocks_merge": BLOCKS_MERGE["FAIL"]}

    # No hard defect. A run whose only issue is the missing-date family
    # (UNDATED_MARKET_DATA / NO_DATED_OBSERVATION) with no unfounded date is an
    # observation (REVIEW), not a failure. Thin evidence is likewise REVIEW.
    total = run.get("claims_total") or 0
    attributed = run.get("claims_attributed") or 0
    if run.get("audit_status") == "ACCEPTED" and total > 0 and attributed == total:
        return {"decision": "PASS", "reasons": [], "blocks_merge": BLOCKS_MERGE["PASS"]}
    return {
        "decision": "REVIEW",
        "reasons": ["THIN_EVIDENCE"],
        "blocks_merge": BLOCKS_MERGE["REVIEW"],
    }


def decide_baseline(report: Mapping[str, Any]) -> dict[str, Any]:
    """Decide an archived baseline report, per case and aggregated.

    ``report`` is the ``baseline.json`` shape: a top-level ``cases`` list, each
    with ``id`` and ``runs``. Returns per-case run decisions plus an overall
    decision (the most severe across all runs). Never rewrites its input.

    A report that is itself an ``INFRASTRUCTURE_ERROR``, that has no cases, or
    that has a case with no runs, is an INFRASTRUCTURE_ERROR — never a default
    PASS.
    """
    if report.get("status") == "INFRASTRUCTURE_ERROR" or report.get("evaluator_exception"):
        return {
            "thresholds": "TBD",
            "overall_decision": "INFRASTRUCTURE_ERROR",
            "blocks_merge": BLOCKS_MERGE["INFRASTRUCTURE_ERROR"],
            "cases": [],
            "reasons": ["top_level_infrastructure_error"],
        }

    cases_in = report.get("cases") or []
    if not cases_in:
        return {
            "thresholds": "TBD",
            "overall_decision": "INFRASTRUCTURE_ERROR",
            "blocks_merge": BLOCKS_MERGE["INFRASTRUCTURE_ERROR"],
            "cases": [],
            "reasons": ["empty_report"],
        }
    case_out: list[dict[str, Any]] = []
    overall = "PASS"
    for case in cases_in:
        run_decisions = []
        runs_in = case.get("runs") or []
        if not runs_in:
            # A case with no run records cannot be judged: infrastructure error.
            case_decision = "INFRASTRUCTURE_ERROR"
            if _severity(case_decision) < _severity(overall):
                overall = case_decision
            case_out.append({
                "id": case.get("id"),
                "runs": [],
                "decision": case_decision,
                "reasons": ["missing_runs"],
            })
            continue
        for run in runs_in:
            finding = decide_run(run)
            run_decisions.append({
                "repetition": run.get("repetition"),
                "decision": finding["decision"],
                "reasons": finding["reasons"],
                "blocks_merge": finding["blocks_merge"],
            })
            if _severity(finding["decision"]) < _severity(overall):
                overall = finding["decision"]
        case_out.append({
            "id": case.get("id"),
            "runs": run_decisions,
            "decision": _worst(d["decision"] for d in run_decisions),
        })
    return {
        "thresholds": "TBD",
        "overall_decision": overall,
        "blocks_merge": BLOCKS_MERGE[overall],
        "cases": case_out,
    }


def _severity(decision: str) -> int:
    return DECISIONS.index(decision)


def _worst(decisions: Iterable[str]) -> str:
    decisions = list(decisions)
    if not decisions:
        return "PASS"
    return min(decisions, key=_severity)


__all__ = [
    "BLOCKS_MERGE",
    "DATE_BASIS_NOTE",
    "DECISIONS",
    "UNKNOWN_SOURCE",
    "decide_baseline",
    "decide_run",
]
