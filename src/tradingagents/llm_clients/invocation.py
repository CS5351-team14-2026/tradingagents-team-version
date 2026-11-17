"""Admission immediately before a logical LLM invocation (REQ-TA-FR-002).

Implements ADR-003. Callbacks observe usage; a distinct refusal at this boundary
prevents retries and fallbacks from treating the budget as a provider failure.
Already dispatched calls and SDK transport retries are not cancelled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from langchain_core.runnables.config import merge_configs

from tradingagents.run_budget import CallRole, RunBudgetContext, current_run_context

from .usage import UsageCallbackHandler, normalize_usage


@dataclass(frozen=True)
class CallSpec:
    """One immediately dispatched logical call, including structured attempts."""

    phase: str
    role: CallRole
    call_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self):
        if not isinstance(self.phase, str) or not self.phase:
            raise ValueError("call phase must be a non-empty string")
        if not isinstance(self.call_id, str) or not self.call_id:
            raise ValueError("call identity must be a non-empty string")
        object.__setattr__(self, "role", CallRole(self.role))


class BudgetInvocationRefused(Exception):
    """Controlled refusal; callers must not turn it into another LLM attempt."""

    def __init__(self, call: CallSpec, reason_codes: tuple[str, ...]):
        self.call_id = call.call_id
        self.phase = call.phase
        self.reason_codes = reason_codes
        super().__init__(f"Token budget stopped optional {call.phase}: {', '.join(reason_codes)}")


def invoke_with_budget(
    model: Any,
    model_input: Any,
    *,
    context: RunBudgetContext | None = None,
    call: CallSpec,
    config=None,
    **kwargs,
):
    """Admit one call and associate nested model callbacks with its identity.

    A supported structured runnable performs one logical model invocation.
    Its internal LangChain run ID can differ from the outer runnable's ID;
    allowlisted metadata connects both callback registrations to this ledger
    entry. Each retry or fallback must call this boundary separately.
    """
    context = context or current_run_context()
    if context is None:
        return model.invoke(model_input, **kwargs) if config is None else model.invoke(
            model_input, config=config, **kwargs)
    with context.activate():
        return _invoke_active(model, model_input, context, call, config, kwargs)


def _invoke_active(model, model_input, context, call, config, kwargs):
    if context.tracker.limit is None:
        # Preserve the baseline call shape for no-budget users and old doubles.
        return model.invoke(model_input, **kwargs) if config is None else model.invoke(
            model_input, config=config, **kwargs)

    tracker = context.tracker
    decision = tracker.try_start(call_id=call.call_id, phase=call.phase, role=call.role)
    if not decision.allowed:
        raise BudgetInvocationRefused(call, decision.reason_codes)
    call_config = merge_configs(config, {
        "metadata": {"ta_budget_call_id": call.call_id},
        "callbacks": [UsageCallbackHandler(tracker)],
    })
    try:
        result = model.invoke(model_input, config=call_config, **kwargs)
        # Plain doubles/adapters can return reported usage without callbacks.
        # A structured parsed object supplies no usage; unavailable never
        # replaces a complete observation already received from the model.
        observed = next(entry for entry in tracker.export_state()["calls"]
                        if entry["call_id"] == call.call_id)
        if not observed["terminal"]:
            tracker.finish_call(call.call_id, normalize_usage(result))
        tracker.raise_if_unhealthy()
        return result
    finally:
        # Failed or callback-free attempts are explicitly ended, never zeroed.
        tracker.fail_call(call.call_id)
