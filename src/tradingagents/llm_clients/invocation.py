"""Admission at the graph boundary: may an optional LLM call start? (REQ-TA-FR-002).

Implements: ADR-004; REQ-TA-FR-002.

The budget is enforced in the graph, not only in the CLI, so direct
``TradingAgentsGraph`` callers get it too. The seam is the node boundary: an
*optional* node (a debate/risk contribution, an analyst follow-up round, a
retry, a reflection) asks this module whether it may start before it makes its
LLM call. A refusal is a control result — the node returns a controlled skip
marker and no request is issued — never a provider error that would trigger a
retry or fallback.

Already-admitted calls and calls that started below the limit are not
cancelled; a single in-flight call may push recorded usage past the limit
(ADR-004 D5). This module neither cancels requests nor claims a hard cap.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingagents.run_budget import (
    CallRole,
    RunBudgetContext,
    StartDecision,
    current_run_context,
)


class BudgetInvocationRefused(Exception):
    """A controlled refusal: the optional call was not started (ADR-004 D4).

    Carries the machine-readable reason codes so a node can record why its
    phase was skipped. Callers must never turn this into another LLM attempt.
    """

    def __init__(self, phase: str, reason_codes: tuple[str, ...]):
        self.phase = phase
        self.reason_codes = tuple(reason_codes)
        super().__init__(f"token budget stopped optional {phase}: {', '.join(self.reason_codes)}")


@dataclass(frozen=True)
class Admission:
    """Whether an optional call may start, and the call id it was admitted under."""

    allowed: bool
    reason_codes: tuple[str, ...]
    context: RunBudgetContext | None


def admit_optional(phase: str, *, context: RunBudgetContext | None = None) -> Admission:
    """Ask whether an OPTIONAL call may start; never raises.

    With no active budget context (a bare graph, or a no-budget run) the call is
    admitted, so baseline behaviour is preserved. With a context, this is an
    atomic :meth:`RunBudgetTracker.try_start` for an OPTIONAL call.
    """
    context = context or current_run_context()
    if context is None:
        return Admission(allowed=True, reason_codes=(), context=None)
    from uuid import uuid4

    decision: StartDecision = context.tracker.try_start(
        call_id=f"{phase}-{uuid4().hex[:8]}", role=CallRole.OPTIONAL, phase=phase
    )
    return Admission(allowed=decision.allowed, reason_codes=decision.reason_codes, context=context)


def require_or_admit(phase: str, *, role: CallRole, call_id: str, context: RunBudgetContext | None = None) -> Admission:
    """Run an admission check for a REQUIRED or OPTIONAL call, registering it.

    A required call is always admitted; an optional one is refused per policy.
    The caller uses the returned :class:`Admission` to decide whether to skip.
    """
    context = context or current_run_context()
    if context is None:
        return Admission(allowed=True, reason_codes=(), context=None)
    decision = context.tracker.try_start(call_id=call_id, role=role, phase=phase)
    return Admission(allowed=decision.allowed, reason_codes=decision.reason_codes, context=context)


__all__ = [
    "Admission",
    "BudgetInvocationRefused",
    "admit_optional",
    "require_or_admit",
]
