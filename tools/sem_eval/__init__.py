"""Gate 4 (semantic evaluation) — Portfolio Manager first version.

Phase 1: offline only. This package scores a run's ``material_claims`` with the
existing deterministic claim audit (:func:`tradingagents.reporting.audit_material_claims`)
and decides whether the semantic-eval gate applies to a set of changed paths.

It never calls a model, never touches the network, and never reports ``PASS``
when it cannot actually evaluate: a missing credential, timeout, evaluator
exception or an unexpected skip are all reported as ``INFRASTRUCTURE_ERROR``,
never ``PASS`` (REQ-TA-GOV-001; DEBT-003).

Thresholds remain TBD; this slice measures and reports, it does not yet block.
"""

from tools.sem_eval.evaluator import (
    CASE_RESULT_STATUSES,
    EVAL_STATUSES,
    EXIT_CODES,
    MODE_OFFLINE_PRECHECK,
    evaluate_case,
    evaluate_cases,
    exit_code_for,
    load_cases,
    render_summary,
)
from tools.sem_eval.triggers import TRIGGER_PATHS, is_semantic_eval_triggered

__all__ = [
    "CASE_RESULT_STATUSES",
    "EVAL_STATUSES",
    "EXIT_CODES",
    "MODE_OFFLINE_PRECHECK",
    "TRIGGER_PATHS",
    "evaluate_case",
    "evaluate_cases",
    "exit_code_for",
    "is_semantic_eval_triggered",
    "load_cases",
    "render_summary",
]
