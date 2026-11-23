"""CI helper: decide the Gate 4 outcome for a PR and exit 0/1/2.

Flow (see the human requirements for Phase 3C):

- docs-only / untriggered -> NOT_APPLICABLE, exit 0, no model credential read;
- triggered, no model credential -> INFRASTRUCTURE_ERROR, exit 2 (never a
  fabricated PASS, never a silent advisory pass);
- triggered, credential present -> generate a fresh report for **this PR** and
  run it through :func:`tools.sem_eval.ci_entry.evaluate_pr`, exiting its code.

A missing report / evaluation exception also yields INFRASTRUCTURE_ERROR/exit 2.
The live model call happens only when a credential is present, i.e. inside the
trusted execution environment (the CI job with the owner's secret, or the
owner's machine). This module reads no credential itself and does no network
unless the caller has chosen the live path.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from tools.sem_eval.ci_entry import evaluate_pr

CASES_PATH = "test/fixtures/gate4/baseline_cases.json"
REPETITIONS = 3


def _load_cases() -> list[dict[str, Any]]:
    import json

    with open(CASES_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def decide(
    *,
    triggered: bool,
    paths: list[str],
    candidate_sha: str,
    llm_factory: Any | None = None,
    cases: list[dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
    config_overridden: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Decision helper (isolated factory for offline testing).

    Returns ``(ci_result, report)``. ``report`` is ``None`` when no evaluation was
    produced. The real evaluation reads the **candidate version's** effective PM
    (deep-tier) config via the application's own resolution and builds the same
    client the production graph would; an unsupported provider or a missing
    credential is an INFRASTRUCTURE_ERROR (never a fallback to another model, never
    a fabricated PASS). Pure-docs paths return NOT_APPLICABLE before any config or
    credential access. An injected ``llm_factory`` lets offline tests use a double.

    ``config`` may override the candidate config (manual runs, e.g. an explicit
    DeepSeek smoke); ``config_overridden`` records that the report is not the
    candidate's stock config.
    """
    from tools.sem_eval.reportgen import (
        build_report,
        candidate_llm_factory,
        effective_pm_model_config,
        validate_pm_model_config,
    )

    # Docs-only / untriggered: NOT_APPLICABLE, no model config or key touched.
    if not triggered:
        return evaluate_pr(paths), None

    def _infra(reason: str) -> tuple[dict[str, Any], None]:
        return {
            "status": "INFRASTRUCTURE_ERROR",
            "exit_code": 2,
            "reason": reason,
            "matched_paths": paths,
            "blocks_merge": True,
            "thresholds": "TBD",
        }, None

    model_config = effective_pm_model_config(config)
    if config_overridden:
        model_config = {**model_config, "config_overridden": True}

    # Validate the candidate's PM model config unless a test double is injected
    # (the double stands in for a live model, so real provider/key checks are
    # bypassed only on that offline path).
    if llm_factory is None:
        ok, reason = validate_pm_model_config(config)
        if not ok:
            return _infra(reason or "invalid_model_config")
        llm_factory = candidate_llm_factory(config)

    if cases is None:
        try:
            cases = _load_cases()
        except (OSError, ValueError):
            return _infra("missing_cases")

    try:
        report = build_report(
            cases,
            llm_factory=llm_factory,
            candidate_sha=candidate_sha,
            model_config={**model_config, "repetitions": REPETITIONS},
            repetitions=REPETITIONS,
        )
    except Exception:  # noqa: BLE001 - any failure is an infra error, never PASS
        return _infra("evaluation_exception")

    return evaluate_pr(paths, report=report["replay"]), report


def main(argv: list[str]) -> int:
    changed_file = argv[1] if len(argv) > 1 else "changed.txt"
    trigger_file = argv[2] if len(argv) > 2 else "trigger.out"
    with open(trigger_file, encoding="utf-8") as handle:
        verdict = handle.read().strip()
    with open(changed_file, encoding="utf-8") as handle:
        paths = [line.strip() for line in handle if line.strip()]

    triggered = verdict == "TRIGGERED"
    candidate_sha = os.environ.get("GITHUB_SHA", "")

    # Manual runs may pin an explicit model via env (e.g. a DeepSeek smoke); the
    # formal PR check sets neither and uses the candidate's actual deep-tier
    # config, so a model switch in the PR is evaluated on the new model.
    override: dict[str, Any] = {}
    if os.environ.get("GATE4_PROVIDER"):
        override["deep_think_provider"] = os.environ["GATE4_PROVIDER"]
    if os.environ.get("GATE4_MODEL"):
        override["deep_think_llm"] = os.environ["GATE4_MODEL"]
    if os.environ.get("GATE4_TEMPERATURE"):
        override["temperature"] = os.environ["GATE4_TEMPERATURE"]

    result, report = decide(
        triggered=triggered,
        paths=paths,
        candidate_sha=candidate_sha,
        config=override or None,
        config_overridden=bool(override),
    )

    if report is not None:
        from tools.sem_eval.reportgen import finalize_verdict, write_report

        finalized = finalize_verdict(report, result)
        json_path, summary_path = write_report(finalized, "gate4-report")
        print(json_path.read_text(encoding="utf-8"))
        print(summary_path.read_text(encoding="utf-8"))

    print(f"GATE4 status={result['status']} exit={result['exit_code']} "
          f"reason={result.get('reason')}")
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main(sys.argv))
