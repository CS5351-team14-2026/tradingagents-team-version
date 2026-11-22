"""Gate 4 Phase 2A — Portfolio Manager replay adapter (offline).

Exercises ``tools.sem_eval.replay`` with a model **double**; no network, no API
key. It verifies:

1. The double receives the *actually rendered* PM prompt (the production node's
   f-string output), not a snapshot or a handcrafted string.
2. The audit scores the claims *this* call produced, not the fixture's
   pre-written ``material_claims`` (which the adapter strips).
3. A successful replay reports observations with ``status="OBSERVE"`` (never a
   semantic ``PASS``), and a controlled failure does so too, without claiming
   success.

Thresholds are TBD by design.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.sem_eval.replay import (
    MODE_SEMANTIC_REPLAY,
    build_pm_state,
    run_replay,
)
from tradingagents.agents.schemas import (
    MaterialClaim,
    PortfolioDecision,
    PortfolioRating,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "gate4" / "pm_cases.json"


class _StructuredDouble:
    """A structured-output double that records the prompt it was handed."""

    def __init__(self, decision: PortfolioDecision, sink: dict):
        self._decision = decision
        self._sink = sink

    def invoke(self, prompt):
        self._sink["prompt"] = prompt
        return self._decision


class _LlmDouble:
    """An LLM double whose ``with_structured_output`` returns the recorder."""

    def __init__(self, decision: PortfolioDecision, sink: dict):
        self._decision = decision
        self._sink = sink

    def with_structured_output(self, schema):  # noqa: ANN001 - match production signature
        self._sink["schema"] = schema
        return _StructuredDouble(self._decision, self._sink)


def _good_decision() -> PortfolioDecision:
    """A decision whose claims cite real artifacts, so the audit ACCEPTs it."""
    return PortfolioDecision(
        rating=PortfolioRating.HOLD,
        confidence="medium",
        executive_summary="Hold and reassess.",
        investment_thesis="Market data and debate support holding the position.",
        supporting_factors=[
            MaterialClaim(
                text="Close was 181.2 on 2026-11-14.",
                source_id="market_report",
                observation_date="2026-11-14",
            )
        ],
        opposing_factors=[
            MaterialClaim(
                text="Trader flagged valuation risk.",
                source_id="trader_investment_plan",
            )
        ],
    )


def _bad_decision() -> PortfolioDecision:
    """A decision whose only claim cites an unknown source (audit DOWNGRADED)."""
    return PortfolioDecision(
        rating=PortfolioRating.HOLD,
        confidence="low",
        executive_summary="Wait.",
        investment_thesis="Only a non-report source was cited.",
        supporting_factors=[
            MaterialClaim(text="A podcast said so.", source_id="podcast_transcript")
        ],
        opposing_factors=[],
    )


def _cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _factory(decision: PortfolioDecision, sink: dict):
    def _make():
        return _LlmDouble(decision, sink)

    return _make


# --- 1. build_pm_state strips pre-written outputs -------------------------

@pytest.mark.unit
def test_build_pm_state_strips_pretended_outputs():
    case = _cases()[0]
    state = build_pm_state(case["state"])
    for key in ("material_claims", "final_rating", "final_trade_decision",
                "decision_review_reasons", "pm_confidence"):
        assert key not in state
    # Analyst inputs survive so the prompt has evidence to render.
    assert state["market_report"] == case["state"]["market_report"]
    assert state["investment_plan"] == case["state"]["investment_plan"]
    # Risk-debate keys the node reads unconditionally are present.
    assert state["risk_debate_state"]["count"] == 0
    # The original case is not mutated.
    assert "material_claims" in case["state"]


# --- 2. The double receives the actual rendered prompt --------------------

@pytest.mark.unit
def test_double_receives_the_actual_rendered_prompt():
    sink: dict = {}
    case = _cases()[0]
    run_replay([case], llm_factory=_factory(_good_decision(), sink))

    prompt = sink["prompt"]
    text = prompt if isinstance(prompt, str) else "\n".join(
        m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
        for m in prompt
    )
    # The production PM prompt's own sections must be present.
    assert "As the Portfolio Manager" in text
    assert "**Primary analyst evidence:**" in text
    assert "**Rating Scale**" in text
    # The fixture's analyst report is interpolated into the prompt.
    assert case["state"]["market_report"] in text
    # The structured schema bound is the real PortfolioDecision.
    assert sink["schema"] is PortfolioDecision


@pytest.mark.unit
def test_audit_scores_this_calls_claims_not_the_fixture():
    # The fixture for valid_dated_claim expects ACCEPTED with its own claims.
    # Swap the *decision* to an unknown-source claim: the replay must score the
    # new claim (DOWNGRADED / UNKNOWN_SOURCE), proving the fixture's pre-written
    # claims were replaced by this call's output.
    sink: dict = {}
    case = next(c for c in _cases() if c["id"] == "valid_dated_claim")
    report = run_replay([case], llm_factory=_factory(_bad_decision(), sink))
    result = report["results"][0]
    assert result["observed_status"] == "DOWNGRADED"
    assert result["observed_reasons"] == ["UNKNOWN_SOURCE"]
    assert result["matches_expectation"] is False


# --- 3. Success sample ----------------------------------------------------

@pytest.mark.unit
def test_successful_replay_observes_never_passes():
    sink: dict = {}
    case = next(c for c in _cases() if c["id"] == "valid_dated_claim")
    report = run_replay([case], llm_factory=_factory(_good_decision(), sink))

    assert report["mode"] == MODE_SEMANTIC_REPLAY
    assert report["status"] == "OBSERVE"
    assert report["status"] != "PASS"
    assert report["thresholds"] == "TBD"
    assert report["exit_code"] == 0

    result = report["results"][0]
    assert result["observed_status"] == "ACCEPTED"
    assert result["observed_reasons"] == []
    assert result["matches_expectation"] is True
    assert result["final_rating"] == "Hold"
    assert result["confidence"] == "medium"
    # Phase 1 result fields are carried through.
    for key in ("audit_status", "claims_total", "claims_attributed",
                "unsupported_claim_ids", "matches_expectation"):
        assert key in result


# --- 4. Controlled failure sample -----------------------------------------

@pytest.mark.unit
def test_controlled_mismatch_still_observes_never_passes():
    sink: dict = {}
    case = next(c for c in _cases() if c["id"] == "valid_dated_claim")
    report = run_replay([case], llm_factory=_factory(_bad_decision(), sink))
    # A mismatch is reported as an observation, not a PASS or a hard failure.
    assert report["status"] == "OBSERVE"
    assert report["status"] != "PASS"
    assert report["mismatches"] == ["valid_dated_claim"]
    assert report["exit_code"] == 0


@pytest.mark.unit
def test_replay_exception_is_infrastructure_error_redacted():
    def boom():
        raise RuntimeError("secret=xyz789 must not leak")

    report = run_replay([_cases()[0]], llm_factory=boom)
    assert report["status"] == "INFRASTRUCTURE_ERROR"
    assert report["exit_code"] == 2
    assert report["errors"] == ["valid_dated_claim"]
    encoded = json.dumps(report)
    assert "xyz789" not in encoded
    assert "replay_error:RuntimeError" in encoded


@pytest.mark.unit
def test_empty_replay_is_infrastructure_error():
    report = run_replay([], llm_factory=lambda: None)
    assert report["status"] == "INFRASTRUCTURE_ERROR"
    assert report["reason"] == "empty_case_set"


@pytest.mark.unit
def test_invalid_case_input_is_infrastructure_error_redacted():
    # A case missing ``state`` must not crash: it becomes a redacted infra error.
    bad_case = {"id": "no_state", "expected_status": "ACCEPTED", "expected_reasons": []}
    report = run_replay([bad_case], llm_factory=lambda: None)
    assert report["status"] == "INFRASTRUCTURE_ERROR"
    assert report["exit_code"] == 2
    assert report["errors"] == ["no_state"]
    result = report["results"][0]
    assert result["evaluator_exception"] is True
    assert result["error"] == "case_schema_error:missing_state"
    assert result["observed_status"] is None


@pytest.mark.unit
def test_null_expected_reasons_case_is_infrastructure_error():
    case = next(c for c in _cases() if c["id"] == "valid_dated_claim")
    bad = json.loads(json.dumps(case))
    bad["expected_reasons"] = None
    report = run_replay([bad], llm_factory=lambda: None)
    assert report["status"] == "INFRASTRUCTURE_ERROR"
    assert report["exit_code"] == 2
    assert report["results"][0]["error"] == "case_schema_error:expected_reasons"


@pytest.mark.unit
def test_audit_exception_is_infrastructure_error_redacted(monkeypatch):
    import tools.sem_eval.replay as replay

    def boom(_state):
        raise RuntimeError("audit secret=abc123 must not leak")

    monkeypatch.setattr(replay, "audit_material_claims", boom)
    case = next(c for c in _cases() if c["id"] == "valid_dated_claim")
    report = run_replay([case], llm_factory=_factory(_good_decision(), {}))
    assert report["status"] == "INFRASTRUCTURE_ERROR"
    assert report["exit_code"] == 2
    result = report["results"][0]
    assert result["evaluator_exception"] is True
    assert result["error"] == "audit_error:RuntimeError"
    encoded = json.dumps(report)
    assert "abc123" not in encoded
    assert "audit secret" not in encoded


# --- 5. Phase 1 offline pre-check still rejects semantic_replay -----------

@pytest.mark.unit
def test_offline_precheck_still_rejects_semantic_replay():
    from tools.sem_eval.evaluator import MODE_OFFLINE_PRECHECK, UnsupportedModeError, evaluate_cases

    assert MODE_OFFLINE_PRECHECK == "offline_precheck"
    with pytest.raises(UnsupportedModeError):
        evaluate_cases(_cases(), mode="semantic_replay")
