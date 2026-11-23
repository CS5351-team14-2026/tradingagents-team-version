"""Gate 4 CI entry — offline validation (no GitHub, no model).

Verifies the CI adapter end to end using offline samples:

- pure-docs PR -> NOT_APPLICABLE, exit 0 (no evaluation);
- prompt/model change with a clean report -> PASS, exit 0;
- quality-degraded report (unfounded date / unknown source) -> FAIL, exit 1;
- infrastructure error -> INFRASTRUCTURE_ERROR, exit 2;
- triggered change with no report -> INFRASTRUCTURE_ERROR, exit 2.

The historical baseline.json is used here only as regression material; CI's real
evaluation targets a report produced from the current PR.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.sem_eval.ci_entry import evaluate_pr

BASELINE = (
    Path(__file__).resolve().parent.parent.parent
    / "docs" / "evidence" / "gate4" / "2026-11-22" / "baseline" / "baseline.json"
)

DOCS = ["docs/evaluation.md", "README.md"]
PROMPT = ["src/tradingagents/agents/managers/portfolio_manager.py"]


def _pass_run(repetition):
    return {
        "repetition": repetition,
        "id": "run",
        "audit_status": "ACCEPTED",
        "observed_status": "ACCEPTED",
        "observed_reasons": [],
        "claims_total": 6,
        "claims_attributed": 6,
        "unsupported_claim_ids": [],
        "claims": [
            {"kind": "supporting", "source": "market_report",
             "observation_date": "2026-11-13", "attributed": True,
             "reasons": []},
        ],
        "observation_notes": [],
        "final_rating": "Overweight",
        "confidence": "medium",
        "decision_review_reasons": [],
        "matches_expectation": False,
        "evaluator_exception": False,
        "error": None,
    }


def _thin_review_run(repetition):
    """A thin-evidence run: DOWNGRADED, no hard defect -> REVIEW."""
    return {
        "repetition": repetition,
        "id": "run",
        "audit_status": "DOWNGRADED",
        "observed_status": "DOWNGRADED",
        "observed_reasons": ["UNDATED_MARKET_DATA"],
        "claims_total": 1,
        "claims_attributed": 0,
        "unsupported_claim_ids": [],
        "claims": [
            {"kind": "supporting", "source": "UNKNOWN",
             "observation_date": None, "attributed": False,
             "reasons": ["UNDATED_MARKET_DATA"]},
        ],
        "observation_notes": [],
        "final_rating": "Hold",
        "confidence": "low",
        "decision_review_reasons": [],
        "matches_expectation": False,
        "evaluator_exception": False,
        "error": None,
    }


def _complete_report(full_evidence_runs=None):
    """A complete 3-case × 3-run report (the formal-CI evidence set).

    The full-evidence case declares ``expects_pass`` and defaults to three PASS
    runs; the two thin cases are non-blocking REVIEW runs. Used to exercise the
    PASS/FAIL mapping through the real CI entry without tripping completeness.
    """
    from tools.sem_eval.gate import REQUIRED_CASE_IDS

    full = "baseline_full_evidence_dated"
    full_runs = full_evidence_runs or [_pass_run(i) for i in range(1, 4)]
    cases = [{"id": full, "expects_pass": True, "runs": full_runs}]
    for case_id in REQUIRED_CASE_IDS:
        if case_id == full:
            continue
        cases.append({"id": case_id, "runs": [_thin_review_run(i) for i in range(1, 4)]})
    return {"status": "OBSERVE", "cases": cases}


def _clean_report():
    """A complete report from the current PR where every run is clean (PASS)."""
    return _complete_report()


def _degraded_report():
    """A complete report where the full-evidence case fails (unfounded date)."""
    failing = []
    for i in range(1, 4):
        run = _pass_run(i)
        run["observation_notes"] = ["date basis unverified"]
        failing.append(run)
    return _complete_report(failing)


def _infra_report():
    return {"status": "INFRASTRUCTURE_ERROR", "reason": "empty_case_set", "cases": []}


@pytest.mark.unit
def test_docs_only_pr_is_not_applicable_exit_0():
    result = evaluate_pr(DOCS)
    assert result["status"] == "NOT_APPLICABLE"
    assert result["exit_code"] == 0
    assert result["blocks_merge"] is False
    assert result["matched_paths"] == []


@pytest.mark.unit
def test_prompt_change_clean_report_passes_exit_0():
    result = evaluate_pr(PROMPT, report=_clean_report())
    assert result["status"] == "PASS"
    assert result["exit_code"] == 0
    assert result["matched_paths"] == PROMPT


@pytest.mark.unit
def test_prompt_change_degraded_report_fails_exit_1():
    result = evaluate_pr(PROMPT, report=_degraded_report())
    assert result["status"] == "FAIL"
    assert result["exit_code"] == 1


@pytest.mark.unit
def test_infrastructure_error_report_exit_2():
    result = evaluate_pr(PROMPT, report=_infra_report())
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2


@pytest.mark.unit
def test_triggered_change_without_report_is_infrastructure_error_exit_2():
    result = evaluate_pr(PROMPT, report=None)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert result["reason"] == "missing_evaluation_report"


@pytest.mark.unit
def test_model_config_change_triggers_gate():
    result = evaluate_pr(
        ["src/tradingagents/llm_clients/model_catalog.py"], report=_clean_report()
    )
    assert result["status"] == "PASS"
    assert result["exit_code"] == 0


@pytest.mark.unit
def test_archived_baseline_as_regression_material_fails_via_historical_path():
    # The frozen archived baseline (regression material) carries hard defects, so
    # the historical per-case decision over it is FAIL. This is the baseline's
    # original contract and is exercised through ``decide_baseline`` (default
    # single/historical support), since the frozen artefact predates the
    # formal-CI completeness rule.
    from tools.sem_eval.gate import decide_baseline

    report = json.loads(BASELINE.read_text(encoding="utf-8"))
    decision = decide_baseline(report)
    assert decision["overall_decision"] == "FAIL"


@pytest.mark.unit
def test_frozen_archived_baseline_is_incomplete_for_formal_ci():
    # The frozen archived baseline predates the ``expects_pass`` declaration, so
    # formal CI rejects it as incomplete (INFRASTRUCTURE_ERROR/exit 2) rather
    # than reporting a partial verdict — never a PASS.
    report = json.loads(BASELINE.read_text(encoding="utf-8"))
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert result["reason"] == "incomplete_report"
    assert "full_evidence_expects_pass" in result["completeness"]["problems"]


# --- CI helper scripts (trigger + decide mains) --------------------------

@pytest.mark.unit
def test_ci_trigger_main_writes_verdict(tmp_path):
    from tools.sem_eval import ci_trigger_main

    changed = tmp_path / "changed.txt"
    out = tmp_path / "trigger.out"
    changed.write_text("docs/evaluation.md\nREADME.md\n", encoding="utf-8")
    code = ci_trigger_main.main(["x", str(changed), str(out)])
    assert code == 0
    assert out.read_text(encoding="utf-8") == "NOT_APPLICABLE"

    changed.write_text("src/tradingagents/agents/managers/portfolio_manager.py\n", encoding="utf-8")
    ci_trigger_main.main(["x", str(changed), str(out)])
    assert out.read_text(encoding="utf-8") == "TRIGGERED"


@pytest.mark.unit
def test_ci_decide_main_docs_returns_not_applicable_exit_0(tmp_path, monkeypatch):
    from tools.sem_eval import ci_decide_main

    changed = tmp_path / "changed.txt"
    trigger = tmp_path / "trigger.out"
    changed.write_text("docs/x.md\n", encoding="utf-8")
    trigger.write_text("NOT_APPLICABLE", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert ci_decide_main.main(["x", str(changed), str(trigger)]) == 0


@pytest.mark.unit
def test_ci_decide_main_triggered_without_secret_is_infrastructure_error_exit_2(
    tmp_path, monkeypatch
):
    from tools.sem_eval import ci_decide_main

    changed = tmp_path / "changed.txt"
    trigger = tmp_path / "trigger.out"
    changed.write_text("src/tradingagents/agents/managers/portfolio_manager.py\n", encoding="utf-8")
    trigger.write_text("TRIGGERED", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    # Missing credential -> INFRASTRUCTURE_ERROR exit 2, never a fabricated PASS.
    assert ci_decide_main.main(["x", str(changed), str(trigger)]) == 2


@pytest.mark.unit
def test_workflow_yaml_parses():
    import yaml

    wf = (
        Path(__file__).resolve().parent.parent.parent
        / ".github" / "workflows" / "gate4-semantic-eval.yml"
    )
    data = yaml.safe_load(wf.read_text(encoding="utf-8"))
    assert "semantic-eval" in data["jobs"]
    # ``on:`` parses as the boolean True under YAML 1.1; accept either spelling.
    assert "on" in data or True in data


# --- REVIEW exit-code fix + real-report path (Phase 3C) ------------------

@pytest.mark.unit
def test_all_review_maps_to_pass_top_level_with_per_run_review_detail():
    # A complete report: full-evidence case PASS + thin cases REVIEW -> top-level
    # PASS (exit 0) with the per-run REVIEW detail preserved in the gate view.
    report = _complete_report()
    result = evaluate_pr(PROMPT, report=report)
    # Top-level is one of the four CI statuses; REVIEW is not a top-level status.
    assert result["status"] == "PASS"
    assert result["exit_code"] == 0
    assert result["blocks_merge"] is False
    # Per-run REVIEW detail preserved for the thin cases.
    decisions = {
        run["decision"]
        for case in result["gate"]["cases"]
        for run in case["runs"]
    }
    assert "REVIEW" in decisions


@pytest.mark.unit
def test_reportgen_records_metadata_and_writes_files(tmp_path):
    from tools.sem_eval.reportgen import build_report, write_report

    class _S:
        def __init__(self, d): self.d = d
        def invoke(self, p): return self.d

    class _L:
        def __init__(self, d): self.d = d
        def with_structured_output(self, schema):
            outer = self

            class _W:
                def invoke(self, prompt): return outer.d
            return _W()

    from tradingagents.agents.schemas import MaterialClaim, PortfolioDecision, PortfolioRating

    dec = PortfolioDecision(
        rating=PortfolioRating.HOLD, confidence="medium",
        executive_summary="Hold.", investment_thesis="ok",
        supporting_factors=[MaterialClaim(text="Close was 181.20 on 2026-11-13.",
                                          source_id="market_report",
                                          observation_date="2026-11-13")],
        opposing_factors=[MaterialClaim(text="valuation", source_id="investment_plan")],
    )
    cases = json.loads(
        (Path(__file__).resolve().parent.parent / "fixtures" / "gate4" / "baseline_cases.json")
        .read_text(encoding="utf-8"))
    report = build_report(
        cases, llm_factory=lambda: _L(dec), candidate_sha="deadbeef",
        model_config={"provider": "deepseek", "model": "deepseek-flash",
                      "temperature": "unset", "api_key": object()},
        repetitions=1,
    )
    assert report["candidate_sha"] == "deadbeef"
    assert report["case_version"]
    assert "api_key" not in report["model_config"]  # not allowlisted
    json_path, summary_path = write_report(report, tmp_path / "out")
    assert json_path.exists() and summary_path.exists()
    assert "deadbeef" in summary_path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_decide_docs_does_not_need_credential_or_report(monkeypatch):
    from tools.sem_eval.ci_decide_main import decide

    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    result, report = decide(triggered=False, paths=["docs/x.md"], candidate_sha="abc")
    assert result["status"] == "NOT_APPLICABLE"
    assert result["exit_code"] == 0
    assert report is None


@pytest.mark.unit
def test_decide_triggered_no_credential_is_infrastructure_error(monkeypatch):
    from tools.sem_eval.ci_decide_main import decide

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    result, report = decide(
        triggered=True, paths=PROMPT, candidate_sha="abc",
        config={"deep_think_provider": "deepseek", "deep_think_llm": "deepseek-flash",
                "temperature": 0},
    )
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert result["reason"] == "missing_credential"
    assert report is None


@pytest.mark.unit
def test_decide_triggered_unsupported_provider_is_infrastructure_error():
    from tools.sem_eval.ci_decide_main import decide

    result, report = decide(
        triggered=True, paths=PROMPT, candidate_sha="abc",
        config={"deep_think_provider": "not-a-provider", "deep_think_llm": "x",
                "temperature": 0},
    )
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert result["reason"] == "unsupported_provider"
    assert report is None


@pytest.mark.unit
def test_decide_triggered_with_double_produces_report_and_gate_result():
    from tools.sem_eval.ci_decide_main import decide

    class _S:
        def __init__(self, d): self.d = d
        def invoke(self, p): return self.d

    class _L:
        def __init__(self, d): self.d = d
        def with_structured_output(self, schema):
            outer = self

            class _W:
                def invoke(self, prompt): return outer.d
            return _W()

    from tradingagents.agents.schemas import MaterialClaim, PortfolioDecision, PortfolioRating

    dec = PortfolioDecision(
        rating=PortfolioRating.HOLD, confidence="medium",
        executive_summary="Hold.", investment_thesis="ok",
        supporting_factors=[MaterialClaim(text="Close was 181.20 on 2026-11-13.",
                                          source_id="market_report",
                                          observation_date="2026-11-13")],
        opposing_factors=[MaterialClaim(text="valuation", source_id="investment_plan")],
    )
    cases = json.loads(
        (Path(__file__).resolve().parent.parent / "fixtures" / "gate4" / "baseline_cases.json")
        .read_text(encoding="utf-8"))
    result, report = decide(
        triggered=True, paths=PROMPT, candidate_sha="cafe1234",
        llm_factory=lambda: _L(dec), cases=cases,
        config={"deep_think_provider": "deepseek", "deep_think_llm": "deepseek-flash",
                "temperature": 0},
    )
    assert report is not None
    assert report["candidate_sha"] == "cafe1234"
    assert result["status"] in {"PASS", "FAIL", "INFRASTRUCTURE_ERROR"}
    assert "gate" in result


@pytest.mark.unit
def test_effective_pm_model_config_reads_deep_tier():
    from tools.sem_eval.reportgen import effective_pm_model_config

    cfg = effective_pm_model_config({
        "llm_provider": "openai", "deep_think_provider": None,
        "deep_think_llm": "gpt-6-sol", "temperature": 0,
    })
    assert cfg["provider"] == "openai"
    assert cfg["model"] == "gpt-6-sol"
    assert cfg["temperature"] == 0


@pytest.mark.unit
def test_validate_pm_model_config_credential_check(monkeypatch):
    from tools.sem_eval.reportgen import validate_pm_model_config

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = {"deep_think_provider": "deepseek", "deep_think_llm": "deepseek-flash",
           "temperature": 0}
    ok, reason = validate_pm_model_config(cfg)
    assert ok is False and reason == "missing_credential"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "placeholder")
    ok, reason = validate_pm_model_config(cfg)
    assert ok is False and reason == "missing_credential"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-realmustnotbeshown")
    ok, reason = validate_pm_model_config(cfg)
    assert ok is True and reason is None


@pytest.mark.unit
def test_finalize_verdict_records_decision_rules_and_cases():
    from tools.sem_eval.reportgen import finalize_verdict

    report = {"candidate_sha": "abc", "replay": {"cases": []}}
    ci_result = {
        "status": "FAIL", "exit_code": 1, "blocks_merge": True,
        "gate": {"cases": [{"id": "c", "decision": "FAIL", "runs": [
            {"repetition": 1, "decision": "FAIL", "reasons": ["UNFOUNDED_MARKET_DATE"]}]}]},
    }
    finalized = finalize_verdict(report, ci_result)
    assert finalized["final_decision"] == "FAIL"
    assert finalized["failed_rules"] == ["UNFOUNDED_MARKET_DATE"]
    assert finalized["cases"][0]["id"] == "c"


# --- Candidate config: provider/model/temperature switching (Phase 3D) ----

@pytest.mark.unit
def test_effective_config_for_two_supported_providers():
    from tools.sem_eval.reportgen import effective_pm_model_config

    openai_cfg = effective_pm_model_config({
        "llm_provider": "openai", "deep_think_provider": None,
        "deep_think_llm": "gpt-4.1", "temperature": 0,
    })
    assert openai_cfg["provider"] == "openai"
    assert openai_cfg["model"] == "gpt-4.1"
    assert openai_cfg["temperature"] == 0.0

    anthropic_cfg = effective_pm_model_config({
        "llm_provider": "anthropic", "deep_think_provider": None,
        "deep_think_llm": "claude-x", "temperature": 0.2,
        "anthropic_effort": "high",
    })
    assert anthropic_cfg["provider"] == "anthropic"
    assert anthropic_cfg["model"] == "claude-x"
    assert anthropic_cfg["temperature"] == 0.2
    # Provider-specific reasoning setting is carried, matching the client path.
    assert anthropic_cfg.get("effort") == "high"


@pytest.mark.unit
def test_candidate_factory_passes_resolved_config_to_tier_client(monkeypatch):
    import tradingagents.llm_clients.factory as factory_mod
    from tools.sem_eval.reportgen import candidate_llm_factory

    captured = {}

    class _Client:
        def get_llm(self):
            return "CLIENT"

    def _fake_create_tier_client(config, tier):
        captured["config"] = dict(config)
        captured["tier"] = tier
        return _Client()

    monkeypatch.setattr(factory_mod, "create_tier_client", _fake_create_tier_client)
    llm = candidate_llm_factory({
        "deep_think_provider": "openai", "deep_think_llm": "gpt-4.1",
        "temperature": 0.3,
    })()
    assert llm == "CLIENT"
    assert captured["tier"] == "deep"
    assert captured["config"]["deep_think_provider"] == "openai"
    assert captured["config"]["deep_think_llm"] == "gpt-4.1"
    assert captured["config"]["temperature"] == 0.3


@pytest.mark.unit
def test_switching_model_changes_the_effective_config():
    from tools.sem_eval.reportgen import effective_pm_model_config

    a = effective_pm_model_config({
        "deep_think_provider": "openai", "deep_think_llm": "gpt-4.1", "temperature": 0})
    b = effective_pm_model_config({
        "deep_think_provider": "deepseek", "deep_think_llm": "deepseek-flash", "temperature": 0.5})
    assert (a["provider"], a["model"]) != (b["provider"], b["model"])
    assert a["temperature"] == 0.0 and b["temperature"] == 0.5


@pytest.mark.unit
def test_manual_override_records_config_overridden(tmp_path, monkeypatch):
    # A manual run that pins a provider/model must be flagged as overridden in the
    # report; the formal check passes no override and uses the candidate config.
    from tools.sem_eval.ci_decide_main import decide

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-realmustnotbeshown")

    class _S:
        def __init__(self, d): self.d = d
        def invoke(self, p): return self.d

    class _L:
        def __init__(self, d): self.d = d
        def with_structured_output(self, schema):
            outer = self

            class _W:
                def invoke(self, prompt): return outer.d
            return _W()

    from tradingagents.agents.schemas import MaterialClaim, PortfolioDecision, PortfolioRating

    dec = PortfolioDecision(
        rating=PortfolioRating.HOLD, confidence="medium",
        executive_summary="Hold.", investment_thesis="ok",
        supporting_factors=[MaterialClaim(text="Close was 181.20 on 2026-11-13.",
                                          source_id="market_report",
                                          observation_date="2026-11-13")],
        opposing_factors=[MaterialClaim(text="valuation", source_id="investment_plan")],
    )
    cases = json.loads(
        (Path(__file__).resolve().parent.parent / "fixtures" / "gate4" / "baseline_cases.json")
        .read_text(encoding="utf-8"))
    result, report = decide(
        triggered=True, paths=PROMPT, candidate_sha="cafe9999",
        llm_factory=lambda: _L(dec), cases=cases,
        config={"deep_think_provider": "deepseek", "deep_think_llm": "deepseek-flash",
                "temperature": 0},
        config_overridden=True,
    )
    assert report["model_config"].get("config_overridden") is True
    assert report["model_config"]["provider"] == "deepseek"
    assert report["model_config"]["model"] == "deepseek-flash"


# --- Acceptance gating: group REVIEW must not always map to PASS ---------

def _review_full_evidence_runs():
    """Three full-evidence runs that are REVIEW (missing date, no hard defect)."""
    from tools.sem_eval.gate import DATE_BASIS_NOTE  # noqa: F401 - documents intent

    runs = []
    for i in range(1, 4):
        run = _pass_run(i)
        run["audit_status"] = "DOWNGRADED"
        run["observed_status"] = "DOWNGRADED"
        run["observed_reasons"] = ["UNDATED_MARKET_DATA"]
        run["claims_attributed"] = 5
        run["claims"] = [
            {"kind": "supporting", "source": "market_report",
             "observation_date": None, "attributed": False,
             "reasons": ["UNDATED_MARKET_DATA"]},
        ]
        runs.append(run)
    return runs


@pytest.mark.unit
def test_full_evidence_acceptance_unmet_does_not_map_to_pass():
    # A complete report whose full-evidence case runs are REVIEW (missing date,
    # no hard defect) -> group REVIEW but acceptance unmet -> must be FAIL, not
    # PASS; the unmet case is named.
    replay = _complete_report(_review_full_evidence_runs())
    result = evaluate_pr(PROMPT, report=replay)
    assert result["gate"]["overall_decision"] == "REVIEW"
    assert result["gate"]["full_evidence_met"] is False
    assert result["status"] == "FAIL"
    assert result["exit_code"] == 1
    assert result["reason"] == "full_evidence_acceptance_unmet"
    assert result["unmet_cases"][0]["id"] == "baseline_full_evidence_dated"
    assert result["unmet_cases"][0]["reasons"]


@pytest.mark.unit
def test_full_evidence_pass_plus_thin_review_allows_group_pass():
    # Complete report: full-evidence case PASS; thin cases REVIEW (no hard
    # defect). The group is PASS (exit 0) with the REVIEW detail preserved.
    report = _complete_report()
    result = evaluate_pr(PROMPT, report=report)
    assert result["gate"]["full_evidence_met"] is True
    assert result["gate"]["overall_decision"] == "REVIEW"
    assert result["status"] == "PASS"
    assert result["exit_code"] == 0
    assert result["unmet_cases"] == []
    decisions = {c["id"]: c["decision"] for c in result["gate"]["cases"]}
    assert decisions["baseline_full_evidence_dated"] == "PASS"
    assert decisions["baseline_market_report_undated"] == "REVIEW"


# --- Report output explains a FAIL from acceptance-unmet REVIEW -----------

@pytest.mark.unit
def test_report_outputs_explain_fail_when_full_evidence_review_only(tmp_path):
    # A complete report whose full-evidence case only yields REVIEW -> group
    # REVIEW, acceptance unmet -> CI FAIL. Both report.json and summary.txt must
    # explain the FAIL.
    from tools.sem_eval.reportgen import finalize_verdict, write_report

    replay = _complete_report(_review_full_evidence_runs())  # REVIEW-only runs
    result = evaluate_pr(PROMPT, report=replay)
    assert result["status"] == "FAIL"
    assert result["reason"] == "full_evidence_acceptance_unmet"
    assert result["unmet_cases"][0]["id"] == "baseline_full_evidence_dated"

    envelope = {
        "schema": 1,
        "candidate_sha": "review123",
        "case_version": "basesha",
        "model_config": {"provider": "deepseek", "model": "deepseek-flash"},
        "repetitions": 1,
        "thresholds": "TBD",
        "replay": replay,
    }
    finalized = finalize_verdict(envelope, result)
    # Verdict metadata preserved.
    assert finalized["final_decision"] == "FAIL"
    assert finalized["exit_code"] == 1
    assert finalized["reason"] == "full_evidence_acceptance_unmet"
    assert finalized["unmet_cases"][0]["id"] == "baseline_full_evidence_dated"

    json_path, summary_path = write_report(finalized, tmp_path / "out")
    report_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert report_json["final_decision"] == "FAIL"
    assert report_json["reason"] == "full_evidence_acceptance_unmet"
    assert report_json["unmet_cases"]
    assert report_json["unmet_cases"][0]["reasons"]

    summary = summary_path.read_text(encoding="utf-8")
    assert "final_decision: FAIL" in summary
    assert "reason: full_evidence_acceptance_unmet" in summary
    assert "unmet_cases:" in summary
    assert "baseline_full_evidence_dated" in summary
