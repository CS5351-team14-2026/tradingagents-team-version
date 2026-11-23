"""Portfolio Manager replay adapter (Gate 4, Phase 2A).

Runs the *production* Portfolio Manager node (:func:`tradingagents.agents.managers.
portfolio_manager.create_portfolio_manager`) against a frozen input taken from
the Phase 1 fixtures, with only the analyst reports / plans / debate kept. The
PM's own output is merged back into the state and scored by the **existing**
deterministic claim audit (:func:`tradingagents.reporting.audit_material_claims`),
so there is one scoring path for offline pre-check and replay.

Nothing here is a semantic PASS. Thresholds are TBD, so a replay reports
``status="OBSERVE"`` (with ``exit_code=0``) and prints the observations; turning
those observations into PASS/FAIL is a later, human-approved threshold gate.

The model is not built here for tests: callers pass ``llm_factory``; the real
default uses the application's existing ``deep`` tier configuration
(:func:`tradingagents.llm_clients.factory.create_tier_client`). Tests inject a
double and never touch the network.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.rating import RATINGS_5_TIER, extract_rating
from tradingagents.reporting import audit_material_claims

# Mode label for replay results; distinct from the offline pre-check.
MODE_SEMANTIC_REPLAY = "semantic_replay"
REPLAY_STATUS = "OBSERVE"

# Provenance labels distinguish *where* a run's REVIEW came from:
# - ``"model_explicit"`` — only with positive evidence the model itself chose
#   REVIEW (a supplied ``model_rating == "REVIEW"``);
# - ``"app_validated"`` — the model made a real call (e.g. Buy) that the
#   application's *price policy* downgraded to REVIEW (a known canonical model
#   rating, or recorded validation reasons);
# - ``"unknown"`` — REVIEW with no such evidence (e.g. a missing or unparseable
#   rating, or a historical record without provenance).
REVIEW_ORIGIN_MODEL = "model_explicit"
REVIEW_ORIGIN_APP = "app_validated"
REVIEW_ORIGIN_UNKNOWN = "unknown"

# The five canonical ratings are the only values ``extract_rating`` may return;
# it never yields the ``REVIEW`` sentinel (that is not a tradeable rating).
_CANONICAL_RATINGS = frozenset(RATINGS_5_TIER)

# Output keys the PM node produces. They must be stripped from a fixture input
# so a replay measures *this* model call, not pre-written claims.
_OUTPUT_KEYS = (
    "final_trade_decision",
    "final_rating",
    "pm_confidence",
    "decision_review_reasons",
    "final_prices",
    "material_claims",
    "claim_fallback",
)

# Risk-debate keys the PM node reads unconditionally; a bare fixture may omit
# some, so the adapter fills them with empty defaults.
_RISK_DEBATE_DEFAULTS = {
    "history": "",
    "aggressive_history": "",
    "conservative_history": "",
    "neutral_history": "",
    "latest_speaker": "",
    "current_aggressive_response": "",
    "current_conservative_response": "",
    "current_neutral_response": "",
    "count": 0,
}


def build_pm_state(case_state: Mapping[str, Any]) -> dict[str, Any]:
    """A clean PM input: fixture state minus any pre-written decision/claims."""
    state = copy.deepcopy(dict(case_state))
    for key in _OUTPUT_KEYS:
        state.pop(key, None)
    risk = dict(_RISK_DEBATE_DEFAULTS)
    risk.update(state.get("risk_debate_state") or {})
    state["risk_debate_state"] = risk
    return state


#: A factory returning a model that supports ``with_structured_output``.
LlmFactory = Callable[[], Any]


def default_llm_factory(config: Mapping[str, Any] | None = None) -> LlmFactory:
    """A factory that builds the real ``deep`` tier client from the app config.

    Imported lazily so tests that inject a double never import provider SDKs.
    """
    def _factory() -> Any:
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.llm_clients.factory import create_tier_client

        cfg = dict(DEFAULT_CONFIG)
        if config:
            cfg.update(config)
        client = create_tier_client(cfg, "deep")
        return client.get_llm() if hasattr(client, "get_llm") else client

    return _factory


def provider_llm_factory(provider: str, model: str) -> LlmFactory:
    """A factory for an explicit ``provider`` + ``model`` (deep-tier replay).

    The provider client reads its credential from the environment
    (``llm_clients.api_key_env``); this adapter never takes or stores a key.
    Built lazily so tests that inject a double never import provider SDKs.
    """
    def _factory() -> Any:
        from tradingagents.llm_clients.factory import create_llm_client

        client = create_llm_client(provider=provider, model=model)
        return client.get_llm() if hasattr(client, "get_llm") else client

    return _factory


def _error_result(case_id: Any, error: str) -> dict[str, Any]:
    """A redacted, typed replay result for one case (never a PASS/observation)."""
    return {
        "id": case_id if isinstance(case_id, str) and case_id else "<unknown>",
        "audit_status": None,
        "observed_status": None,
        "observed_reasons": [],
        "claims_total": None,
        "claims_attributed": None,
        "unsupported_claim_ids": [],
        "final_rating": None,
        "confidence": None,
        "decision_review_reasons": [],
        # Provenance is unknown on an error: no model intent was recovered.
        "model_rating": None,
        "applied_rating": None,
        "applied_review_reasons": [],
        "review_origin": REVIEW_ORIGIN_UNKNOWN,
        "matches_expectation": False,
        "evaluator_exception": True,
        "error": error,
    }


def _recover_model_rating(produced: Mapping[str, Any]) -> str | None:
    """The model's own rating, recovered only from a controlled render.

    ``final_trade_decision`` is trustworthy for provenance **only** on the
    structured / JSON-mode path, where the production node renders a typed
    decision with :func:`tradingagents.agents.schemas.render_pm_decision`. On the
    free-text fallback the field holds *raw model prose*, which this adapter must
    never parse or emit, so the rating is reported unknown. The function returns
    one of the five canonical ratings, or ``None`` when it cannot be recovered —
    it never returns the ``REVIEW`` sentinel, which :func:`extract_rating` does
    not yield.
    """
    if produced.get("claim_fallback") is not None:
        # Free-text fallback: ``final_trade_decision`` is model prose, not a
        # controlled render. Do not trust it for provenance.
        return None
    rating = extract_rating(produced.get("final_trade_decision") or "")
    return rating if rating in _CANONICAL_RATINGS else None


def _review_origin(
    model_rating: str | None,
    applied_rating: str | None,
    applied_review_reasons: list[str],
) -> str | None:
    """Classify where an applied ``REVIEW`` came from (see the ``REVIEW_ORIGIN_*``).

    Returns ``None`` when the run was not a REVIEW. ``model_explicit`` is used
    only with **positive** evidence that the model itself chose REVIEW (a supplied
    ``model_rating == "REVIEW"``). Otherwise an application validation origin is
    reported when recorded evidence shows the app downgraded a real call — a known
    canonical model rating, or recorded validation reasons — and ``unknown`` when
    there is no such evidence (e.g. a historical record with no provenance).
    """
    if applied_rating != "REVIEW":
        return None
    if model_rating == "REVIEW":
        return REVIEW_ORIGIN_MODEL
    if model_rating in _CANONICAL_RATINGS or applied_review_reasons:
        return REVIEW_ORIGIN_APP
    return REVIEW_ORIGIN_UNKNOWN


def run_case(case: Mapping[str, Any], llm_factory: LlmFactory) -> dict[str, Any]:
    """Replay one case through the production PM node and audit its claims.

    The PM node returns only the keys it sets; those are merged back into the
    full input state so the audit sees the analyst reports alongside the
    decision's claims. Returns the Phase 1 shape plus replay-only fields.

    An invalid case input (missing/ill-typed ``state``, ``expected_status`` or
    ``expected_reasons``), a node/replay exception, or an audit exception all
    become a redacted ``evaluator_exception`` result — never a fabricated pass
    and never a raw exception message.
    """
    case_id = case.get("id") if isinstance(case, Mapping) else None
    if not isinstance(case, Mapping):
        return _error_result(case_id, "case_schema_error:not_a_mapping")
    state = case.get("state")
    if not isinstance(state, Mapping):
        return _error_result(case_id, "case_schema_error:missing_state")
    if "expected_status" in case and not isinstance(case["expected_status"], str):
        return _error_result(case_id, "case_schema_error:expected_status")
    if "expected_reasons" in case:
        reasons = case["expected_reasons"]
        if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
            return _error_result(case_id, "case_schema_error:expected_reasons")

    try:
        base_state = build_pm_state(state)
        node = create_portfolio_manager(llm_factory())
        produced = node(base_state)
    except Exception as exc:  # noqa: BLE001 - surfaced as a typed error, never hidden
        return _error_result(case_id, f"replay_error:{type(exc).__name__}")

    merged = dict(base_state)
    merged.update(produced)
    try:
        audit = audit_material_claims(merged)
    except Exception as exc:  # noqa: BLE001 - an audit panic is an infra error, not a pass
        return _error_result(case_id, f"audit_error:{type(exc).__name__}")
    observed_status = audit["status"]
    audit_status = observed_status if observed_status in {"ACCEPTED", "DOWNGRADED", "NOT_ASSESSED"} else None
    expected_status = case.get("expected_status")
    expected_reasons = list(case.get("expected_reasons") or [])
    matches = (
        observed_status == expected_status
        and sorted(audit["reasons"]) == sorted(expected_reasons)
    )
    notes = _observation_notes(case, audit)
    # Provenance: distinguish the model's own rating (when safely recoverable),
    # the application-validated rating and its review reasons, and the
    # evidence-audit status/reasons. Legacy ``final_rating`` /
    # ``decision_review_reasons`` keep their exact meaning (validated rating and
    # app reasons) so existing consumers are unaffected.
    applied_rating = produced.get("final_rating")
    applied_review_reasons = list(produced.get("decision_review_reasons") or [])
    model_rating = _recover_model_rating(produced)
    return {
        "id": case_id,
        "audit_status": audit_status,
        "observed_status": observed_status,
        "observed_reasons": list(audit["reasons"]),
        "claims_total": audit["claims_total"],
        "claims_attributed": audit["claims_attributed"],
        "unsupported_claim_ids": list(audit["unsupported_claim_ids"]),
        # Safe per-claim projection: no raw claim text, prompt, or credential.
        "claims": _safe_claims(audit),
        "observation_notes": notes,
        # The application-validated rating (identical to legacy ``final_rating``).
        "final_rating": applied_rating,
        "confidence": produced.get("pm_confidence"),
        # The application's review reasons (identical to legacy field).
        "decision_review_reasons": applied_review_reasons,
        # Provenance (S2): model's own rating (or None = unknown), the validated
        # rating, its reasons, and where a REVIEW originated.
        "model_rating": model_rating,
        "applied_rating": applied_rating,
        "applied_review_reasons": applied_review_reasons,
        "review_origin": _review_origin(
            model_rating, applied_rating, applied_review_reasons
        ),
        "matches_expectation": matches,
        "evaluator_exception": False,
        "error": None,
    }


def _safe_claims(audit: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Per-claim report from the audit, keeping only safe fields.

    ``source_id`` is the resolved source, or the fixed marker ``UNKNOWN`` when the
    audit could not resolve it; ``observation_date`` is the audit's normalised
    ISO date (or ``None``); ``attributed`` and ``reasons`` come straight from the
    audit. The claim's ``text`` is deliberately omitted so no raw model output
    enters the report.
    """
    safe: list[dict[str, Any]] = []
    for detail in audit.get("claims", []):
        attributed = bool(detail.get("attributed"))
        source_id = detail.get("source_id")
        safe.append({
            "kind": detail.get("kind"),
            "source": source_id if attributed and isinstance(source_id, str) else "UNKNOWN",
            "observation_date": detail.get("observation_date"),
            "attributed": attributed,
            "reasons": list(detail.get("reasons", [])),
        })
    return safe


def _observation_notes(case: Mapping[str, Any], audit: Mapping[str, Any]) -> list[str]:
    """Non-verdict observation notes (readable, not raw text or expectations).

    A market claim's supplied ``observation_date`` is checked against the case's
    ``source_supported_dates`` (the dates the source reports actually state). If
    the model supplies a date the source does not support — or any date when the
    source stated none (an empty supported set) — the run is flagged
    ``date basis unverified``, which the gate turns into UNFOUNDED_MARKET_DATE.
    A correctly supported date, or a missing date, is not flagged.
    """
    notes: list[str] = []
    supported = case.get("source_supported_dates")
    if supported is None:
        return notes
    supported = set(supported)
    for detail in audit.get("claims", []):
        if detail.get("source_id") != "market_report":
            continue
        date = detail.get("observation_date")
        if date and date not in supported:
            notes.append("date basis unverified")
            break
    return notes


def run_replay(
    cases: Iterable[Mapping[str, Any]],
    *,
    llm_factory: LlmFactory,
) -> dict[str, Any]:
    """Replay every case and aggregate into a Phase-1-shaped report.

    Overall status is ``OBSERVE`` (thresholds TBD): it reports observations and
    never claims a semantic PASS. An evaluator/replay exception makes the run
    ``INFRASTRUCTURE_ERROR`` (exit 2). An empty case set is likewise an
    infrastructure error.
    """
    cases = list(cases)
    if not cases:
        return _report("INFRASTRUCTURE_ERROR", "empty_case_set", [])
    results = [run_case(case, llm_factory) for case in cases]
    if any(r["evaluator_exception"] for r in results):
        return _report("INFRASTRUCTURE_ERROR", "replay_exception", results)
    return _report(REPLAY_STATUS, None, results)


def run_baseline(
    cases: Iterable[Mapping[str, Any]],
    *,
    llm_factory: LlmFactory,
    repetitions: int,
    model_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Repeat every case ``repetitions`` times and aggregate observations.

    Phase 3A baseline: each case is replayed N times so parse/retry variance is
    visible. Every per-run result is kept (including infrastructure errors); a
    run that hits an evaluator/replay error is recorded with its redacted error,
    never dropped. Overall status is ``OBSERVE`` (thresholds TBD) unless a
    harness-level problem makes it ``INFRASTRUCTURE_ERROR``.

    ``model_config`` is recorded verbatim as the effective configuration (the
    CLI currently has no temperature control, so it is whatever the caller
    passes; the config is reported, not assumed).
    """
    cases = list(cases)
    if repetitions < 1:
        return _baseline_report("INFRASTRUCTURE_ERROR", "invalid_repetitions", [], model_config)
    if not cases:
        return _baseline_report("INFRASTRUCTURE_ERROR", "empty_case_set", [], model_config)

    case_reports: list[dict[str, Any]] = []
    for case in cases:
        case_id = case.get("id", "<unknown>")
        runs = [run_case(case, llm_factory) for _ in range(repetitions)]
        runs = [{"repetition": index + 1, **run} for index, run in enumerate(runs)]
        report_case = {"id": case_id, "runs": runs, "aggregate": _aggregate(runs)}
        # Carry the case's acceptance intent so the gate can require a full-evidence
        # case to actually pass before the whole group may be PASS. The raw value
        # is preserved (not coerced to bool): a malformed literal such as
        # ``"false"`` or ``1`` must reach the gate as an incompleteness error, not
        # be silently turned into ``True`` here.
        if "expects_pass" in case:
            report_case["expects_pass"] = case["expects_pass"]
        if case.get("acceptance"):
            report_case["acceptance"] = case["acceptance"]
        case_reports.append(report_case)

    any_error = any(run["evaluator_exception"]
                    for cr in case_reports for run in cr["runs"])
    status = "INFRASTRUCTURE_ERROR" if any_error else REPLAY_STATUS
    reason = "replay_exception" if any_error else None
    return _baseline_report(status, reason, case_reports, model_config)


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-case aggregation of repeated runs (observational, no threshold)."""
    statuses: dict[str, int] = {}
    for run in runs:
        key = run["audit_status"] or "ERROR"
        statuses[key] = statuses.get(key, 0) + 1
    attributed = sum(r["claims_attributed"] or 0 for r in runs)
    total = sum(r["claims_total"] or 0 for r in runs)
    return {
        "runs": len(runs),
        "status_counts": statuses,
        "claims_attributed": attributed,
        "claims_total": total,
        "errors": sum(1 for r in runs if r["evaluator_exception"]),
        "runs_with_date_basis_unverified": sum(
            1 for r in runs if "date basis unverified" in (r.get("observation_notes") or [])
        ),
    }


def _baseline_report(
    status: str,
    reason: str | None,
    cases: list[dict[str, Any]],
    model_config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "mode": MODE_SEMANTIC_REPLAY,
        "status": status,
        "exit_code": 0 if status != "INFRASTRUCTURE_ERROR" else 2,
        "reason": reason,
        "thresholds": "TBD",
        "model_config": dict(model_config or {}),
        "cases": cases,
    }


def _report(status: str, reason: str | None, results: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for result in results:
        key = result["audit_status"] or "ERROR"
        counts[key] = counts.get(key, 0) + 1
    return {
        "mode": MODE_SEMANTIC_REPLAY,
        "status": status,
        "exit_code": 0 if status != "INFRASTRUCTURE_ERROR" else 2,
        "reason": reason,
        "thresholds": "TBD",
        "results": results,
        "counts": counts,
        "mismatches": [r["id"] for r in results if not r["matches_expectation"]],
        "errors": [r["id"] for r in results if r["evaluator_exception"]],
    }


__all__ = [
    "MODE_SEMANTIC_REPLAY",
    "REPLAY_STATUS",
    "REVIEW_ORIGIN_APP",
    "REVIEW_ORIGIN_MODEL",
    "REVIEW_ORIGIN_UNKNOWN",
    "build_pm_state",
    "default_llm_factory",
    "provider_llm_factory",
    "run_baseline",
    "run_case",
    "run_replay",
]
