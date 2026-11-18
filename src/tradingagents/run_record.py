"""Canonical, versioned structured run record (Implements: REQ-TA-QR-004).

Every run produces one :class:`RunRecord` describing what produced it and what
happened. The record is the single canonical structured representation of a
run's settings and observability fields; no second, independently maintained
dictionary describes the same run.

The record has two clearly separated top-level sections:

``replayable_settings``
    The safe, allowlisted settings that reproduce the run's *configuration*.
    These never include secrets, endpoints, or local paths. REQ-TA-FR-008 may
    load only this section to re-run an analysis later.

``run_metadata``
    Observational information about what occurred: package version, timestamps,
    completion status, token totals, and call counts. These are never treated as
    replayable inputs.

The record also keeps the historical flat keys (``version``, ``llm_provider``,
``analysts``, ``max_debate_rounds``, ...) for one schema version so existing
report and state-log consumers keep working while the nested structure becomes
canonical (migration strategy C). A later schema version may drop the flat keys.

Field provenance and the allowed/observational/forbidden classification are
documented in the trace matrix row for REQ-TA-QR-004.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The run-record schema version. Bump when the field set or semantics change in
# a way a loader (REQ-TA-FR-008) must tell apart. "1" is the first version: the
# nested replayable_settings/run_metadata split introduced with REQ-TA-QR-004.
RECORD_SCHEMA_VERSION = "1"

# The only completion statuses a run record carries (approved: no new enum).
# A run that reaches the end of the pipeline is ``completed``; a run that ends
# in a controlled failure before completion is ``failed``.
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
RECORD_STATUSES = (STATUS_COMPLETED, STATUS_FAILED)

# The usage-summary keys the record consumes. A caller that measures token usage
# (the CLI's StatsCallbackHandler today) supplies these; the record never counts
# tokens itself, so there is one accounting source of truth.
_USAGE_KEYS = ("tokens_in", "tokens_out", "llm_calls", "tool_calls", "usage_complete")


@dataclass(frozen=True)
class UsageSummary:
    """A measured usage snapshot for one run (REQ-TA-QR-004).

    ``usage_complete`` is true only when every LLM call reported both token
    counts. When it is false, token totals are not presented as complete: the
    per-count fields are kept as reported (or ``None``) and ``total_tokens``
    returns ``None``.
    """

    tokens_in: int | None = None
    tokens_out: int | None = None
    llm_calls: int | None = None
    tool_calls: int | None = None
    usage_complete: bool = False

    @property
    def total_tokens(self) -> int | None:
        """The run's total tokens, or ``None`` when usage is not complete."""
        if not self.usage_complete or self.tokens_in is None or self.tokens_out is None:
            return None
        return self.tokens_in + self.tokens_out

    def to_metadata(self) -> dict[str, Any]:
        """The usage summary as a ``run_metadata`` block.

        Unavailable values are ``None`` (never omitted), matching the approved
        contract: ``usage_complete`` false with null token values. Report
        rendering may show "unavailable" as presentation text.
        """
        return {
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "total_tokens": self.total_tokens,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "usage_complete": self.usage_complete,
        }


@dataclass(frozen=True)
class RunRecord:
    """One run's canonical structured record (REQ-TA-QR-004).

    ``replayable_settings`` and ``run_metadata`` are the two canonical sections.
    ``legacy`` holds the flat keys consumers already read; they are merged into
    :meth:`to_dict` for backward compatibility (migration strategy C).
    """

    replayable_settings: dict[str, Any]
    run_metadata: dict[str, Any]
    legacy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The record as a plain dict: schema version, canonical sections, and
        the legacy flat keys kept for one schema version."""
        out: dict[str, Any] = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "replayable_settings": dict(self.replayable_settings),
            "run_metadata": dict(self.run_metadata),
        }
        # Legacy flat keys, added last so the canonical sections win on any
        # accidental name collision. Consumers migrate off these over time.
        for key, value in self.legacy.items():
            out.setdefault(key, value)
        return out


def build_usage_summary(stats: dict[str, Any] | None) -> UsageSummary:
    """Build a :class:`UsageSummary` from a stats mapping.

    Accepts the ``StatsCallbackHandler.get_stats()`` shape (``tokens_in``,
    ``tokens_out``, ``llm_calls``, ``tool_calls``). ``usage_complete`` is true
    only when both token counts are present and non-negative; a provider that
    reported nothing yields an incomplete summary with null token fields rather
    than a fabricated zero.
    """
    if not stats:
        return UsageSummary()
    tokens_in = stats.get("tokens_in")
    tokens_out = stats.get("tokens_out")
    llm_calls = stats.get("llm_calls")
    tool_calls = stats.get("tool_calls")
    # An explicit ``usage_complete`` (from the budget ledger, REQ-TA-FR-002)
    # takes precedence over the inference below: a ledger knows whether every
    # call reported both counts, so a partial sum is never promoted to complete.
    complete = (
        isinstance(tokens_in, int)
        and isinstance(tokens_out, int)
        and tokens_in >= 0
        and tokens_out >= 0
    )
    if isinstance(stats.get("usage_complete"), bool):
        complete = stats["usage_complete"] and complete
    return UsageSummary(
        tokens_in=tokens_in if isinstance(tokens_in, int) else None,
        tokens_out=tokens_out if isinstance(tokens_out, int) else None,
        llm_calls=llm_calls if isinstance(llm_calls, int) else None,
        tool_calls=tool_calls if isinstance(tool_calls, int) else None,
        usage_complete=complete,
    )


def build_run_record(
    *,
    replayable_settings: dict[str, Any],
    usage: UsageSummary | None = None,
    status: str = STATUS_COMPLETED,
    started_at: str | None = None,
    completed_at: str | None = None,
    version: str | None = None,
    legacy: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
) -> RunRecord:
    """Assemble a :class:`RunRecord` from its parts.

    ``status`` must be one of :data:`RECORD_STATUSES`; any other value is a
    programming error and raises, so a caller cannot invent a status. The
    usage summary contributes only observational fields to ``run_metadata``;
    its values are never copied into ``replayable_settings``.

    ``budget`` (REQ-TA-FR-002; ADR-004) is an optional allowlisted block placed
    under ``run_metadata.budget``. It is a separate dimension from the lifecycle
    ``status`` and never changes it; a run that completed with optional work
    curtailed keeps lifecycle ``completed`` and reports its budget result
    alongside. When omitted, no ``budget`` key is added (backward compatible).
    """
    if status not in RECORD_STATUSES:
        raise ValueError(
            f"run status must be one of {', '.join(RECORD_STATUSES)}, got {status!r}"
        )
    usage = usage or UsageSummary()
    run_metadata: dict[str, Any] = {
        "version": version,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    run_metadata.update(usage.to_metadata())
    if budget is not None:
        run_metadata["budget"] = dict(budget)
    return RunRecord(
        replayable_settings=dict(replayable_settings),
        run_metadata=run_metadata,
        legacy=dict(legacy or {}),
    )
