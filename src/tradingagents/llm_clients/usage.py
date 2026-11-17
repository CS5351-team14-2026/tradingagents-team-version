"""Provider usage observations and callbacks (REQ-TA-FR-002; REQ-TA-QR-004).

Implements ADR-003: callbacks observe calls; they never enforce a budget by
raising from a callback. Only allowlisted token fields enter the shared ledger.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler

from tradingagents.run_budget import (
    RunBudgetTracker,
    UsageObservation,
    current_run_context,
)

_COUNTS = {
    "tokens_in": ("input_tokens", "prompt_tokens", "inputTokens"),
    "tokens_out": ("output_tokens", "completion_tokens", "outputTokens"),
    "total_tokens": ("total_tokens", "totalTokens"),
}


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _counts(data: Any, source: str) -> UsageObservation:
    """Read reported fields without coercing, estimating, or assuming zero."""
    if not isinstance(data, Mapping):
        return UsageObservation()
    counts = {}
    conflict = False
    present = False
    for field, aliases in _COUNTS.items():
        values = []
        for alias in aliases:
            if alias not in data:
                continue
            present = True
            value = data[alias]
            if value is None:
                continue
            if not _count(value):
                conflict = True
                continue
            values.append(value)
        if len(set(values)) > 1:
            conflict = True
            counts[field] = None
        else:
            counts[field] = values[0] if values else None
    if not present:
        return UsageObservation()
    tokens_in, tokens_out, total = (counts[key] for key in _COUNTS)
    if tokens_in is not None and tokens_out is not None:
        if total is not None and total != tokens_in + tokens_out:
            conflict = True
            counts["total_tokens"] = None
        elif total is None:
            counts["total_tokens"] = tokens_in + tokens_out
    elif total is not None and any(value is not None and value > total
                                   for value in (tokens_in, tokens_out)):
        conflict = True
        counts["total_tokens"] = None
    state = (
        "conflict" if conflict else
        "complete" if tokens_in is not None and tokens_out is not None else
        "partial" if any(value is not None for value in counts.values()) else
        "unavailable"
    )
    return UsageObservation(**counts, state=state, source=source)


def _merge_reports(reports: Sequence[UsageObservation]) -> UsageObservation:
    """Corroborate reports of the same usage; never add them together."""
    available = [report for report in reports if report.state != "unavailable"]
    if not available:
        return UsageObservation()
    counts = {}
    conflict = any(report.state == "conflict" for report in available)
    for field in _COUNTS:
        values = {getattr(report, field) for report in available
                  if getattr(report, field) is not None}
        if len(values) > 1:
            conflict = True
            counts[field] = None
        else:
            counts[field] = next(iter(values)) if values else None
    tokens_in, tokens_out, total = (counts[key] for key in _COUNTS)
    complete = any(report.state == "complete" for report in available)
    if tokens_in is not None and tokens_out is not None:
        if total is not None and (
            tokens_in + tokens_out > total or (complete and total != tokens_in + tokens_out)
        ):
            conflict = True
            counts["total_tokens"] = None
        elif total is None:
            counts["total_tokens"] = tokens_in + tokens_out
    state = ("conflict" if conflict else
             "complete" if complete else
             "partial")
    return UsageObservation(**counts, state=state, source=available[0].source)


def _native_provider(data: Any, provider: str | None) -> str | None:
    if not isinstance(data, Mapping):
        return None
    if provider in {"anthropic", "google", "google_genai"}:
        return "google" if provider != "anthropic" else provider
    if any(key in data for key in ("cache_read_input_tokens", "cache_creation_input_tokens", "cache_creation")):
        return "anthropic"
    if any(key in data for key in ("promptTokenCount", "prompt_token_count", "candidatesTokenCount", "candidates_token_count")):
        return "google"
    return None


def _native_counts(data: Mapping, source: str, native: str) -> UsageObservation:
    """Normalize only published, complete decompositions verified against SDKs.

    Anthropic cached input is additional to base input; Google tool prompts and
    thoughts are additional to prompt/candidate counts. Missing additive fields
    remain unknown. Cache/reasoning details that are subsets are not added.
    """
    invalid = False

    def value(*aliases):
        nonlocal invalid
        values = [data[key] for key in aliases if key in data and data[key] is not None]
        if any(not _count(item) for item in values) or len(set(values)) > 1:
            invalid = True
            return None
        return values[0] if values else None

    def add_if_complete(*parts):
        return sum(parts) if all(part is not None for part in parts) else None

    total = value("total_tokens", "totalTokenCount", "total_token_count")
    if native == "anthropic":
        creation = value("cache_creation_input_tokens")
        details = data.get("cache_creation")
        if isinstance(details, Mapping):
            detail_values = [details.get(key) for key in
                             ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")]
            if any(item is not None and not _count(item) for item in detail_values):
                invalid = True
            if all(_count(item) for item in detail_values):
                specific = sum(detail_values)
                if creation is not None and creation != specific:
                    invalid = True
                creation = specific
            elif creation is not None:
                detail_floor = sum(item for item in detail_values if _count(item))
                if detail_floor > creation:
                    invalid = True
        tokens_in = add_if_complete(value("input_tokens"), value("cache_read_input_tokens"), creation)
        tokens_out = value("output_tokens")
    else:
        tokens_in = add_if_complete(value("promptTokenCount", "prompt_token_count"),
                                   value("toolUsePromptTokenCount", "tool_use_prompt_token_count"))
        tokens_out = add_if_complete(value("candidatesTokenCount", "candidates_token_count"),
                                    value("thoughtsTokenCount", "thoughts_token_count"))
    if tokens_in is not None and tokens_out is not None:
        if total is not None and total != tokens_in + tokens_out:
            invalid = True
        elif total is None:
            total = tokens_in + tokens_out
    if total is not None and any(item is not None and item > total for item in (tokens_in, tokens_out)):
        invalid = True
    state = ("conflict" if invalid else
             "complete" if tokens_in is not None and tokens_out is not None else
             "partial" if any(item is not None for item in (tokens_in, tokens_out, total)) else
             "unavailable")
    return UsageObservation(tokens_in, tokens_out, total, state, source)


def _raw_counts(data: Any, source: str, provider: str | None) -> UsageObservation:
    if not isinstance(data, Mapping):
        return UsageObservation()
    native = _native_provider(data, provider)
    return _native_counts(data, source, native) if native else _counts(data, source)


def _metadata_reports(data: Any, source: str, provider: str | None) -> list[UsageObservation]:
    if not isinstance(data, Mapping):
        return []
    # Known wrappers only: do not traverse response bodies or arbitrary keys.
    reports = []
    for key in ("token_usage", "usage", "usage_metadata", "usageMetadata"):
        wrapped = data.get(key)
        # A standardized usage_metadata wrapper is already canonical, even
        # when the caller names a provider whose native counts differ.
        canonical = (key == "usage_metadata" and isinstance(wrapped, Mapping)
                     and any(field in wrapped for field in ("input_tokens", "output_tokens", "total_tokens"))
                     and _native_provider(wrapped, None) is None)
        reports.append(_counts(wrapped, f"{source}.{key}") if canonical else
                       _raw_counts(wrapped, f"{source}.{key}", provider))
    return [*reports, _raw_counts(data, source, provider)]


def _raw_present(data: Any) -> bool:
    return isinstance(data, Mapping) and any(
        key in data and isinstance(data[key], Mapping)
        for key in ("token_usage", "usage", "usage_metadata", "usageMetadata")
    )


def _native_metadata(data: Any, provider: str | None) -> bool:
    return isinstance(data, Mapping) and (
        _native_provider(data, provider) is not None or any(
            _native_provider(data.get(key), provider) is not None
            for key in ("token_usage", "usage", "usage_metadata", "usageMetadata")
        )
    )


def _reconcile(canonical: UsageObservation, raw: UsageObservation, *, native: bool,
               raw_present: bool) -> UsageObservation:
    if canonical.state == "unavailable":
        return raw
    if native and canonical.state == "complete":
        # Native partial decompositions do not have the same field semantics as
        # canonical counts. Compare only the exact canonical fields we recovered.
        return _merge_reports([canonical, raw]) if raw.state != "unavailable" else canonical
    if raw_present and raw.state != "complete":
        # The OpenAI SDK can synthesize zero for omitted fields. Published raw
        # absence/partial evidence must not become complete through those zeros.
        if raw.state == "unavailable":
            return raw
        corroborated = _merge_reports([canonical, raw])
        return corroborated if corroborated.state == "conflict" else raw
    return _merge_reports([canonical, raw])


def _message_usage(message: Any, provider: str | None) -> UsageObservation:
    metadata = getattr(message, "response_metadata", None)
    raw = _merge_reports(_metadata_reports(metadata, "response_metadata", provider))
    return _reconcile(
        _counts(getattr(message, "usage_metadata", None), "usage_metadata"), raw,
        native=_native_metadata(metadata, provider), raw_present=_raw_present(metadata),
    )


def _batch_usage(reports: Sequence[UsageObservation]) -> UsageObservation:
    """Sum distinct prompt groups, retaining partial counts as lower bounds."""
    if not reports or all(report.state == "unavailable" for report in reports):
        return UsageObservation()
    if len(reports) == 1:
        return reports[0]
    counts = {}
    for field in ("tokens_in", "tokens_out"):
        values = [getattr(report, field) for report in reports
                  if getattr(report, field) is not None]
        counts[field] = sum(values) if values else None
    # Each prompt can have different missing fields. Sum its reported lower
    # bound, rather than summing only the prompts that published a full total.
    # The fixed source marker distinguishes this partial aggregate floor from
    # an exact provider total when a later callback supplies richer metadata.
    known = [report.known_tokens for report in reports if report.known_tokens is not None]
    counts["total_tokens"] = sum(known) if known else None
    state = ("conflict" if any(report.state == "conflict" for report in reports) else
             "complete" if all(report.state == "complete" for report in reports) else
             "partial")
    source = "generations_lower_bound" if state == "partial" else "generations"
    return UsageObservation(**counts, state=state, source=source)


def normalize_usage(response: Any, *, provider: str | None = None) -> UsageObservation:
    """Normalize published usage (REQ-TA-FR-002), without provider estimates.

    LLMResult-level usage describes the entire result and is counted once.
    Within one prompt group, alternate generations can repeat the same request
    usage; corroborate those reports rather than multiplying them. Distinct
    prompt groups are additive. A missing prompt group's usage remains partial.
    ``provider`` identifies native additive semantics, never persisted. Native
    raw-only input/output is partial when additive cache/tool/thought fields are
    absent; published exact total is retained. Standardized metadata is preferred.
    """
    provider = provider.lower() if isinstance(provider, str) else None
    aggregate_data = getattr(response, "llm_output", None)
    aggregate = _merge_reports(_metadata_reports(aggregate_data, "llm_output", provider))
    if isinstance(response, Mapping):
        aggregate = _merge_reports([aggregate, *_metadata_reports(response, "response", provider)])
        aggregate_data = response
    generations = getattr(response, "generations", None)
    if isinstance(generations, (list, tuple)):
        per_prompt = []
        for group in generations:
            if not isinstance(group, (list, tuple)):
                per_prompt.append(UsageObservation())
                continue
            per_prompt.append(_merge_reports([
                _message_usage(getattr(generation, "message", None), provider)
                for generation in group
            ]))
        messages = _batch_usage(per_prompt)
    else:
        messages = _message_usage(response, provider)
    # A partial multi-prompt batch is a lower bound of aggregate usage. A
    # single prompt's reported fields are exact and must corroborate strictly.
    if aggregate.state != "unavailable" and messages.source == "generations_lower_bound":
        contradictory = any(
            getattr(aggregate, field) is not None
            and getattr(messages, field) is not None
            and getattr(messages, field) > getattr(aggregate, field)
            for field in ("tokens_in", "tokens_out")
        )
        if (aggregate.total_tokens is not None and messages.known_tokens is not None
                and messages.known_tokens > aggregate.total_tokens):
            contradictory = True
        if contradictory:
            return UsageObservation(
                tokens_in=aggregate.tokens_in, tokens_out=aggregate.tokens_out,
                total_tokens=aggregate.total_tokens, state="conflict", source=aggregate.source,
            )
        if aggregate.state != "partial" or aggregate.total_tokens is not None:
            return aggregate
        # An incomplete aggregate can omit usage already reported by the batch.
        # Both describe the same request set, so take their strongest compatible
        # floor instead of adding overlapping observations together.
        tokens_in = aggregate.tokens_in if aggregate.tokens_in is not None else messages.tokens_in
        tokens_out = aggregate.tokens_out if aggregate.tokens_out is not None else messages.tokens_out
        component_floor = sum(value for value in (tokens_in, tokens_out) if value is not None)
        known = [value for value in (aggregate.known_tokens, messages.known_tokens)
                 if value is not None]
        floor = max([*known, component_floor])
        return UsageObservation(
            tokens_in=tokens_in, tokens_out=tokens_out, total_tokens=floor,
            state="partial", source="generations_lower_bound",
        )
    return _reconcile(messages, aggregate, native=_native_metadata(aggregate_data, provider),
                      raw_present=_raw_present(aggregate_data))


class UsageCallbackHandler(BaseCallbackHandler):
    """Observe a single shared run ledger (ADR-003; FR-002; QR-004).

    Callback run IDs own their tracker from start to end, so an asynchronous
    completion cannot enter whichever analysis happens to be active later.
    The standalone tracker supports users of the historical CLI stats handler.
    """

    def __init__(self, tracker: RunBudgetTracker | None = None, *, provider: str | None = None):
        super().__init__()
        self._fallback = tracker if tracker is not None else RunBudgetTracker()
        self._last_tracker = self._fallback
        self._provider = provider
        self._lock = threading.RLock()
        self._owners: dict[str, RunBudgetTracker] = {}
        self._call_ids: dict[str, str] = {}
        self._providers: dict[str, str | None] = {}
        self._anonymous_calls: deque[str] = deque()

    @property
    def tracker(self) -> RunBudgetTracker:
        """The active run's ledger, or the last ledger observed by this handler."""
        context = current_run_context()
        return context.tracker if context is not None else self._last_tracker

    def _owner(self, run_id: Any, *, starting: bool = False, metadata: Any = None) -> tuple[str, RunBudgetTracker]:
        with self._lock:
            if run_id is None:
                if starting or not self._anonymous_calls:
                    key = f"anonymous:{uuid4()}"
                    if starting:
                        self._anonymous_calls.append(key)
                else:
                    key = self._anonymous_calls.popleft()
            else:
                key = str(run_id)
            owner = self._owners.get(key)
            if owner is None:
                owner = self.tracker
                self._owners[key] = owner
                self._last_tracker = owner
                logical_id = metadata.get("ta_budget_call_id") if isinstance(metadata, Mapping) else None
                if isinstance(logical_id, str) and logical_id:
                    self._call_ids[key] = logical_id
            return self._call_ids.get(key, key), owner

    def _remember_provider(self, key: str, serialized: Any, metadata: Any) -> None:
        # LangChain adds ls_provider to call metadata. Keep only the provider
        # label, never serialized constructor data or arbitrary metadata.
        provider = metadata.get("ls_provider") if isinstance(metadata, Mapping) else None
        allowed = {"anthropic", "google", "google_genai", "openai", "azure", "bedrock"}
        if (not isinstance(provider, str) or provider not in allowed) and isinstance(serialized, Mapping):
            model_id = serialized.get("id")
            model_type = model_id[-1] if isinstance(model_id, (list, tuple)) and model_id else None
            provider = {
                "ChatAnthropic": "anthropic", "ChatGoogleGenerativeAI": "google",
                "ChatOpenAI": "openai", "AzureChatOpenAI": "azure",
                "ChatBedrock": "bedrock", "ChatBedrockConverse": "bedrock",
            }.get(model_type) if isinstance(model_type, str) else None
        with self._lock:
            self._providers.setdefault(
                key, provider if isinstance(provider, str) and provider in allowed else self._provider,
            )

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any) -> None:
        """Record an observed start; optional-call admission belongs outside callbacks."""
        key, owner = self._owner(kwargs.get("run_id"), starting=True, metadata=kwargs.get("metadata"))
        self._remember_provider(key, serialized, kwargs.get("metadata"))
        owner.start_call(key)

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], **kwargs: Any) -> None:
        key, owner = self._owner(kwargs.get("run_id"), starting=True, metadata=kwargs.get("metadata"))
        self._remember_provider(key, serialized, kwargs.get("metadata"))
        owner.start_call(key)

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        key, owner = self._owner(kwargs.get("run_id"))
        owner.start_call(key)
        owner.finish_call(key, normalize_usage(response, provider=self._providers.get(key, self._provider)))

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        key, owner = self._owner(kwargs.get("run_id"))
        owner.start_call(key)
        owner.fail_call(key)

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs: Any) -> None:
        # Tool IDs are separate from model IDs and never contribute token usage.
        key = str(kwargs.get("run_id") or f"anonymous-tool:{uuid4()}")
        with self._lock:
            owner = self._owners.get(f"tool:{key}")
            if owner is None:
                owner = self.tracker
                self._owners[f"tool:{key}"] = owner
                self._last_tracker = owner
        owner.record_tool(key)

    def get_stats(self) -> dict[str, Any]:
        """Return legacy stats keys plus explicit completeness (REQ-TA-QR-004)."""
        return self.tracker.snapshot().to_stats()

    @property
    def tokens_in(self) -> int | None:
        return self.get_stats()["tokens_in"]

    @property
    def tokens_out(self) -> int | None:
        return self.get_stats()["tokens_out"]

    @property
    def llm_calls(self) -> int:
        return self.get_stats()["llm_calls"]

    @property
    def tool_calls(self) -> int:
        return self.get_stats()["tool_calls"]
