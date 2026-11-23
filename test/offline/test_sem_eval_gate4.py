"""Gate 4 Phase 1 — Portfolio Manager semantic-eval scaffolding (offline).

Covers the REQ-TA-GOV-001 / DEBT-003 slice approved as test plan #81, Phase 1:

1. Fixed PM cases live in ``test/fixtures/gate4/pm_cases.json``.
2. The existing claim audit (:func:`tradingagents.reporting.audit_material_claims`)
   is reused to verify ACCEPTED, UNTRACEABLE_CLAIM, UNKNOWN_SOURCE and
   UNDATED_MARKET_DATA, in both the JSON result and the readable summary.
   Per-case audit status is separate from the overall evaluation status.
3. Trigger rules fire on PM prompt / model config / output parsing changes and
   return NOT_APPLICABLE for pure-docs changes.
4. Overall status is PASS / FAIL / NOT_APPLICABLE / INFRASTRUCTURE_ERROR;
   missing credentials, timeouts, evaluator exceptions, an empty case set and an
   unexpected skip never report PASS. Error evidence is redacted.
5. The CLI writes result.json + summary.txt and maps status to exit 0/1/2.

No model is called and no network is used. Thresholds stay TBD; a PASS means
"offline pre-check matched", never "the semantic evaluation passed".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.sem_eval import cli as sem_cli
from tools.sem_eval.evaluator import (
    EXIT_CODES,
    SUPPORTED_MODES,
    CaseSchemaError,
    UnsupportedModeError,
    evaluate_case,
    evaluate_cases,
    exit_code_for,
    load_cases,
    render_summary,
)
from tools.sem_eval.triggers import is_semantic_eval_triggered

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "gate4" / "pm_cases.json"


def _cases():
    return load_cases(FIXTURE)


# --- 1. Fixed cases -------------------------------------------------------

@pytest.mark.unit
def test_fixture_has_the_four_required_cases():
    ids = {case["id"] for case in _cases()}
    assert ids == {
        "valid_dated_claim",
        "empty_claim",
        "unknown_source",
        "undated_market_claim",
    }


# --- 2. Reuse claim audit; verify verdicts --------------------------------

@pytest.mark.unit
@pytest.mark.parametrize(
    ("case_id", "expected_status", "expected_reasons"),
    [
        ("valid_dated_claim", "ACCEPTED", []),
        ("empty_claim", "DOWNGRADED", ["UNTRACEABLE_CLAIM"]),
        ("unknown_source", "DOWNGRADED", ["UNKNOWN_SOURCE"]),
        ("undated_market_claim", "DOWNGRADED", ["UNDATED_MARKET_DATA"]),
    ],
)
def test_each_case_matches_its_expected_audit(case_id, expected_status, expected_reasons):
    case = next(c for c in _cases() if c["id"] == case_id)
    result = evaluate_case(case)
    assert result["observed_status"] == expected_status
    assert result["observed_reasons"] == expected_reasons
    assert result["audit_status"] == expected_status
    assert result["evaluator_exception"] is False
    assert result["matches_expectation"] is True


@pytest.mark.unit
def test_all_matching_cases_returns_pass():
    report = evaluate_cases(_cases())
    assert report["mode"] == "offline_precheck"
    assert report["status"] == "PASS"
    assert report["exit_code"] == 0
    assert report["reason"] is None
    assert report["mismatches"] == []
    assert report["errors"] == []
    assert report["counts"] == {"ACCEPTED": 1, "DOWNGRADED": 3}
    # Per-case audit status is separate from the overall status.
    assert all("audit_status" in r for r in report["results"])


@pytest.mark.unit
def test_summary_names_each_case_and_keeps_audit_status_separate():
    summary = render_summary(evaluate_cases(_cases()))
    assert "overall status: PASS (exit 0)" in summary
    assert "valid_dated_claim: audit=ACCEPTED" in summary
    assert "empty_claim: audit=DOWNGRADED observed=DOWNGRADED (UNTRACEABLE_CLAIM)" in summary
    assert "unknown_source:" in summary and "UNKNOWN_SOURCE" in summary
    assert "undated_market_claim:" in summary and "UNDATED_MARKET_DATA" in summary
    assert "MISMATCH" not in summary


# --- 3. Trigger rules -----------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "src/tradingagents/agents/managers/portfolio_manager.py",
        "src/tradingagents/agents/schemas.py",
        "src/tradingagents/agents/rating.py",
        "src/tradingagents/agents/structured.py",
        "src/tradingagents/reporting.py",
        "src/tradingagents/llm_clients/model_catalog.py",
        "src/tradingagents/llm_clients/factory.py",
        "src/tradingagents/llm_clients/openai_client.py",
        "src/tradingagents/default_config.py",
        "prompts/prompt_v1.1.yaml",
    ],
)
def test_prompt_model_and_parsing_paths_trigger(path):
    verdict, matched = is_semantic_eval_triggered([path])
    assert verdict == "TRIGGERED"
    assert matched == [path]


@pytest.mark.unit
def test_pure_docs_change_is_not_applicable():
    verdict, matched = is_semantic_eval_triggered(
        ["docs/evaluation.md", "README.md", "docs/req/requirements.yaml"]
    )
    assert verdict == "NOT_APPLICABLE"
    assert matched == []


@pytest.mark.unit
def test_empty_change_set_is_not_applicable():
    assert is_semantic_eval_triggered([]) == ("NOT_APPLICABLE", [])


# --- 4. Overall status: normal, mismatch, empty, env error, redaction ------

@pytest.mark.unit
def test_expected_mismatch_returns_fail():
    case = next(c for c in _cases() if c["id"] == "valid_dated_claim")
    wrong = json.loads(json.dumps(case))
    wrong["expected_status"] = "DOWNGRADED"
    wrong["expected_reasons"] = ["UNKNOWN_SOURCE"]
    report = evaluate_cases([wrong])
    assert report["status"] == "FAIL"
    assert report["exit_code"] == 1
    assert report["reason"] == "expectation_mismatch"
    assert report["mismatches"] == ["valid_dated_claim"]


@pytest.mark.unit
def test_empty_case_set_is_infrastructure_error():
    report = evaluate_cases([])
    assert report["status"] == "INFRASTRUCTURE_ERROR"
    assert report["exit_code"] == 2
    assert report["reason"] == "empty_case_set"


@pytest.mark.unit
def test_missing_environment_is_infrastructure_error_never_pass():
    report = evaluate_cases(_cases(), env_ok=False, env_error="missing_api_credential")
    assert report["status"] == "INFRASTRUCTURE_ERROR"
    assert report["exit_code"] == 2
    assert report["reason"] == "missing_api_credential"
    assert report["status"] != "PASS"


@pytest.mark.unit
def test_timeout_is_infrastructure_error_never_pass():
    report = evaluate_cases(_cases(), env_ok=False, env_error="evaluator_timeout")
    assert report["status"] == "INFRASTRUCTURE_ERROR"
    assert "PASS" not in render_summary(report).splitlines()[0]


@pytest.mark.unit
def test_evaluator_exception_is_infrastructure_error_and_redacted(monkeypatch):
    import tools.sem_eval.evaluator as evaluator

    def boom(_state):
        raise RuntimeError("secret-token=abc123 leaked")

    monkeypatch.setattr(evaluator, "audit_material_claims", boom)
    report = evaluate_cases(_cases())
    assert report["status"] == "INFRASTRUCTURE_ERROR"
    assert report["exit_code"] == 2
    assert report["reason"] == "evaluator_exception"
    assert report["errors"] == ["valid_dated_claim", "empty_claim", "unknown_source",
                                "undated_market_claim"]
    encoded = json.dumps(report)
    assert "abc123" not in encoded
    assert "secret-token" not in encoded
    assert "evaluator_error:RuntimeError" in encoded


@pytest.mark.unit
def test_unexpected_skip_is_not_counted_as_pass():
    # A case with no claims audits NOT_ASSESSED, never ACCEPTED/PASS.
    case = {
        "id": "no_claims",
        "expected_status": "NOT_ASSESSED",
        "expected_reasons": ["NO_CLAIM_METADATA"],
        "state": {"trade_date": "2026-11-14", "material_claims": []},
    }
    report = evaluate_cases([case])
    assert report["status"] == "PASS"
    result = report["results"][0]
    assert result["audit_status"] == "NOT_ASSESSED"
    assert result["audit_status"] != "ACCEPTED"


# --- 5. Exit-code mapping + CLI artefacts ---------------------------------

@pytest.mark.unit
def test_exit_code_mapping():
    assert exit_code_for("PASS") == 0
    assert exit_code_for("NOT_APPLICABLE") == 0
    assert exit_code_for("FAIL") == 1
    assert exit_code_for("INFRASTRUCTURE_ERROR") == 2
    assert EXIT_CODES == {
        "PASS": 0,
        "NOT_APPLICABLE": 0,
        "FAIL": 1,
        "INFRASTRUCTURE_ERROR": 2,
    }


@pytest.mark.unit
def test_cli_writes_result_json_and_summary(tmp_path):
    out = tmp_path / "gate4"
    code = sem_cli.main(["--cases", str(FIXTURE), "--out", str(out)])
    assert code == 0
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert result["exit_code"] == 0
    assert (out / "summary.txt").read_text(encoding="utf-8").startswith(
        "Gate 4 PM semantic eval"
    )


@pytest.mark.unit
def test_cli_unreadable_case_file_is_infrastructure_error(tmp_path):
    out = tmp_path / "gate4"
    code = sem_cli.main(["--cases", str(tmp_path / "missing.json"), "--out", str(out)])
    assert code == 2
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["reason"].startswith("case_file_unreadable:")


# --- 6. Regression: malformed expectations + unsupported mode -------------

@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_reasons",
    [None, "UNTRACEABLE_CLAIM", ["OK", 7]],
)
def test_load_cases_rejects_malformed_expected_reasons(tmp_path, bad_reasons):
    case = {
        "id": "bad",
        "expected_status": "DOWNGRADED",
        "expected_reasons": bad_reasons,
        "state": {"trade_date": "2026-11-14", "material_claims": []},
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([case]), encoding="utf-8")
    with pytest.raises(CaseSchemaError):
        load_cases(path)


@pytest.mark.unit
def test_load_cases_rejects_non_string_expected_status(tmp_path):
    case = {
        "id": "bad",
        "expected_status": None,
        "expected_reasons": [],
        "state": {"trade_date": "2026-11-14", "material_claims": []},
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([case]), encoding="utf-8")
    with pytest.raises(CaseSchemaError):
        load_cases(path)


@pytest.mark.unit
def test_cli_null_expected_reasons_is_infra_error_with_artifacts(tmp_path):
    # Regression: ``expected_reasons: null`` used to crash and write no files.
    case = {
        "id": "null_reasons",
        "expected_status": "DOWNGRADED",
        "expected_reasons": None,
        "state": {"trade_date": "2026-11-14", "material_claims": []},
    }
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([case]), encoding="utf-8")
    out = tmp_path / "gate4"
    code = sem_cli.main(["--cases", str(cases), "--out", str(out)])
    assert code == 2
    assert (out / "result.json").exists()
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert result["reason"].startswith("case_schema_error:")
    summary = (out / "summary.txt").read_text(encoding="utf-8")
    assert "INFRASTRUCTURE_ERROR" in summary


@pytest.mark.unit
def test_unsupported_mode_is_rejected_not_pass():
    with pytest.raises(UnsupportedModeError):
        evaluate_cases(_cases(), mode="semantic_replay")
    assert set(SUPPORTED_MODES) == {"offline_precheck"}


@pytest.mark.unit
def test_cli_rejects_unsupported_mode_without_reporting_pass(tmp_path):
    out = tmp_path / "gate4"
    code = sem_cli.main(
        ["--cases", str(FIXTURE), "--out", str(out), "--mode", "semantic_replay"]
    )
    assert code == 2
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["status"] != "PASS"
    assert result["reason"].startswith("unsupported_mode:")
    assert result["mode"] == "semantic_replay"
