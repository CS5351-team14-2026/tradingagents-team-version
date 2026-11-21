"""Per-run data-availability signal (Implements: ADR-005; REQ-TA-QR-001).

The data layer reports "couldn't serve this" as a **sentinel string**
(``NO_DATA_AVAILABLE`` / ``DATA_UNAVAILABLE``) rather than raising, so a run can
still complete on the data it did get. But a run whose *core* market data was
unavailable must not present a normal, confident recommendation, and its run
record must say so (``run_metadata.failure.code = STOCK_DATA_UNAVAILABLE``).

A plain ``ContextVar[bool]`` set inside a tool does not propagate back to the
graph: LangGraph runs tool nodes in copied contexts, so a value set there is lost
to the caller (verified). Instead the contextvar holds a **mutable holder** bound
once at run start; the tool mutates the shared holder (a mutation of a shared
object survives context copies, unlike a rebind). This mirrors how the budget
tracker is shared.

Not part of the safety-critical data taxonomy; standard-library only.
"""

from __future__ import annotations

from contextvars import ContextVar

# Sentinel prefixes the router returns when no usable data could be served.
NO_DATA_SENTINEL = "NO_DATA_AVAILABLE"
DATA_UNAVAILABLE_SENTINEL = "DATA_UNAVAILABLE"

# Methods whose absence means *core* market data is missing (prices, indicators,
# the verified snapshot). Missing optional enrichment (macro, prediction markets)
# does NOT make the run's core data unavailable.
CORE_MARKET_METHODS = frozenset({"get_stock_data", "get_indicators", "get_verified_market_snapshot"})


class _Signal:
    """A shared per-run holder; tools mutate it, the graph reads it."""

    __slots__ = ("unavailable",)

    def __init__(self) -> None:
        self.unavailable = False


_signal: ContextVar[_Signal | None] = ContextVar("tradingagents_data_signal", default=None)


def _current() -> _Signal:
    """The active run's holder, creating a process-level one if none is bound.

    A holder created on demand (no run scope) still records; the graph binds a
    fresh holder per run so a stale flag never leaks across runs.
    """
    holder = _signal.get()
    if holder is None:
        holder = _Signal()
        _signal.set(holder)
    return holder


def bind() -> _Signal:
    """Bind a fresh holder for the current run and return it (call at run start)."""
    holder = _Signal()
    _signal.set(holder)
    return holder


def is_unavailable_sentinel(text) -> bool:
    """Whether a tool result is the router's "no data / unavailable" sentinel."""
    if not isinstance(text, str):
        return False
    head = text.lstrip()
    return head.startswith(NO_DATA_SENTINEL) or head.startswith(DATA_UNAVAILABLE_SENTINEL)


def note_result(method: str, result) -> None:
    """Record that ``method`` returned an unavailable sentinel for core data."""
    if method in CORE_MARKET_METHODS and is_unavailable_sentinel(result):
        _current().unavailable = True


def mark_unavailable() -> None:
    """Mark the current run's core market data as unavailable."""
    _current().unavailable = True


def reset() -> None:
    """Clear the current run's flag (bind a fresh holder)."""
    bind()


def core_data_unavailable() -> bool:
    """Whether the current run saw unavailable core market data."""
    holder = _signal.get()
    return bool(holder and holder.unavailable)


__all__ = [
    "CORE_MARKET_METHODS",
    "DATA_UNAVAILABLE_SENTINEL",
    "NO_DATA_SENTINEL",
    "bind",
    "core_data_unavailable",
    "is_unavailable_sentinel",
    "mark_unavailable",
    "note_result",
    "reset",
]
