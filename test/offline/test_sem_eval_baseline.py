"""Gate 4 Phase 3A — formal-baseline cases + repeated replay aggregation (offline).

Uses a model **double**; no network, no API key. Verifies:

1. The three baseline fixture inputs are genuinely different after pre-written
   claims are stripped (and none pre-write claims).
2. Repeated replay (N per case) keeps every per-run result and aggregates
   audit status, claims attributed/total, and records infrastructure errors.
3. Overall status stays OBSERVE with thresholds TBD; a harness-level failure
   becomes INFRASTRUCTURE_ERROR (exit 2).
4. The effective model configuration is recorded verbatim (temperature is not
   set by the CLI, so the config is reported, not assumed).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.sem_eval.replay import build_pm_state, run_baseline
from tradingagents.agents.schemas import MaterialClaim, PortfolioDecision, PortfolioRating

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "gate4" / "baseline_cases.json"


class _StructuredDouble:
    def __init__(self, decision, sink):
        self._decision = decision
        self._sink = sink

    def invoke(self, prompt):
        self._sink.setdefault("prompts", []).append(prompt)
        return self._decision


class _LlmDouble:
    def __init__(self, decision, sink):
        self._decision = decision
        self._sink = sink

    def with_structured_output(self, schema):  # noqa: ANN001 - mirror production
        return _StructuredDouble(self._decision, self._sink)


def _good_decision() -> PortfolioDecision:
    return PortfolioDecision(
        rating=PortfolioRating.HOLD,
        confidence="medium",
        executive_summary="Hold.",
        investment_thesis="Dated market data and the debate support holding.",
        supporting_factors=[
            MaterialClaim(
                text="Close was 181.20 on 2026-11-13.",
                source_id="market_report",
                observation_date="2026-11-13",
            )
        ],
        opposing_factors=[
            MaterialClaim(text="Valuation is stretched.", source_id="investment_plan")
        ],
    )


def _factory(decision, sink):
    return lambda: _LlmDouble(decision, sink)


def _cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- 1. Baseline inputs are distinct after stripping ---------------------

@pytest.mark.unit
def test_three_baseline_inputs_are_distinct_and_no_prewritten_claims():
    cases = _cases()
    assert [c["id"] for c in cases] == [
        "baseline_full_evidence_dated",
        "baseline_market_report_undated",
        "baseline_partial_reports",
    ]
    stripped = [build_pm_state(c["state"]) for c in cases]

    def sig(state):
        return (
            state["market_report"],
            state["sentiment_report"],
            state["news_report"],
            state["fundamentals_report"],
        )

    assert len({sig(s) for s in stripped}) == 3
    assert all("material_claims" not in s for s in stripped)


# --- 2. Repeated replay keeps every run and aggregates -------------------

@pytest.mark.unit
def test_repeated_replay_keeps_runs_and_aggregates():
    sink: dict = {}
    report = run_baseline(
        _cases(), llm_factory=_factory(_good_decision(), sink), repetitions=3
    )
    assert report["status"] == "OBSERVE"
    assert report["status"] != "PASS"
    assert report["thresholds"] == "TBD"
    assert report["exit_code"] == 0
    assert len(report["cases"]) == 3
    for case in report["cases"]:
        assert [r["repetition"] for r in case["runs"]] == [1, 2, 3]
        agg = case["aggregate"]
        assert agg["runs"] == 3
        assert agg["status_counts"] == {"ACCEPTED": 3}
        assert agg["claims_attributed"] == agg["claims_total"]
        assert agg["errors"] == 0
    # Each run actually invoked the double (rendered prompt captured).
    assert len(sink["prompts"]) == 9


@pytest.mark.unit
def test_baseline_records_effective_model_config_verbatim():
    report = run_baseline(
        _cases(),
        llm_factory=_factory(_good_decision(), {}),
        repetitions=1,
        model_config={"provider": "deepseek", "model": "deepseek-flash", "temperature": "unset"},
    )
    assert report["model_config"] == {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "temperature": "unset",
    }


# --- 3. Infrastructure errors are retained, not dropped ------------------

@pytest.mark.unit
def test_repeated_replay_retains_infrastructure_errors():
    def boom():
        raise RuntimeError("secret=qqq111 must not leak")

    report = run_baseline(_cases()[:1], llm_factory=boom, repetitions=2)
    assert report["status"] == "INFRASTRUCTURE_ERROR"
    assert report["exit_code"] == 2
    case = report["cases"][0]
    assert len(case["runs"]) == 2  # failures kept, not dropped
    assert case["aggregate"]["errors"] == 2
    encoded = json.dumps(report)
    assert "qqq111" not in encoded
    assert "replay_error:RuntimeError" in encoded


@pytest.mark.unit
def test_invalid_repetitions_is_infrastructure_error():
    report = run_baseline(_cases(), llm_factory=_factory(_good_decision(), {}), repetitions=0)
    assert report["status"] == "INFRASTRUCTURE_ERROR"
    assert report["reason"] == "invalid_repetitions"


@pytest.mark.unit
def test_empty_cases_is_infrastructure_error():
    report = run_baseline([], llm_factory=_factory(_good_decision(), {}), repetitions=3)
    assert report["status"] == "INFRASTRUCTURE_ERROR"
    assert report["reason"] == "empty_case_set"


# --- 4. Per-claim safe report + observation notes ------------------------

def _decision_with_unknown_and_dated():
    """One attributed dated market claim + one unknown-source claim."""
    return PortfolioDecision(
        rating=PortfolioRating.HOLD,
        confidence="medium",
        executive_summary="Hold.",
        investment_thesis="Mixed evidence.",
        supporting_factors=[
            MaterialClaim(
                text="Close was 181.20 on 2026-11-13.",
                source_id="market_report",
                observation_date="2026-11-13",
            )
        ],
        opposing_factors=[
            MaterialClaim(text="A podcast said so.", source_id="podcast_transcript")
        ],
    )


@pytest.mark.unit
def test_per_run_report_has_safe_claim_fields_no_raw_text():
    report = run_baseline(
        _cases()[:1],
        llm_factory=_factory(_decision_with_unknown_and_dated(), {}),
        repetitions=1,
    )
    run = report["cases"][0]["runs"][0]
    claims = run["claims"]
    assert len(claims) == 2
    for claim in claims:
        assert set(claim) == {
            "kind", "source", "observation_date", "attributed", "reasons"
        }
        assert "text" not in claim
    # The dated market claim resolves to market_report and keeps its ISO date.
    supported = next(c for c in claims if c["kind"] == "supporting")
    assert supported["source"] == "market_report"
    assert supported["observation_date"] == "2026-11-13"
    assert supported["attributed"] is True
    # The unknown source uses the fixed marker, not the raw id.
    unsupported = next(c for c in claims if c["kind"] == "opposing")
    assert unsupported["source"] == "UNKNOWN"
    assert unsupported["attributed"] is False
    assert "UNKNOWN_SOURCE" in unsupported["reasons"]
    # No raw claim text anywhere in the report.
    encoded = json.dumps(report)
    assert "Close was" not in encoded
    assert "podcast said so" not in encoded


@pytest.mark.unit
def test_undated_market_case_flags_date_basis_unverified_when_model_fills_date():
    # baseline_market_report_undated has no source dates; the model supplies one.
    undated = next(c for c in _cases() if c["id"] == "baseline_market_report_undated")
    report = run_baseline(
        [undated],
        llm_factory=_factory(_decision_with_unknown_and_dated(), {}),
        repetitions=3,
    )
    case = report["cases"][0]
    for run in case["runs"]:
        assert "date basis unverified" in run["observation_notes"]
    assert case["aggregate"]["runs_with_date_basis_unverified"] == 3


@pytest.mark.unit
def test_dated_case_has_no_date_basis_note():
    dated = next(c for c in _cases() if c["id"] == "baseline_full_evidence_dated")
    report = run_baseline(
        [dated],
        llm_factory=_factory(_decision_with_unknown_and_dated(), {}),
        repetitions=1,
    )
    run = report["cases"][0]["runs"][0]
    assert run["observation_notes"] == []


@pytest.mark.unit
def test_baseline_without_expected_answer_not_counted_as_model_failure():
    # Baseline cases carry no expected_status, so matches_expectation is False by
    # construction; that must not be reported as a failure. Overall status stays
    # OBSERVE and no error is recorded.
    report = run_baseline(
        _cases(), llm_factory=_factory(_good_decision(), {}), repetitions=1
    )
    assert report["status"] == "OBSERVE"
    for case in report["cases"]:
        for run in case["runs"]:
            assert run["matches_expectation"] is False  # no preset answer
            assert run["evaluator_exception"] is False   # not a model failure
        assert case["aggregate"]["errors"] == 0
