"""Per-run recorded usage and budget policy (REQ-TA-FR-002; REQ-TA-QR-004).

Implements ADR-003. Only provider-reported counts are retained; a known-token
lower bound is separate from the complete total. S1 supplies this accounting
foundation without enabling budget-driven graph routing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from enum import StrEnum
from threading import RLock
from typing import Any
from uuid import uuid4

USAGE_STATES = frozenset({"complete", "partial", "unavailable", "conflict"})
BUDGET_OK = "BUDGET_OK"
BUDGET_WARNING = "BUDGET_WARNING"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
BUDGET_STATE_VERSION = 1


class BudgetLedgerError(RuntimeError):
    """A durable-accounting failure that must stop further dispatch (FR-002).

    Only the fixed machine-readable reason is exposed. Storage paths, SQL,
    provider data and exception text are deliberately excluded.
    """

    phase = "budget_ledger"

    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        self.reason_codes = (reason_code,)
        super().__init__(f"Token budget accounting stopped: {reason_code}")


def _token_count(value: Any, name: str) -> None:
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(f"{name} must be a non-negative integer or None")


def _identity(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True)
class UsageObservation:
    """A single call's reported usage; unknown counts remain null (FR-002).

    ``generations_lower_bound`` marks sums across incomplete prompt groups.
    Those fields are reported lower bounds, so a richer complete callback may
    increase them. They never produce a complete run total while partial.
    """

    tokens_in: int | None = None
    tokens_out: int | None = None
    total_tokens: int | None = None
    state: str = "unavailable"
    source: str | None = None

    def __post_init__(self) -> None:
        for name in ("tokens_in", "tokens_out", "total_tokens"):
            _token_count(getattr(self, name), name)
        if not isinstance(self.state, str) or self.state not in USAGE_STATES:
            raise ValueError("unknown usage state")
        if self.source is not None:
            _identity(self.source, "source")
        if self.state == "complete":
            if self.tokens_in is None or self.tokens_out is None:
                raise ValueError("complete usage requires both input and output counts")
            if self.total_tokens is not None and self.total_tokens != self.tokens_in + self.tokens_out:
                raise ValueError("complete usage total conflicts with its input/output counts")
        if self.state == "unavailable" and any(
            getattr(self, name) is not None for name in ("tokens_in", "tokens_out", "total_tokens")
        ):
            raise ValueError("unavailable usage must not carry token counts")
        if (self.state == "partial" and self.total_tokens is not None
                and self.total_tokens < sum(value for value in (self.tokens_in, self.tokens_out)
                                            if value is not None)):
            raise ValueError("reported total is smaller than its reported components")

    @property
    def known_tokens(self) -> int | None:
        """Reported total or reported disjoint components, never an estimate."""
        if self.state in {"unavailable", "conflict"}:
            return None
        if self.total_tokens is not None:
            return self.total_tokens
        values = [value for value in (self.tokens_in, self.tokens_out) if value is not None]
        return sum(values) if values else None


class CallRole(StrEnum):
    OPTIONAL = "optional"
    REQUIRED = "required"


@dataclass(frozen=True)
class StartDecision:
    """Atomic logical-call admission; no cancellation promise (FR-002)."""

    allowed: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class BudgetSnapshot:
    """One immutable view; nullable totals preserve the QR-004 contract."""

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
    blocked_calls: int
    status: str
    reason_codes: tuple[str, ...]

    def to_stats(self) -> dict[str, Any]:
        """CLI-compatible observations with explicit availability (QR-004)."""
        return {
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "total_tokens": self.total_tokens,
            "known_tokens": self.known_tokens,
            "usage_complete": self.usage_complete,
            "usage_state": self.usage_state,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "pending_calls": self.pending_calls,
        }


@dataclass
class _Call:
    phase: str
    observation: UsageObservation | None = None
    terminal: bool = False
    exact_observation: UsageObservation | None = None


def _merge_usage(old: UsageObservation | None, new: UsageObservation) -> UsageObservation:
    if old is None or old.state == "unavailable":
        return new
    if new.state == "unavailable":
        return old
    if old.source == "generations_lower_bound" or new.source == "generations_lower_bound":
        return _merge_generation_bounds(old, new)
    fields = ("tokens_in", "tokens_out", "total_tokens")
    conflict = old.state == "conflict" or new.state == "conflict" or any(
        getattr(old, name) is not None
        and getattr(new, name) is not None
        and getattr(old, name) != getattr(new, name)
        for name in fields
    )
    values = {name: getattr(old, name) if getattr(old, name) is not None else getattr(new, name)
              for name in fields}
    if (values["tokens_in"] is not None and values["tokens_out"] is not None
            and values["total_tokens"] is not None
            and values["total_tokens"] != values["tokens_in"] + values["tokens_out"]):
        conflict = True
    state = "conflict" if conflict else (
        "complete" if "complete" in {old.state, new.state} else "partial"
    )
    return UsageObservation(**values, state=state, source=new.source or old.source)


def _merge_generation_bounds(old: UsageObservation, new: UsageObservation) -> UsageObservation:
    """Upgrade incomplete batch floors without weakening exact-report conflicts."""
    fields = ("tokens_in", "tokens_out", "total_tokens")
    old_bound = old.source == "generations_lower_bound"
    new_bound = new.source == "generations_lower_bound"
    conflict = old.state == "conflict" or new.state == "conflict"
    if old_bound and new_bound:
        values = {name: max(values) if (values := [getattr(obs, name) for obs in (old, new)
                                                   if getattr(obs, name) is not None]) else None
                  for name in fields}
        floor = sum(value for value in (values["tokens_in"], values["tokens_out"])
                    if value is not None)
        if values["total_tokens"] is not None:
            values["total_tokens"] = max(values["total_tokens"], floor)
        return UsageObservation(**values, state="conflict" if conflict else "partial",
                                source="generations_lower_bound")

    bound, exact = (old, new) if old_bound else (new, old)
    for name in fields:
        lower, reported = getattr(bound, name), getattr(exact, name)
        if lower is not None and reported is not None and reported < lower:
            conflict = True
    if (exact.state == "complete" and bound.known_tokens is not None
            and exact.known_tokens < bound.known_tokens):
        conflict = True
    if conflict:
        return UsageObservation(exact.tokens_in, exact.tokens_out, exact.total_tokens,
                                state="conflict", source=exact.source)
    if exact.state == "complete":
        return exact
    # Both callbacks remain partial. Keep their measured floors until a full
    # response can confirm the batch; do not label these merged counts exact.
    values = {name: max(values) if (values := [getattr(obs, name) for obs in (old, new)
                                               if getattr(obs, name) is not None]) else None
              for name in fields}
    floor = sum(value for value in (values["tokens_in"], values["tokens_out"])
                if value is not None)
    if values["total_tokens"] is not None:
        values["total_tokens"] = max(values["total_tokens"], floor)
    return UsageObservation(**values, state="partial", source="generations_lower_bound")


def _restore_usage(data: Any) -> UsageObservation | None:
    if data is None:
        return None
    if not isinstance(data, dict) or set(data) != {
        "tokens_in", "tokens_out", "total_tokens", "state", "source"
    }:
        raise ValueError("invalid usage ledger fields")
    return UsageObservation(**data)


def _validate_provenance(usage: UsageObservation | None, exact: UsageObservation | None) -> None:
    """Reject saved observations that discard or contradict exact provider facts."""
    if exact is None:
        if usage is not None and usage.source != "generations_lower_bound" and usage.state != "unavailable":
            raise ValueError("reported usage requires exact provenance")
        return
    if exact.source == "generations_lower_bound" or exact.state == "unavailable" or usage is None:
        raise ValueError("invalid exact usage provenance")
    corroborated = _merge_usage(usage, exact)
    if usage.state != "conflict" and any(
        getattr(corroborated, field) != getattr(usage, field)
        for field in ("tokens_in", "tokens_out", "total_tokens", "state")
    ):
        raise ValueError("usage contradicts its exact provenance")


class RunBudgetTracker:
    """Single-run ledger; callbacks and call admission share one lock (FR-002).

    A callback never enforces the budget. Call sites must use ``try_start``
    immediately before dispatch when the approved S2 enforcement is connected.
    ``start_call`` observes starts and deliberately never blocks them.
    """

    def __init__(self, limit: int | None = None, run_id: str | None = None):
        _token_count(limit, "token budget")
        if run_id is not None:
            _identity(run_id, "run_id")
        self._limit = limit
        self._run_id = run_id or str(uuid4())
        self._lock = RLock()
        self._calls: dict[str, _Call] = {}
        self._tools: set[str] = set()
        self._blocked: dict[str, str] = {}
        self._exhausted = limit == 0
        self._persistence_writer: Callable[[dict[str, Any]], None] | None = None
        self._failure_reason: str | None = None
        self._history_unavailable = False
        self._recovered_phases: set[str] = set()

    @property
    def limit(self) -> int | None:
        """A run's configured limit is fixed for its lifetime (FR-002 D8)."""
        return self._limit

    @property
    def run_id(self) -> str:
        """Callbacks and exported state retain one immutable run identity."""
        return self._run_id

    def raise_if_unhealthy(self) -> None:
        """Surface callback write failures even if a framework swallowed them."""
        with self._lock:
            if self._failure_reason is not None:
                raise BudgetLedgerError(self._failure_reason)

    def mark_history_unavailable(self, reason_code: str = "BUDGET_HISTORY_UNAVAILABLE") -> None:
        """Fail closed without representing missing history as zero (FR-002 D8)."""
        _identity(reason_code, "reason_code")
        with self._lock:
            self._failure_reason = self._failure_reason or reason_code
            self._history_unavailable = True

    def bind_persistence(self, writer: Callable[[dict[str, Any]], None]) -> None:
        """Commit the current ledger, then every mutation, before releasing its lock.

        The writer receives detached allowlisted state. It must atomically commit
        or raise; it must not call back into this tracker. Admission cannot return
        a permit before its start is durable. A failed writer permanently latches
        this in-memory run, including required calls, until a validated resume.
        """
        if not callable(writer):
            raise TypeError("persistence writer must be callable")
        with self._lock:
            self.raise_if_unhealthy()
            if self._persistence_writer is not None:
                raise ValueError("a budget persistence writer is already bound")
            self._persistence_writer = writer
            self._persist()

    def _persist(self) -> None:
        self.raise_if_unhealthy()
        if self._persistence_writer is None:
            return
        try:
            self._persistence_writer(self.export_state())
        except Exception as exc:
            reason = exc.reason_code if isinstance(exc, BudgetLedgerError) else "BUDGET_LEDGER_WRITE_FAILED"
            self.mark_history_unavailable(reason)
            raise BudgetLedgerError(reason) from None

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore into an empty tracker while preserving its public references.

        CLI callbacks and the active context may already refer to this instance.
        Restoration must happen before observation or persistence is bound. The
        configured limit must match the saved run; identity is never reset.
        """
        with self._lock:
            self.raise_if_unhealthy()
            if self._calls or self._tools or self._blocked or self._persistence_writer is not None:
                raise ValueError("budget state can only restore into an unbound empty tracker")
            try:
                restored = type(self).restore(state)
            except (TypeError, ValueError):
                self.mark_history_unavailable("BUDGET_LEDGER_INVALID")
                raise BudgetLedgerError("BUDGET_LEDGER_INVALID") from None
            if restored.limit != self.limit:
                self.mark_history_unavailable("BUDGET_LEDGER_IDENTITY_MISMATCH")
                raise BudgetLedgerError("BUDGET_LEDGER_IDENTITY_MISMATCH")
            self._run_id = restored.run_id
            self._calls = restored._calls
            self._tools = restored._tools
            self._blocked = restored._blocked
            self._exhausted = restored._exhausted
            self._recovered_phases = restored._recovered_phases

    def recover_inflight(self) -> int:
        """Mark starts left by a crash unavailable; never assume they cost zero.

        Pure ``restore`` retains pending states for serialization round trips.
        A durable resume invokes this explicitly before dispatch and binding the
        restored ledger to storage. Completed calls and their IDs stay intact.
        """
        with self._lock:
            self.raise_if_unhealthy()
            pending = [call for call in self._calls.values() if not call.terminal]
            for call in pending:
                call.terminal = True
                call.observation = UsageObservation()
            if pending:
                self._persist()
            return len(pending)

    def start_call(self, call_id: str, phase: str = "unclassified") -> None:
        """Record an actual start idempotently, without routing changes (S1)."""
        _identity(call_id, "call_id")
        _identity(phase, "phase")
        with self._lock:
            self.raise_if_unhealthy()
            if call_id not in self._calls:
                self._calls[call_id] = _Call(phase)
                self._persist()

    def finish_call(self, call_id: str, observation: UsageObservation) -> None:
        """Upsert one call's usage; duplicate callbacks do not accumulate."""
        _identity(call_id, "call_id")
        if not isinstance(observation, UsageObservation):
            raise TypeError("observation must be UsageObservation")
        with self._lock:
            self.raise_if_unhealthy()
            call = self._calls.setdefault(call_id, _Call("unclassified"))
            # An aggregate floor must never erase an earlier exact provider
            # assertion. Strictly retain those facts for later callbacks and
            # pure ledger restoration (ADR-003; REQ-TA-FR-002).
            if observation.source != "generations_lower_bound" and observation.state != "unavailable":
                call.exact_observation = _merge_usage(call.exact_observation, observation)
            call.observation = _merge_usage(call.observation, observation)
            if call.exact_observation is not None:
                call.observation = _merge_usage(call.observation, call.exact_observation)
            call.terminal = True
            self._update_exhaustion()
            self._persist()

    def fail_call(self, call_id: str) -> None:
        """An ended failure has unavailable usage unless already reported."""
        _identity(call_id, "call_id")
        with self._lock:
            self.raise_if_unhealthy()
            call = self._calls.setdefault(call_id, _Call("unclassified"))
            call.terminal = True
            if call.observation is None:
                call.observation = UsageObservation()
            self._persist()

    def record_tool(self, call_id: str) -> None:
        """Count a tool once; tools are never estimated as LLM tokens."""
        _identity(call_id, "call_id")
        with self._lock:
            self.raise_if_unhealthy()
            if call_id not in self._tools:
                self._tools.add(call_id)
                self._persist()

    def try_start(self, *, call_id: str, phase: str, role: CallRole) -> StartDecision:
        """Atomically check recorded usage and commit a logical start (FR-002)."""
        _identity(call_id, "call_id")
        _identity(phase, "phase")
        role = CallRole(role)
        with self._lock:
            self.raise_if_unhealthy()
            if call_id in self._calls:
                return StartDecision(False, ("ALREADY_STARTED",))
            # A checkpoint may replay a node after its first logical request
            # already started. That replay is a new optional retry, not another
            # first required contribution (REQ-TA-FR-002 D4/D8).
            optional = role is CallRole.OPTIONAL or phase in self._recovered_phases
            if optional and self.limit is not None:
                snapshot = self.snapshot()
                uncertain = any(call.terminal and (
                    call.observation is None or call.observation.state != "complete"
                ) for call in self._calls.values())
                if self._exhausted or uncertain:
                    self._blocked.setdefault(call_id, phase)
                    self._persist()
                    return StartDecision(False, snapshot.reason_codes)
            self._calls[call_id] = _Call(phase)
            self._persist()
            return StartDecision(True, ("CALL_STARTED",))

    def _known_tokens(self) -> int | None:
        values = [call.observation.known_tokens for call in self._calls.values()
                  if call.observation is not None and call.observation.known_tokens is not None]
        return sum(values) if values else None

    def _update_exhaustion(self) -> None:
        known = self._known_tokens()
        if self.limit is not None and known is not None and known >= self.limit:
            self._exhausted = True

    def snapshot(self) -> BudgetSnapshot:
        """Copy a coherent immutable view without treating missing data as zero."""
        with self._lock:
            observations = [call.observation for call in self._calls.values()
                            if call.observation is not None]
            pending = sum(not call.terminal for call in self._calls.values())
            complete = bool(self._calls) and not pending and not self._history_unavailable and all(
                call.observation is not None and call.observation.state == "complete"
                for call in self._calls.values()
            )
            counts = {}
            for name in ("tokens_in", "tokens_out"):
                values = [getattr(obs, name) for obs in observations
                          if obs.state != "conflict" and getattr(obs, name) is not None]
                counts[name] = sum(values) if values else None
            known = self._known_tokens()
            states = {obs.state for obs in observations}
            if "conflict" in states:
                usage_state = "conflict"
            elif complete:
                usage_state = "complete"
            elif known is not None:
                usage_state = "partial"
            else:
                usage_state = "unavailable"
            if self.limit is None:
                status, reasons = BUDGET_OK, ("NOT_CONFIGURED",)
            elif self._exhausted:
                reason = ("ZERO_TOKEN_BUDGET" if self.limit == 0 and known is None else
                          "RECORDED_USAGE_EXCEEDED_LIMIT" if known is not None and known > self.limit else
                          "RECORDED_USAGE_REACHED_LIMIT")
                status, reasons = BUDGET_EXHAUSTED, (reason,)
            elif not complete:
                reason = {"partial": "USAGE_PARTIAL", "conflict": "USAGE_CONFLICT",
                          "unavailable": "USAGE_UNAVAILABLE"}[usage_state]
                status, reasons = BUDGET_WARNING, (reason,)
                if pending:
                    reasons += ("PENDING_USAGE",)
            else:
                status, reasons = BUDGET_OK, ("WITHIN_RECORDED_BUDGET",)
            if self._failure_reason is not None:
                if status != BUDGET_EXHAUSTED:
                    status = BUDGET_WARNING
                reasons += (self._failure_reason,)
            return BudgetSnapshot(
                run_id=self.run_id, limit=self.limit, **counts,
                total_tokens=counts["tokens_in"] + counts["tokens_out"] if complete else None,
                known_tokens=known, usage_complete=complete, usage_state=usage_state,
                llm_calls=len(self._calls), tool_calls=len(self._tools), pending_calls=pending,
                blocked_calls=len(self._blocked), status=status, reason_codes=reasons,
            )

    def export_state(self) -> dict[str, Any]:
        """Versioned safe ledger data; durable checkpoint storage belongs to S3."""
        with self._lock:
            return {
                "version": BUDGET_STATE_VERSION,
                "run_id": self.run_id,
                "limit": self.limit,
                "exhausted": self._exhausted,
                "calls": [{"call_id": call_id, "phase": call.phase, "terminal": call.terminal,
                           "usage": asdict(call.observation) if call.observation is not None else None,
                           "exact_usage": asdict(call.exact_observation) if call.exact_observation is not None else None}
                          for call_id, call in sorted(self._calls.items())],
                "tool_ids": sorted(self._tools),
                "blocked": [{"call_id": call_id, "phase": phase}
                            for call_id, phase in sorted(self._blocked.items())],
            }

    @classmethod
    def restore(cls, state: dict[str, Any]) -> RunBudgetTracker:
        """Validate the allowlist; never silently reset a damaged ledger (FR-002)."""
        expected = {"version", "run_id", "limit", "exhausted", "calls", "tool_ids", "blocked"}
        if not isinstance(state, dict) or set(state) != expected:
            raise ValueError("invalid budget ledger fields")
        if type(state["version"]) is not int or state["version"] != BUDGET_STATE_VERSION:
            raise ValueError("unsupported budget ledger version")
        if type(state["exhausted"]) is not bool:
            raise ValueError("invalid budget exhaustion state")
        _identity(state["run_id"], "run_id")
        tracker = cls(limit=state["limit"], run_id=state["run_id"])
        if not all(isinstance(state[name], list) for name in ("calls", "tool_ids", "blocked")):
            raise ValueError("invalid budget ledger collections")
        for entry in state["calls"]:
            if not isinstance(entry, dict) or set(entry) != {
                "call_id", "phase", "terminal", "usage", "exact_usage"
            }:
                raise ValueError("invalid call ledger fields")
            _identity(entry["call_id"], "call_id")
            _identity(entry["phase"], "phase")
            if entry["call_id"] in tracker._calls or type(entry["terminal"]) is not bool:
                raise ValueError("duplicate call or invalid terminal state")
            usage = _restore_usage(entry["usage"])
            exact_usage = _restore_usage(entry["exact_usage"])
            _validate_provenance(usage, exact_usage)
            if entry["terminal"] and usage is None:
                raise ValueError("terminal calls must explicitly record usage availability")
            if not entry["terminal"] and usage is not None:
                raise ValueError("pending calls must not carry terminal usage observations")
            tracker._calls[entry["call_id"]] = _Call(
                entry["phase"], usage, entry["terminal"], exact_usage)
        for tool_id in state["tool_ids"]:
            _identity(tool_id, "tool_id")
            if tool_id in tracker._tools:
                raise ValueError("duplicate tool id")
            tracker._tools.add(tool_id)
        for entry in state["blocked"]:
            if not isinstance(entry, dict) or set(entry) != {"call_id", "phase"}:
                raise ValueError("invalid blocked-call fields")
            _identity(entry["call_id"], "call_id")
            _identity(entry["phase"], "phase")
            if entry["call_id"] in tracker._blocked:
                raise ValueError("duplicate blocked call")
            tracker._blocked[entry["call_id"]] = entry["phase"]
        tracker._exhausted = tracker._exhausted or state["exhausted"]
        tracker._update_exhaustion()
        tracker._recovered_phases = {call.phase for call in tracker._calls.values()}
        return tracker


_ACTIVE_CONTEXT: ContextVar[RunBudgetContext | None] = ContextVar("run_budget_context", default=None)


@dataclass(frozen=True)
class RunBudgetContext:
    """Explicit run lifetime shared across callbacks and graph workers (FR-002)."""

    tracker: RunBudgetTracker

    @contextmanager
    def activate(self) -> Iterator[RunBudgetContext]:
        """Restore the caller's context even after controlled or provider failure."""
        token = _ACTIVE_CONTEXT.set(self)
        try:
            yield self
        finally:
            _ACTIVE_CONTEXT.reset(token)


def current_run_context() -> RunBudgetContext | None:
    """Public context accessor; no component reads another's private state (QR-003)."""
    return _ACTIVE_CONTEXT.get()
