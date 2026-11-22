"""Gate 4 CI entry (offline-testable): triggers -> gate -> status + exit code.

Combines the reusable trigger matcher (:mod:`tools.sem_eval.triggers`) with the
gate-decision logic (:mod:`tools.sem_eval.gate`) into one result the GitHub
Actions job can consume:

- pure-docs / untracked change set -> ``NOT_APPLICABLE`` (exit 0), no evaluation;
- a triggered change with a baseline report -> run the gate over that report
  (which CI produces from the **current PR**, not the archived baseline) and
  map its overall decision to ``PASS`` / ``FAIL`` / ``INFRASTRUCTURE_ERROR``.

Exit codes reuse the Gate 4 mapping: PASS/NOT_APPLICABLE -> 0, FAIL -> 1,
INFRASTRUCTURE_ERROR -> 2. Merge blocking is NOT enabled this round: the job
runs as a non-required check; the ``blocks_merge`` field states the intent for
when thresholds are approved.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from tools.sem_eval.evaluator import exit_code_for
from tools.sem_eval.gate import decide_baseline
from tools.sem_eval.triggers import is_semantic_eval_triggered

MODES = ("offline_precheck", "semantic_replay")


def evaluate_pr(
    changed_paths: Iterable[str],
    *,
    report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide the Gate 4 outcome for a PR.

    ``changed_paths`` is the PR diff (``git diff --name-only``). ``report`` is a
    baseline/replay report produced from the current PR; it is only consulted
    when the change set triggers the gate. A triggered PR without a report is an
    ``INFRASTRUCTURE_ERROR`` (the job must produce one).
    """
    verdict, matched = is_semantic_eval_triggered(changed_paths)
    if verdict != "TRIGGERED":
        return {
            "status": "NOT_APPLICABLE",
            "exit_code": exit_code_for("NOT_APPLICABLE"),
            "reason": "no_prompt_or_model_change",
            "matched_paths": [],
            "blocks_merge": False,
            "thresholds": "TBD",
        }

    if report is None:
        return {
            "status": "INFRASTRUCTURE_ERROR",
            "exit_code": exit_code_for("INFRASTRUCTURE_ERROR"),
            "reason": "missing_evaluation_report",
            "matched_paths": matched,
            "blocks_merge": True,
            "thresholds": "TBD",
        }

    decision = decide_baseline(report)
    overall = decision["overall_decision"]
    full_evidence_met = decision.get("full_evidence_met", True)
    unmet = _unmet_acceptance(decision)
    # Map the gate's group decision to one of the four #81 CI statuses.
    if overall == "REVIEW":
        if full_evidence_met:
            # Only thin cases carry a reasoned REVIEW; the full-evidence case met
            # its acceptance condition. The group passes, with per-case REVIEW
            # detail preserved in ``gate``.
            status = "PASS"
            reason = None
        else:
            # The full-evidence case did NOT meet its acceptance condition. This
            # must NOT become PASS: it is a failure, and the unmet cases/reasons
            # are named.
            status = "FAIL"
            reason = "full_evidence_acceptance_unmet"
    elif overall in ("PASS", "FAIL", "INFRASTRUCTURE_ERROR"):
        status = overall
        reason = None if status != "INFRASTRUCTURE_ERROR" else "evaluation_infrastructure_error"
    else:
        status = "INFRASTRUCTURE_ERROR"
        reason = "evaluation_infrastructure_error"
    return {
        "status": status,
        "exit_code": exit_code_for(status),
        "reason": reason,
        "matched_paths": matched,
        "blocks_merge": status in ("FAIL", "INFRASTRUCTURE_ERROR"),
        "thresholds": "TBD",
        "unmet_cases": unmet,
        "gate": decision,
    }


def _unmet_acceptance(decision: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Cases that declared ``expects_pass`` but did not meet acceptance.

    Returns ``[{id, reasons}]`` where ``reasons`` are the non-PASS run reasons, so
    the CI result names which full-evidence case failed and why.
    """
    unmet: list[dict[str, Any]] = []
    for case in decision.get("cases", []):
        if case.get("expects_pass") and not case.get("meets_acceptance", False):
            reasons: list[str] = []
            for run in case.get("runs", []):
                if run.get("decision") != "PASS":
                    for reason in run.get("reasons", []):
                        if reason not in reasons:
                            reasons.append(reason)
            unmet.append({"id": case.get("id"), "reasons": reasons})
    return unmet


__all__ = ["MODES", "evaluate_pr"]
