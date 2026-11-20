"""Per-run recorded token usage and the optional-call budget (REQ-TA-FR-002).

Implements: ADR-004; REQ-TA-FR-002; REQ-TA-QR-004.

This module owns one analysis run's usage ledger and the pure budget policy
that decides whether an *optional* LLM call may start. It depends only on the
standard library: not on the CLI, the graph internals, or any provider SDK, so
both the CLI path and direct ``TradingAgentsGraph`` callers can share it.

Design facts fixed by ADR-004:

- Only provider-reported counts are retained. A known-token lower bound (from
  ``partial`` observations) is distinct from a complete total and is never
  presented as one (D1).
- A call the provider does not report makes the run's accounting incomplete;
  that never becomes a fabricated zero (D2).
- Admission is atomic and lock-protected: analysts and the Memory Log run in
  parallel, and a late callback is charged to the run that started its call
  (D5).
- A single in-flight call may push recorded usage past the limit; no exact
  hard cap is claimed (D5).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Any
from uuid import uuid4

# Usage observation states. "complete" = both counts reported; "partial" = a
# non-overlapping lower bound; "unavailable" = nothing usable reported;
# "conflict" = reported fields disagree.
USAGE_COMPLETE = "complete"
USAGE_PARTIAL = "partial"
USAGE_UNAVAILABLE = "unavailable"
USAGE_CONFLICT = "conflict"
USAGE_STATES = frozenset({USAGE_COMPLETE, USAGE_PARTIAL, USAGE_UNAVAILABLE, USAGE_CONFLICT})

# Budget result statuses (REQ-TA-FR-002).
BUDGET_OK = "BUDGET_OK"
BUDGET_WARNING = "BUDGET_WARNING"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
BUDGET_STATUSES = (BUDGET_OK, BUDGET_WARNING, BUDGET_EXHAUSTED)

# Machine-readable reason codes. Allowlisted; never carry paths, keys or text.
REASON_NOT_CONFIGURED = "NOT_CONFIGURED"
REASON_WITHIN_RECORDED_BUDGET = "WITHIN_RECORDED_BUDGET"
REASON_RECORDED_USAGE_REACHED_LIMIT = "RECORDED_USAGE_REACHED_LIMIT"
REASON_RECORDED_USAGE_EXCEEDED_LIMIT = "RECORDED_USAGE_EXCEEDED_LIMIT"
REASON_USAGE_PARTIAL = "USAGE_PARTIAL"
REASON_USAGE_UNAVAILABLE = "USAGE_UNAVAILABLE"
REASON_USAGE_CONFLICT = "USAGE_CONFLICT"
REASON_USAGE_HISTORY_UNAVAILABLE = "USAGE_HISTORY_UNAVAILABLE"

# The format version of the ledger's exported identity (checkpoint resume).
BUDGET_STATE_VERSION = 1


class CallRole(StrEnum):
    """Whether a call may start once the budget is reached (ADR-004 D4)."""

    OPTIONAL = "optional"
    REQUIRED = "required"


def _count(value: Any, name: str) -> None:
    """Validate an optional non-negative integer token count (bools rejected)."""
    if value is None:
        return
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer or None, got {value!r}")


@dataclass(frozen=True)
class UsageObservation:
    """One call's reported usage; unknown fields stay ``None`` (ADR-004 D1/D2).

    A genuine reported zero (``tokens_in=0``) is distinct from an unknown field
    (``None``). ``state`` records how much of the call's usage was observed; a
    ``partial`` observation's ``tokens_in``/``tokens_out`` are a non-overlapping
    lower bound, never the call's exact total.
    """

    tokens_in: int | None = None
    tokens_out: int | None = None
    state: str = USAGE_UNAVAILABLE

    def __post_init__(self) -> None:
        _count(self.tokens_in, "tokens_in")
        _count(self.tokens_out, "tokens_out")
        if self.state not in USAGE_STATES:
            raise ValueError(f"unknown usage state {self.state!r}")
        if self.state == USAGE_UNAVAILABLE and (
            self.tokens_in is not None or self.tokens_out is not None
        ):
            raise ValueError("unavailable usage must not carry token counts")
        if self.state == USAGE_COMPLETE and (self.tokens_in is None or self.tokens_out is None):
            raise ValueError("complete usage requires both input and output counts")

    @property
    def known_tokens(self) -> int | None:
        """The reported total or reported disjoint components; never an estimate."""
        if self.state in (USAGE_UNAVAILABLE, USAGE_CONFLICT):
            return None
        values = [value for value in (self.tokens_in, self.tokens_out) if value is not None]
        return sum(values) if values else None


@dataclass(frozen=True)
class StartDecision:
    """The result of an atomic admission check; no cancellation is promised."""

    allowed: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class BudgetSnapshot:
    """An immutable view of one run's usage and budget result (REQ-TA-QR-004).

    Nullable token totals preserve the QR-004 contract: unavailable usage is
    ``None`` with ``usage_complete=False``, never a fabricated zero.
    """

    run_id: str
    limit: int | None
    tokens_in: int | None
    tokens_out: int | None
    total_tokens: int | None
    known_tokens: int | None
    usage_complete: bool
    usage_state: str
    llm_calls: int
    tool_calls: int
    pending_calls: int
    status: str
    reason_codes: tuple[str, ...]

    def to_metadata(self) -> dict[str, Any]:
        """The budget block for the run record's ``run_metadata`` (allowlisted)."""
        return {
            "status": self.status,
            "limit": self.limit,
            "reason_codes": list(self.reason_codes),
            "usage_state": self.usage_state,
            "usage_complete": self.usage_complete,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "total_tokens": self.total_tokens,
            "known_tokens": self.known_tokens,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
        }


@dataclass
class _Call:
    role: CallRole
    phase: str
    observation: UsageObservation | None = None
    failed: bool = False


class RunBudgetTracker:
    """One run's usage ledger and budget policy (Implements: ADR-004; FR-002).

    ``limit=None`` disables enforcement: every call is admitted and the budget
    result is ``BUDGET_OK`` with ``NOT_CONFIGURED``. Usage is still observed and
    reported honestly, so the no-budget run reports complete/incomplete usage
    as the baseline did, without changing execution behaviour.
    """

    def __init__(self, limit: int | None = None, run_id: str | None = None):
        if limit is not None:
            if type(limit) is bool or not isinstance(limit, int):
                raise ValueError(f"token budget must be a non-negative integer or None, got {limit!r}")
            if limit < 0:
                raise ValueError(f"token budget must be >= 0, got {limit}")
        self._limit = limit
        self._run_id = run_id or f"run-{uuid4().hex[:12]}"
        self._lock = RLock()
        self._calls: dict[str, _Call] = {}
        self._tool_calls = 0
        self._history_unavailable = False

    # --- identity ---------------------------------------------------------

    @property
    def limit(self) -> int | None:
        return self._limit

    @property
    def run_id(self) -> str:
        return self._run_id

    def mark_history_unavailable(self) -> None:
        """Flag a legacy resume whose pre-checkpoint usage is unknown (ADR-004)."""
        with self._lock:
            self._history_unavailable = True

    # --- call lifecycle ---------------------------------------------------

    def start_call(self, call_id: str, *, role: CallRole, phase: str) -> None:
        """Register an in-flight logical call. Idempotent observation registration.

        This is not admission control (use :meth:`try_start` for that); it lets
        a callback associate a late result with the run that started the call.
        """
        if not call_id:
            raise ValueError("call_id must be a non-empty string")
        with self._lock:
            existing = self._calls.get(call_id)
            if existing is None:
                self._calls[call_id] = _Call(role=CallRole(role), phase=phase)
            else:
                # A duplicate start for the same identity keeps the role/phase
                # but refreshes nothing else; a second delivery of one event
                # must not double count.
                existing.role = CallRole(role)
                existing.phase = phase

    def finish_call(self, call_id: str, observation: UsageObservation) -> None:
        """Record one call's usage; a later, more complete observation replaces it.

        Replacing (not adding) prevents a callback delivered twice for the same
        call from inflating usage, while letting a richer observation upgrade a
        lower bound.
        """
        if not isinstance(observation, UsageObservation):
            raise TypeError("observation must be a UsageObservation")
        with self._lock:
            call = self._calls.get(call_id)
            if call is None:
                # A result with no registration still counts; its role is
                # unknown, treated as required so it never hides usage.
                call = _Call(role=CallRole.REQUIRED, phase="unclassified")
                self._calls[call_id] = call
            call.observation = observation
            call.failed = False

    def fail_call(self, call_id: str) -> None:
        """Mark a call ended without a usable observation; its usage is unknown."""
        with self._lock:
            call = self._calls.get(call_id)
            if call is None:
                call = _Call(role=CallRole.REQUIRED, phase="unclassified")
                self._calls[call_id] = call
            if call.observation is None:
                call.failed = True

    def record_tool(self, call_id: str | None = None) -> None:
        """Count one tool call (tools are not LLM token usage)."""
        with self._lock:
            self._tool_calls += 1

    # --- admission --------------------------------------------------------

    def try_start(self, *, call_id: str, role: CallRole, phase: str) -> StartDecision:
        """Atomically admit an optional call, or refuse it once the budget stops it.

        A required call is always admitted. With no limit, everything is
        admitted. An optional call is refused when recorded usage reaches or
        exceeds the limit (D1), and also — conservatively — when accounting is
        incomplete below the limit (a partial or unavailable observation), so
        the budget can never be silently overrun by an unverifiable remainder
        (D2/D3). The check and the registration happen under the lock so two
        parallel analysts cannot both slip past the threshold (D5).
        """
        role = CallRole(role)
        with self._lock:
            if self._limit is not None and role is CallRole.OPTIONAL:
                # A zero budget admits no optional call at all, even before any
                # usage is observed (ADR-004 D6: "zero blocks optional calls
                # immediately").
                if self._limit == 0:
                    return StartDecision(allowed=False, reason_codes=(REASON_RECORDED_USAGE_REACHED_LIMIT,))
                ins, outs, states, any_incomplete, any_conflict = self._observed_locked()
                known = self._known_tokens_locked()
                if known is not None and known >= self._limit:
                    return StartDecision(allowed=False, reason_codes=self._threshold_reasons_locked(known))
                if any_conflict:
                    return StartDecision(allowed=False, reason_codes=(REASON_USAGE_CONFLICT,))
                if self._history_unavailable:
                    return StartDecision(allowed=False, reason_codes=(REASON_USAGE_HISTORY_UNAVAILABLE,))
                if any_incomplete:
                    reason = REASON_USAGE_UNAVAILABLE if known is None else REASON_USAGE_PARTIAL
                    return StartDecision(allowed=False, reason_codes=(reason,))
            # Admitted: register the in-flight call so its result is attributed.
            existing = self._calls.get(call_id)
            if existing is None:
                self._calls[call_id] = _Call(role=role, phase=phase)
            else:
                existing.role = role
                existing.phase = phase
            return StartDecision(allowed=True, reason_codes=())

    def _threshold_reasons_locked(self, known: int) -> tuple[str, ...]:
        assert self._limit is not None
        code = (
            REASON_RECORDED_USAGE_REACHED_LIMIT
            if known == self._limit
            else REASON_RECORDED_USAGE_EXCEEDED_LIMIT
        )
        return (code,)

    # --- aggregation ------------------------------------------------------

    def _observed_locked(self) -> tuple[list[int | None], list[int | None], list[str], bool, bool]:
        """(ins, outs, states, any_incomplete, any_conflict) across finished calls."""
        ins: list[int | None] = []
        outs: list[int | None] = []
        states: list[str] = []
        any_incomplete = False
        any_conflict = False
        for call in self._calls.values():
            obs = call.observation
            if obs is None:
                if call.failed:
                    any_incomplete = True
                continue  # still in flight: not yet counted
            ins.append(obs.tokens_in)
            outs.append(obs.tokens_out)
            states.append(obs.state)
            if obs.state in (USAGE_PARTIAL, USAGE_UNAVAILABLE):
                any_incomplete = True
            elif obs.state == USAGE_CONFLICT:
                any_conflict = True
                any_incomplete = True
        return ins, outs, states, any_incomplete, any_conflict

    def _known_tokens_locked(self) -> int | None:
        ins, outs, _states, _inc, _conf = self._observed_locked()
        values = [v for v in (*ins, *outs) if v is not None]
        return sum(values) if values else None

    def _sum_locked(self, values: list[int | None]) -> int | None:
        present = [v for v in values if v is not None]
        return sum(present) if present else None

    def snapshot(self) -> BudgetSnapshot:
        """An immutable view: usage, completeness, budget status and reasons."""
        with self._lock:
            ins, outs, states, any_incomplete, any_conflict = self._observed_locked()
            pending = sum(1 for c in self._calls.values() if c.observation is None and not c.failed)
            llm_calls = sum(1 for c in self._calls.values() if c.observation is not None)

            complete = (
                bool(self._calls)
                and not any_incomplete
                and not self._history_unavailable
                and all(s == USAGE_COMPLETE for s in states)
            )
            tokens_in = self._sum_locked(ins)
            tokens_out = self._sum_locked(outs)
            total = tokens_in + tokens_out if complete and tokens_in is not None and tokens_out is not None else None
            # The known-token lower bound: the sum of every reported count
            # (complete, partial or a reported zero), never an estimate.
            known = self._known_tokens_locked()

            if any_conflict:
                usage_state = USAGE_CONFLICT
            elif self._history_unavailable:
                usage_state = USAGE_UNAVAILABLE
            elif complete:
                usage_state = USAGE_COMPLETE
            elif known is not None:
                # Some counts were reported but not all calls are complete.
                usage_state = USAGE_PARTIAL
            else:
                usage_state = USAGE_UNAVAILABLE

            status, reasons = self._status_locked(
                known=known, complete=complete,
                any_incomplete=any_incomplete, any_conflict=any_conflict,
            )

            return BudgetSnapshot(
                run_id=self._run_id,
                limit=self._limit,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                total_tokens=total,
                known_tokens=known,
                usage_complete=complete,
                usage_state=usage_state,
                llm_calls=llm_calls,
                tool_calls=self._tool_calls,
                pending_calls=pending,
                status=status,
                reason_codes=reasons,
            )

    def _status_locked(
        self, *, known: int | None, complete: bool, any_incomplete: bool, any_conflict: bool,
    ) -> tuple[str, tuple[str, ...]]:
        if self._limit is None:
            reasons = [REASON_NOT_CONFIGURED]
            if any_conflict:
                reasons.append(REASON_USAGE_CONFLICT)
            elif any_incomplete:
                reasons.append(REASON_USAGE_UNAVAILABLE if known is None else REASON_USAGE_PARTIAL)
            return BUDGET_OK, tuple(reasons)

        # Known usage that already reaches the limit establishes exhaustion,
        # regardless of other incomplete/unknown calls (D1/D2 take precedence).
        if known is not None and known >= self._limit:
            reasons: list[str] = list(self._threshold_reasons_locked(known))
            if not complete:
                reasons.append(REASON_USAGE_PARTIAL)
            return BUDGET_EXHAUSTED, tuple(reasons)

        # No known usage, or incomplete/conflicting observations below the
        # limit: cannot certify the budget was enforced precisely => warning.
        if any_conflict:
            return BUDGET_WARNING, (REASON_USAGE_CONFLICT,)
        if self._history_unavailable:
            # A legacy resume whose pre-checkpoint usage is unknown: report the
            # distinct history-unavailable reason (ADR-004 D8), never a zero.
            return BUDGET_WARNING, (REASON_USAGE_HISTORY_UNAVAILABLE,)
        if any_incomplete:
            reason = REASON_USAGE_UNAVAILABLE if known is None else REASON_USAGE_PARTIAL
            return BUDGET_WARNING, (reason,)

        # Complete usage strictly below the limit.
        return BUDGET_OK, (REASON_WITHIN_RECORDED_BUDGET,)

    # --- QR-004 bridge ----------------------------------------------------

    def to_usage_summary(self):
        """A ``run_record.UsageSummary`` mirroring this ledger (REQ-TA-QR-004).

        Complete usage yields summed counts; incomplete usage keeps null totals
        with ``usage_complete=False`` (never a fabricated total).
        """
        from tradingagents.run_record import UsageSummary

        snap = self.snapshot()
        return UsageSummary(
            tokens_in=snap.tokens_in,
            tokens_out=snap.tokens_out,
            llm_calls=snap.llm_calls,
            tool_calls=snap.tool_calls,
            usage_complete=snap.usage_complete,
        )


class RunBudgetContext:
    """Binds one run's tracker for the duration of an execution (ADR-004 D5).

    Callbacks and the invocation boundary resolve the active context, so a call
    started in this run is charged to it even when its end event arrives late.
    """

    def __init__(self, tracker: RunBudgetTracker):
        if not isinstance(tracker, RunBudgetTracker):
            raise TypeError("tracker must be a RunBudgetTracker")
        self.tracker = tracker

    @contextmanager
    def activate(self) -> Iterator[RunBudgetTracker]:
        token = _current_context.set(self)
        try:
            yield self.tracker
        finally:
            _current_context.reset(token)


_current_context: ContextVar[RunBudgetContext | None] = ContextVar(
    "tradingagents_run_budget", default=None
)


def current_run_context() -> RunBudgetContext | None:
    """The budget context bound to the current execution, if any."""
    return _current_context.get()


def bind_context(tracker: RunBudgetTracker) -> RunBudgetContext:
    """Bind ``tracker`` as the current execution's context and return it.

    For a caller that runs steps inside a copied ``contextvars.Context`` (the
    graph's streaming path): binding inside that context makes each step
    resolve this run's ledger. Unlike :meth:`RunBudgetContext.activate`, this
    does not reset on exit; the copied context is discarded by the caller.
    """
    context = RunBudgetContext(tracker)
    _current_context.set(context)
    return context


def budget_from_config(config: dict | None) -> RunBudgetTracker:
    """Build a tracker from a run config's ``token_budget`` (ADR-004 D6).

    A missing key or ``None`` disables enforcement (baseline behaviour).
    """
    raw = (config or {}).get("token_budget")
    return RunBudgetTracker(raw)


__all__ = [
    "BUDGET_EXHAUSTED",
    "BUDGET_OK",
    "BUDGET_STATUSES",
    "BUDGET_STATE_VERSION",
    "BUDGET_WARNING",
    "BudgetSnapshot",
    "CallRole",
    "REASON_NOT_CONFIGURED",
    "REASON_RECORDED_USAGE_EXCEEDED_LIMIT",
    "REASON_RECORDED_USAGE_REACHED_LIMIT",
    "REASON_USAGE_CONFLICT",
    "REASON_USAGE_HISTORY_UNAVAILABLE",
    "REASON_USAGE_PARTIAL",
    "REASON_USAGE_UNAVAILABLE",
    "REASON_WITHIN_RECORDED_BUDGET",
    "RunBudgetContext",
    "RunBudgetTracker",
    "StartDecision",
    "USAGE_COMPLETE",
    "USAGE_CONFLICT",
    "USAGE_PARTIAL",
    "USAGE_STATES",
    "USAGE_UNAVAILABLE",
    "UsageObservation",
    "bind_context",
    "budget_from_config",
    "current_run_context",
]
