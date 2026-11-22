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
from tradingagents.reporting import audit_material_claims

# Mode label for replay results; distinct from the offline pre-check.
MODE_SEMANTIC_REPLAY = "semantic_replay"
REPLAY_STATUS = "OBSERVE"

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
        "matches_expectation": False,
        "evaluator_exception": True,
        "error": error,
    }


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
    return {
        "id": case_id,
        "audit_status": audit_status,
        "observed_status": observed_status,
        "observed_reasons": list(audit["reasons"]),
        "claims_total": audit["claims_total"],
        "claims_attributed": audit["claims_attributed"],
        "unsupported_claim_ids": list(audit["unsupported_claim_ids"]),
        "final_rating": produced.get("final_rating"),
        "confidence": produced.get("pm_confidence"),
        "decision_review_reasons": list(produced.get("decision_review_reasons") or []),
        "matches_expectation": matches,
        "evaluator_exception": False,
        "error": None,
    }


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
    "build_pm_state",
    "default_llm_factory",
    "run_case",
    "run_replay",
]
