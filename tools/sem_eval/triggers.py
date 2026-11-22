"""Which changed paths trigger the Gate 4 semantic evaluation.

Portfolio Manager first version. The gate is triggered when a PR touches a
surface that can change the PM decision prompt, the model that answers it, or
how its output is parsed and audited. A change confined to documentation (or
anything else outside the trigger set) is ``NOT_APPLICABLE``: the gate cannot
honestly report ``PASS`` for work it never evaluated, so it says so explicitly.

Matches the Portfolio Manager subset of the REQ-TA-GOV-001 fit criterion; the
broader analyst/reflection surfaces are a later slice.

Pure function, no I/O: Phase 2's CI job feeds it ``git diff --name-only``.
"""

from __future__ import annotations

from collections.abc import Iterable

# Why each path triggers the gate (kept beside the pattern for review).
TRIGGER_PATHS: tuple[tuple[str, str], ...] = (
    ("src/tradingagents/agents/managers/portfolio_manager.py", "PM prompt"),
    ("src/tradingagents/agents/schemas.py", "PM structured schema + field descriptions"),
    ("src/tradingagents/agents/rating.py", "rating / price output parsing"),
    ("src/tradingagents/agents/structured.py", "structured-output parsing path"),
    ("src/tradingagents/reporting.py", "claim audit / evidence scoring"),
    ("src/tradingagents/llm_clients/model_catalog.py", "model configuration"),
    ("src/tradingagents/llm_clients/factory.py", "model configuration"),
    ("src/tradingagents/llm_clients/openai_client.py", "model configuration"),
    ("src/tradingagents/default_config.py", "default model configuration"),
    ("prompts/", "versioned prompt snapshots"),
)

_PREFIX_PATHS = frozenset(p for p, _why in TRIGGER_PATHS if p.endswith("/"))


def _matches(path: str) -> bool:
    for pattern in _PREFIX_PATHS:
        if path.startswith(pattern):
            return True
    return any(path == p for p, _why in TRIGGER_PATHS if not p.endswith("/"))


def is_semantic_eval_triggered(changed_paths: Iterable[str]) -> tuple[str, list[str]]:
    """Return ``(verdict, matched_paths)``.

    ``verdict`` is ``"TRIGGERED"`` when any changed path touches a tracked
    surface, otherwise ``"NOT_APPLICABLE"``. A pure-docs (or empty) change set
    returns ``NOT_APPLICABLE`` and an empty match list; it is never ``PASS``.
    """
    matched = sorted({p for p in changed_paths if _matches(p)})
    if matched:
        return "TRIGGERED", matched
    return "NOT_APPLICABLE", []
