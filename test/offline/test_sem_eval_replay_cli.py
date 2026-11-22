"""Gate 4 Phase 2B step 1 — single-case replay entry (offline).

Exercises :mod:`tools.sem_eval.replay_cli` with a model **double**; no network,
no API key. Verifies:

1. A valid case runs and writes result.json + summary.txt, with the result coming
   from this call's output (status OBSERVE, thresholds TBD, exit 0).
2. An invalid/missing case or a model-call exception returns
   INFRASTRUCTURE_ERROR (exit 2) with a redacted error report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.sem_eval import replay_cli
from tradingagents.agents.schemas import MaterialClaim, PortfolioDecision, PortfolioRating

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "gate4" / "pm_cases.json"


class _StructuredDouble:
    def __init__(self, decision, sink):
        self._decision = decision
        self._sink = sink

    def invoke(self, prompt):
        self._sink["prompt"] = prompt
        return self._decision


class _LlmDouble:
    def __init__(self, decision, sink):
        self._decision = decision
        self._sink = sink

    def with_structured_output(self, schema):  # noqa: ANN001 - mirror production
        self._sink["schema"] = schema
        return _StructuredDouble(self._decision, self._sink)


def _good_decision() -> PortfolioDecision:
    # Hold needs no prices, so it is not forced to REVIEW.
    return PortfolioDecision(
        rating=PortfolioRating.HOLD,
        confidence="medium",
        executive_summary="Hold.",
        investment_thesis="Evidence supports holding.",
        supporting_factors=[
            MaterialClaim(
                text="Close was 181.2 on 2026-11-14.",
                source_id="market_report",
                observation_date="2026-11-14",
            )
        ],
        opposing_factors=[
            MaterialClaim(text="Valuation risk.", source_id="trader_investment_plan")
        ],
    )


def _factory(decision, sink):
    return lambda: _LlmDouble(decision, sink)


@pytest.mark.unit
def test_single_case_success_writes_artifacts_from_this_call(tmp_path):
    sink: dict = {}
    out = tmp_path / "case-01"
    code = replay_cli.main(
        [
            "--cases", str(FIXTURE),
            "--case-id", "valid_dated_claim",
            "--out", str(out),
        ],
        llm_factory=_factory(_good_decision(), sink),
    )
    assert code == 0
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["mode"] == "semantic_replay"
    assert result["status"] == "OBSERVE"
    assert result["status"] != "PASS"
    assert result["thresholds"] == "TBD"
    assert result["exit_code"] == 0
    assert len(result["results"]) == 1
    case_result = result["results"][0]
    assert case_result["id"] == "valid_dated_claim"
    # The result comes from THIS call's output, not the fixture's pre-written claims.
    assert case_result["observed_status"] == "ACCEPTED"
    assert case_result["final_rating"] == "Hold"
    assert case_result["confidence"] == "medium"
    # The double actually received the rendered prompt.
    assert "As the Portfolio Manager" in sink["prompt"]
    # summary.txt is written and readable.
    summary = (out / "summary.txt").read_text(encoding="utf-8")
    assert "overall status: OBSERVE" in summary
    assert "valid_dated_claim" in summary


@pytest.mark.unit
def test_single_case_audit_reflects_this_calls_claims(tmp_path):
    # The fixture valid_dated_claim expects ACCEPTED; a double returning an
    # unknown-source claim must be scored DOWNGRADED, proving this call is audited.
    bad = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        confidence="low",
        executive_summary="Wait.",
        investment_thesis="Only a non-report source.",
        supporting_factors=[MaterialClaim(text="A podcast said so.", source_id="podcast_transcript")],
        opposing_factors=[],
    )
    out = tmp_path / "case-02"
    code = replay_cli.main(
        ["--cases", str(FIXTURE), "--case-id", "valid_dated_claim", "--out", str(out)],
        llm_factory=_factory(bad, {}),
    )
    assert code == 0
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    case_result = result["results"][0]
    assert case_result["observed_status"] == "DOWNGRADED"
    assert case_result["observed_reasons"] == ["UNKNOWN_SOURCE"]


@pytest.mark.unit
def test_unknown_case_id_is_infra_error_with_artifacts(tmp_path):
    out = tmp_path / "case-03"
    code = replay_cli.main(
        ["--cases", str(FIXTURE), "--case-id", "does_not_exist", "--out", str(out)],
        llm_factory=_factory(_good_decision(), {}),
    )
    assert code == 2
    assert (out / "result.json").exists()
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert result["reason"] == "case_not_found"


@pytest.mark.unit
def test_model_call_exception_is_redacted_infra_error(tmp_path):
    def boom():
        raise RuntimeError("secret=zzz999 must not leak")

    out = tmp_path / "case-04"
    code = replay_cli.main(
        ["--cases", str(FIXTURE), "--case-id", "valid_dated_claim", "--out", str(out)],
        llm_factory=boom,
    )
    assert code == 2
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["errors"] == ["valid_dated_claim"]
    encoded = json.dumps(result)
    assert "zzz999" not in encoded
    assert "secret=" not in encoded
    assert "replay_error:RuntimeError" in encoded


@pytest.mark.unit
def test_missing_provider_or_model_is_infra_error(tmp_path):
    out = tmp_path / "case-05"
    # No injected factory and no --provider/--model: a real run is refused.
    code = replay_cli.main(
        ["--cases", str(FIXTURE), "--case-id", "valid_dated_claim", "--out", str(out)]
    )
    assert code == 2
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["reason"] == "missing_provider_or_model"


@pytest.mark.unit
def test_unreadable_case_file_is_infra_error(tmp_path):
    out = tmp_path / "case-06"
    code = replay_cli.main(
        ["--cases", str(tmp_path / "missing.json"), "--case-id", "x", "--out", str(out)],
        llm_factory=_factory(_good_decision(), {}),
    )
    assert code == 2
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["reason"].startswith("case_file_unreadable:")


@pytest.mark.unit
def test_invalid_case_schema_reports_fixed_reason_no_raw_text(tmp_path, monkeypatch):
    # A schema-invalid case (expected_reasons: null) with a distinctive value that
    # must NOT appear in the report. Provider/model are given so a model client
    # would be built if the error path did not short-circuit first; the spy proves
    # no client is created.
    import tradingagents.llm_clients.factory as factory_mod

    created = {"called": False}

    def _spy(*args, **kwargs):
        created["called"] = True
        raise AssertionError("model client must not be created")

    monkeypatch.setattr(factory_mod, "create_llm_client", _spy)

    bad_cases = tmp_path / "bad.json"
    bad_cases.write_text(
        json.dumps([
            {"id": "SECRET_ID_zzz", "expected_status": "DOWNGRADED",
             "expected_reasons": None, "state": {"trade_date": "2026-11-14"}}
        ]),
        encoding="utf-8",
    )
    out = tmp_path / "case-07"
    code = replay_cli.main(
        [
            "--cases", str(bad_cases), "--case-id", "SECRET_ID_zzz",
            "--provider", "deepseek", "--model", "deepseek-chat", "--out", str(out),
        ]
    )
    assert code == 2
    assert created["called"] is False
    assert (out / "result.json").exists() and (out / "summary.txt").exists()
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["reason"] == "case_schema_error"
    encoded = json.dumps(result)
    # The fixed reason code only: no raw exception text, no input value.
    assert "SECRET_ID_zzz" not in encoded
    assert "expected_reasons" not in encoded
    assert "NoneType" not in encoded


@pytest.mark.unit
def test_non_utf8_case_file_writes_artifacts_and_exits_2(tmp_path, monkeypatch):
    import tradingagents.llm_clients.factory as factory_mod

    created = {"called": False}

    def _spy(*args, **kwargs):
        created["called"] = True
        raise AssertionError("model client must not be created")

    monkeypatch.setattr(factory_mod, "create_llm_client", _spy)

    bad_cases = tmp_path / "bad_bytes.json"
    bad_cases.write_bytes(b"\xff\xfe\x00not utf-8 \xff")
    out = tmp_path / "case-08"
    code = replay_cli.main(
        [
            "--cases", str(bad_cases), "--case-id", "valid_dated_claim",
            "--provider", "deepseek", "--model", "deepseek-chat", "--out", str(out),
        ]
    )
    assert code == 2
    assert created["called"] is False
    assert (out / "result.json").exists() and (out / "summary.txt").exists()
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert result["reason"] == "case_file_not_utf8"
