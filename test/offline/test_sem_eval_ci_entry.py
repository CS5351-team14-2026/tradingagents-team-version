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


def _clean_report():
    """A report from the current PR where every run is clean (PASS)."""
    return {
        "status": "OBSERVE",
        "cases": [
            {
                "id": "case_clean",
                "runs": [
                    {
                        "repetition": 1,
                        "id": "case_clean",
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
                ],
            }
        ],
    }


def _degraded_report():
    """A report where a run has an unfounded market date (FAIL)."""
    report = _clean_report()
    report["cases"][0]["runs"][0]["observation_notes"] = ["date basis unverified"]
    return report


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
def test_archived_baseline_as_regression_material_fails_via_ci():
    # The archived baseline (regression material) carries hard defects, so the
    # gate verdict over it is FAIL/exit 1 when a triggered change is evaluated.
    report = json.loads(BASELINE.read_text(encoding="utf-8"))
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "FAIL"
    assert result["exit_code"] == 1


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

def _review_run():
    return {
        "repetition": 1, "id": "c", "audit_status": "NOT_ASSESSED",
        "observed_status": "NOT_ASSESSED", "observed_reasons": [],
        "claims_total": 0, "claims_attributed": 0, "claims": [],
        "observation_notes": [], "final_rating": "REVIEW", "confidence": None,
        "decision_review_reasons": ["unresolved_rating"], "matches_expectation": False,
        "evaluator_exception": False, "error": None,
    }


def _degraded_run():
    return {
        "repetition": 1, "id": "c", "audit_status": "DOWNGRADED",
        "observed_status": "DOWNGRADED", "observed_reasons": ["UNKNOWN_SOURCE"],
        "claims_total": 1, "claims_attributed": 0,
        "claims": [{"kind": "supporting", "source": "UNKNOWN",
                    "observation_date": None, "attributed": False,
                    "reasons": ["UNKNOWN_SOURCE"]}],
        "observation_notes": [], "final_rating": "Hold", "confidence": "low",
        "decision_review_reasons": [], "matches_expectation": False,
        "evaluator_exception": False, "error": None,
    }


@pytest.mark.unit
def test_all_review_maps_to_pass_top_level_with_per_run_review_detail():
    report = {"status": "OBSERVE", "cases": [{"id": "c", "runs": [_review_run()]}]}
    result = evaluate_pr(PROMPT, report=report)
    # Top-level is one of the four CI statuses; REVIEW is not a top-level status.
    assert result["status"] == "PASS"
    assert result["exit_code"] == 0
    assert result["blocks_merge"] is False
    # Per-run REVIEW detail preserved.
    assert result["gate"]["cases"][0]["runs"][0]["decision"] == "REVIEW"


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
