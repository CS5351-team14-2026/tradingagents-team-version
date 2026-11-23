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

Provenance (S2): a per-run record keeps three things apart — the *model's own*
rating (``model_rating``, or ``None`` = unknown), the *application-validated*
rating and its review reasons (``applied_rating`` / ``applied_review_reasons``),
and the *evidence audit* result (``audit_status`` / ``audit_reasons``). A REVIEW
downgraded by the application is never labelled ``EXPLICIT_REVIEW``: it carries
``APP_VALIDATION_REVIEW`` (a real model call rejected for missing/invalid
prices) or ``UNKNOWN_MODEL_REVIEW`` (model intent not recoverable). Records with
no provenance (the archived historical baseline) keep their legacy behaviour.

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

# The fixed evidence set every *formal CI* evaluation must carry: exactly these
# case ids, each with its full run budget (S1 completeness contract). A report
# missing a case, repeating one, running a case the wrong number of times, or
# mis-numbering its runs is an INFRASTRUCTURE_ERROR — never a (partial) PASS.
REQUIRED_CASE_IDS: tuple[str, ...] = (
    "baseline_full_evidence_dated",
    "baseline_market_report_undated",
    "baseline_partial_reports",
)
# The full-evidence case must declare (and meet) its acceptance expectation.
FULL_EVIDENCE_CASE_ID = "baseline_full_evidence_dated"
# Every case is replayed exactly this many times, numbered 1..N.
REQUIRED_REPETITIONS = 3

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


def _model_explicit_review(run: Mapping[str, Any]) -> bool:
    """Whether the run carries *positive* evidence the model itself chose REVIEW.

    A ``REVIEW`` is a model choice only when a supplied ``model_rating`` is
    exactly ``"REVIEW"``. A missing/ambiguous rating (``None``), a validated
    rating produced only by the application, or a historical record with no
    provenance is **not** positive evidence.
    """
    return run.get("model_rating") == "REVIEW"


def _review_reason_zero_claims(run: Mapping[str, Any]) -> str:
    """The reason code for a complete, claim-less ``REVIEW`` record.

    A ``REVIEW`` with no claims is a valid, judgeable observation (never an
    infrastructure error). Its reason reflects *provenance*:

    - ``EXPLICIT_REVIEW`` only with positive evidence the model chose REVIEW;
    - ``APP_VALIDATION_REVIEW`` when the app downgraded a real call (origin
      ``app_validated``, or recorded validation reasons show the app's hand);
    - ``UNKNOWN_MODEL_REVIEW`` otherwise (e.g. a historical record with no
      provenance, or a missing/ambiguous model rating). A historical record is
      never labelled ``EXPLICIT_REVIEW`` without positive evidence.
    """
    if _model_explicit_review(run):
        return "EXPLICIT_REVIEW"
    if run.get("review_origin") == "app_validated" or list(
        run.get("applied_review_reasons") or run.get("decision_review_reasons") or []
    ):
        return "APP_VALIDATION_REVIEW"
    return "UNKNOWN_MODEL_REVIEW"


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

    # A complete record with no claims is a valid, judgeable REVIEW observation
    # when the validated rating is REVIEW. Its reason reflects provenance:
    # EXPLICIT_REVIEW only with positive model evidence, else APP_VALIDATION_REVIEW
    # (the app downgraded a real call) or UNKNOWN_MODEL_REVIEW (historical/no
    # evidence). It is never an infrastructure error.
    if not run.get("claims"):
        if run.get("final_rating") == "REVIEW":
            return {
                "decision": "REVIEW",
                "reasons": [_review_reason_zero_claims(run)],
                "blocks_merge": BLOCKS_MERGE["REVIEW"],
            }
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


def _is_valid_repetition(value: Any) -> bool:
    """Whether ``value`` is a genuine run number: an ``int`` that is not a bool.

    ``True``/``False`` are ``int`` subclasses and must not be accepted as 1/0.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _repetition_key(value: Any) -> Any:
    """A hashable comparison key for a repetition value (lists/None included)."""
    if _is_valid_repetition(value):
        return ("int", value)
    return ("other", repr(value))


def check_completeness(report: Mapping[str, Any]) -> dict[str, Any]:
    """Whether a report carries the full fixed evidence set (S1 completeness).

    A *formal CI* report must contain exactly the :data:`REQUIRED_CASE_IDS`,
    each once, each with exactly :data:`REQUIRED_REPETITIONS` runs numbered
    ``1..N``, and the full-evidence case (:data:`FULL_EVIDENCE_CASE_ID`) must
    declare ``expects_pass: true`` (a genuine boolean, not ``"false"``/``1``).
    Anything else is an INFRASTRUCTURE_ERROR: a missing, duplicated, under-run,
    mis-numbered or mis-declared report can never be judged PASS. Returns
    ``{"ok", "problems", <details>}``; ``problems`` is a list of fixed, safe
    codes naming exactly what is wrong:

    - ``missing_case:<id>`` — a required case is absent;
    - ``duplicate_case:<id>`` — a required case appears more than once;
    - ``unexpected_case:<id>`` — a case id outside the fixed set;
    - ``run_count:<id>=<n>`` — a case does not have the required run count;
    - ``invalid_repetition:<id>`` — a run number is not an ``int`` (e.g. a
      bool, string or list);
    - ``duplicate_repetition:<id>`` — a run number repeats in a case;
    - ``missing_repetition:<id>`` — run numbers are not exactly ``1..N``;
    - ``full_evidence_expects_pass`` — the full-evidence case's
      ``expects_pass`` is not the boolean ``true``.

    Never rewrites its input. This is purely structural; it does not decide the
    runs (that is :func:`decide_run`).
    """
    problems: list[str] = []
    cases = report.get("cases") or []
    by_id: dict[Any, list[Mapping[str, Any]]] = {}
    for case in cases:
        by_id.setdefault(case.get("id"), []).append(case)

    present_ids = [case.get("id") for case in cases]
    for case_id in REQUIRED_CASE_IDS:
        count = present_ids.count(case_id)
        if count == 0:
            problems.append(f"missing_case:{case_id}")
        elif count > 1:
            problems.append(f"duplicate_case:{case_id}")
    for case_id in present_ids:
        if case_id not in REQUIRED_CASE_IDS:
            problems.append(f"unexpected_case:{case_id}")

    for case_id in REQUIRED_CASE_IDS:
        for case in by_id.get(case_id, []):
            runs = case.get("runs") or []
            if len(runs) != REQUIRED_REPETITIONS:
                problems.append(f"run_count:{case_id}={len(runs)}")
            repetitions = [run.get("repetition") for run in runs]
            # Repetition numbers must be genuine ints ``1..N``. ``True``/``False``
            # are ``int`` subclasses in Python, so they are rejected explicitly;
            # any non-int (string, list, ...) is an invalid repetition, never a
            # crash. Comparing types first keeps the check free of ``TypeError``
            # on unhashable values like a list.
            if not all(_is_valid_repetition(r) for r in repetitions):
                problems.append(f"invalid_repetition:{case_id}")
            keys = [_repetition_key(r) for r in repetitions]
            if len(keys) != len(set(keys)):
                problems.append(f"duplicate_repetition:{case_id}")
            if sorted(
                r for r in repetitions if _is_valid_repetition(r)
            ) != list(range(1, REQUIRED_REPETITIONS + 1)):
                problems.append(f"missing_repetition:{case_id}")
            if case_id == FULL_EVIDENCE_CASE_ID and case.get("expects_pass") is not True:
                problems.append("full_evidence_expects_pass")

    # Deduplicate problem codes while preserving order (a case repeated once may
    # surface the same missing-case problem twice).
    seen: set[str] = set()
    unique = [p for p in problems if not (p in seen or seen.add(p))]
    return {
        "ok": not unique,
        "problems": unique,
        "required_case_ids": list(REQUIRED_CASE_IDS),
        "required_repetitions": REQUIRED_REPETITIONS,
    }


def decide_baseline(
    report: Mapping[str, Any],
    *,
    require_complete: bool = False,
) -> dict[str, Any]:
    """Decide an archived baseline report, per case and aggregated.

    ``report`` is the ``baseline.json`` shape: a top-level ``cases`` list, each
    with ``id`` and ``runs``. Returns per-case run decisions plus an overall
    decision (the most severe across all runs). Never rewrites its input.

    A report that is itself an ``INFRASTRUCTURE_ERROR``, that has no cases, or
    that has a case with no runs, is an INFRASTRUCTURE_ERROR — never a default
    PASS.

    ``require_complete`` is the *formal CI* switch: when true, the report must
    carry the full fixed evidence set (see :func:`check_completeness`). The
    default is false so single-case unit tests and the archived historical
    baseline keep their existing per-case behaviour; the CI entry
    (:func:`tools.sem_eval.ci_entry.evaluate_pr`) always passes true.
    """
    completeness = check_completeness(report)
    if require_complete and not completeness["ok"]:
        return {
            "thresholds": "TBD",
            "overall_decision": "INFRASTRUCTURE_ERROR",
            "blocks_merge": BLOCKS_MERGE["INFRASTRUCTURE_ERROR"],
            "cases": [],
            "reasons": ["INCOMPLETE_REPORT"],
            "completeness": completeness,
        }

    if report.get("status") == "INFRASTRUCTURE_ERROR" or report.get("evaluator_exception"):
        return {
            "thresholds": "TBD",
            "overall_decision": "INFRASTRUCTURE_ERROR",
            "blocks_merge": BLOCKS_MERGE["INFRASTRUCTURE_ERROR"],
            "cases": [],
            "reasons": ["top_level_infrastructure_error"],
            "completeness": completeness,
        }

    cases_in = report.get("cases") or []
    if not cases_in:
        return {
            "thresholds": "TBD",
            "overall_decision": "INFRASTRUCTURE_ERROR",
            "blocks_merge": BLOCKS_MERGE["INFRASTRUCTURE_ERROR"],
            "cases": [],
            "reasons": ["empty_report"],
            "completeness": completeness,
        }
    case_out: list[dict[str, Any]] = []
    overall = "PASS"
    # Whether every case that declares an acceptance expectation actually met it.
    full_evidence_ok = True
    for case in cases_in:
        run_decisions = []
        runs_in = case.get("runs") or []
        # Strict boolean: a full-evidence case must declare ``expects_pass: true``
        # explicitly; ``"false"``/``1`` are not acceptance declarations.
        expects_pass = case.get("expects_pass") is True
        if not runs_in:
            # A case with no run records cannot be judged: infrastructure error.
            if _severity("INFRASTRUCTURE_ERROR") < _severity(overall):
                overall = "INFRASTRUCTURE_ERROR"
            if expects_pass:
                full_evidence_ok = False
            case_out.append({
                "id": case.get("id"),
                "expects_pass": expects_pass,
                "runs": [],
                "decision": "INFRASTRUCTURE_ERROR",
                "reasons": ["missing_runs"],
                "meets_acceptance": False,
            })
            continue
        # Per-run PM decision (rating) and evidence-audit downgrade reasons are
        # recorded separately so the report shows both.
        for run in runs_in:
            finding = decide_run(run)
            validated_rating = run.get("final_rating")
            run_decisions.append({
                "repetition": run.get("repetition"),
                "decision": finding["decision"],
                "reasons": finding["reasons"],
                "blocks_merge": finding["blocks_merge"],
                # Legacy ``pm_decision`` stays the *validated* rating.
                "pm_decision": validated_rating,
                # Provenance (S2): the model's own rating (or None = unknown),
                # the validated rating + its reasons, and the audit result.
                "model_rating": run.get("model_rating"),
                "applied_rating": run.get("applied_rating", validated_rating),
                "applied_review_reasons": list(
                    run.get("applied_review_reasons")
                    or run.get("decision_review_reasons")
                    or []
                ),
                "review_origin": run.get("review_origin"),
                "audit_status": run.get("audit_status"),
                "audit_reasons": list(run.get("observed_reasons") or []),
            })
            if _severity(finding["decision"]) < _severity(overall):
                overall = finding["decision"]
        case_decision = _worst(d["decision"] for d in run_decisions)
        # A case "meets acceptance": for expects_pass cases, every run must be
        # PASS; for others, no hard defect (REVIEW is a recorded observation).
        if expects_pass:
            meets = all(d["decision"] == "PASS" for d in run_decisions)
            if not meets:
                full_evidence_ok = False
        else:
            meets = case_decision in ("PASS", "REVIEW")
        case_out.append({
            "id": case.get("id"),
            "expects_pass": expects_pass,
            "runs": run_decisions,
            "decision": case_decision,
            "meets_acceptance": meets,
        })

    # The whole group is PASS only if no hard failure/infra occurred AND every
    # full-evidence case met its acceptance condition. REVIEW-only cases stay
    # non-blocking. Any FAIL/INFRA already lowered ``overall`` above.
    if overall == "PASS" and not full_evidence_ok:
        overall = "REVIEW"
    return {
        "thresholds": "TBD",
        "overall_decision": overall,
        "blocks_merge": BLOCKS_MERGE[overall],
        "full_evidence_met": full_evidence_ok,
        "cases": case_out,
        "completeness": completeness,
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
    "FULL_EVIDENCE_CASE_ID",
    "REQUIRED_CASE_IDS",
    "REQUIRED_REPETITIONS",
    "UNKNOWN_SOURCE",
    "check_completeness",
    "decide_baseline",
    "decide_run",
]
