"""Provider usage normalization and a LangChain callback adapter (REQ-TA-FR-002).

Implements: ADR-004; REQ-TA-FR-002; REQ-TA-QR-004.

The single accounting source of truth. LangChain surfaces provider token usage
through ``AIMessage.usage_metadata`` (a standardized ``{input_tokens,
output_tokens, total_tokens}`` mapping) and, for some providers, through
provider-specific raw fields on ``response_metadata``. This module reads those
shapes into a :class:`tradingagents.run_budget.UsageObservation` without ever
estimating: a field the provider did not report stays ``None`` (never zero),
and a value the provider contradicts is marked ``conflict`` rather than guessed.

It also provides :class:`UsageCallbackHandler`, the callback adapter that feeds
a :class:`~tradingagents.run_budget.RunBudgetTracker`. The CLI's
``StatsCallbackHandler`` is a thin adapter over the same handler, so there is
one accounting implementation, not two.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage

from tradingagents.run_budget import (
    USAGE_COMPLETE,
    USAGE_CONFLICT,
    USAGE_PARTIAL,
    USAGE_UNAVAILABLE,
    CallRole,
    UsageObservation,
)

logger = logging.getLogger(__name__)


def _as_count(value: Any) -> int | None:
    """A provider-reported count as a non-negative int, or ``None`` if unusable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _from_usage_metadata(usage: dict[str, Any]) -> UsageObservation | None:
    """A standardized ``usage_metadata`` mapping, or ``None`` when it carries nothing."""
    if not isinstance(usage, dict) or not usage:
        return None
    tokens_in = _as_count(usage.get("input_tokens"))
    tokens_out = _as_count(usage.get("output_tokens"))
    total = _as_count(usage.get("total_tokens"))

    if tokens_in is None and tokens_out is None:
        # A result-level total only (some providers): a lower bound, not a split.
        if total is not None:
            return _partial_total(total)
        return None

    if tokens_in is not None and tokens_out is not None:
        if total is not None and total != tokens_in + tokens_out:
            return UsageObservation(tokens_in=tokens_in, tokens_out=tokens_out, state=USAGE_CONFLICT)
        return UsageObservation(tokens_in=tokens_in, tokens_out=tokens_out, state=USAGE_COMPLETE)

    # Exactly one side reported: a lower bound, never a complete total.
    return UsageObservation(tokens_in=tokens_in, tokens_out=tokens_out, state=USAGE_PARTIAL)


def _partial_total(total: int) -> UsageObservation:
    """A total-only observation as a partial lower bound (kept as input side).

    ``UsageObservation`` has no total field; carrying the known total in one
    side as a lower bound keeps ``known_tokens`` correct without splitting a
    number the provider never split.
    """
    return UsageObservation(tokens_in=total, tokens_out=0, state=USAGE_PARTIAL)


def _from_anthropic(raw: dict[str, Any]) -> UsageObservation | None:
    """Anthropic raw usage: input + cache read/creation, output incl. thinking."""
    if not raw:
        return None
    base_in = _as_count(raw.get("input_tokens"))
    cache_read = _as_count(raw.get("cache_read_input_tokens")) or 0
    cache_creation = _as_count(raw.get("cache_creation_input_tokens")) or 0
    tokens_out = _as_count(raw.get("output_tokens"))
    if base_in is None and tokens_out is None:
        return None
    if base_in is not None:
        base_in = base_in + cache_read + cache_creation
    if base_in is not None and tokens_out is not None:
        return UsageObservation(tokens_in=base_in, tokens_out=tokens_out, state=USAGE_COMPLETE)
    return UsageObservation(tokens_in=base_in, tokens_out=tokens_out, state=USAGE_PARTIAL)


def _from_google(raw: dict[str, Any]) -> UsageObservation | None:
    """Google raw usage: prompt(+tool-use) in, candidate(+thought) out."""
    if not raw:
        return None
    prompt = _as_count(raw.get("prompt_token_count", raw.get("promptTokenCount")))
    tool = _as_count(
        raw.get("tool_use_prompt_token_count", raw.get("toolUsePromptTokenCount"))
    ) or 0
    candidates = _as_count(
        raw.get("candidates_token_count", raw.get("candidatesTokenCount"))
    )
    thoughts = _as_count(
        raw.get("thoughts_token_count", raw.get("thoughtsTokenCount"))
    ) or 0
    tokens_in = prompt + tool if prompt is not None else None
    tokens_out = candidates + thoughts if candidates is not None else None
    if tokens_in is None and tokens_out is None:
        return None
    if tokens_in is not None and tokens_out is not None:
        return UsageObservation(tokens_in=tokens_in, tokens_out=tokens_out, state=USAGE_COMPLETE)
    return UsageObservation(tokens_in=tokens_in, tokens_out=tokens_out, state=USAGE_PARTIAL)


# Where a provider stashes its raw usage dict on ``response_metadata``.
_PROVIDER_RAW_KEYS = ("usage", "token_usage", "usage_metadata")


def _provider_raw(message: AIMessage) -> dict[str, Any] | None:
    meta = getattr(message, "response_metadata", None)
    if not isinstance(meta, dict):
        return None
    for key in _PROVIDER_RAW_KEYS:
        value = meta.get(key)
        if isinstance(value, dict):
            return value
    return None


def normalize_usage(response: Any, *, provider: str | None = None) -> UsageObservation:
    """Normalize one LLM response to a usage observation; unknown stays unknown.

    Reads the first generation's message ``usage_metadata`` (standardized) and,
    failing that, the provider-specific raw shape keyed by ``provider`` (with a
    shape-sniffing fallback). Missing or invalid usage yields ``unavailable``;
    never an estimate, never a fabricated zero.
    """
    message = _first_message(response)
    if message is None:
        return UsageObservation(state=USAGE_UNAVAILABLE)

    standardized = getattr(message, "usage_metadata", None)
    if isinstance(standardized, dict) and standardized:
        obs = _from_usage_metadata(standardized)
        if obs is not None:
            return obs

    raw = _provider_raw(message)
    if raw is not None:
        provider_lc = (provider or "").lower()
        if provider_lc == "anthropic" or "cache_read_input_tokens" in raw:
            obs = _from_anthropic(raw)
            if obs is not None:
                return obs
        if provider_lc == "google" or "prompt_token_count" in raw or "promptTokenCount" in raw:
            obs = _from_google(raw)
            if obs is not None:
                return obs

    return UsageObservation(state=USAGE_UNAVAILABLE)


def _first_message(response: Any) -> AIMessage | None:
    """The first generation's ``AIMessage``, from a LangChain chat/LLM result."""
    try:
        generation = response.generations[0][0]
    except (AttributeError, IndexError, TypeError):
        return None
    message = getattr(generation, "message", None)
    return message if isinstance(message, AIMessage) else None


class UsageCallbackHandler(BaseCallbackHandler):
    """Feeds a run's ledger from LangChain LLM lifecycle callbacks (ADR-004).

    ``on_llm_start``/``on_chat_model_start`` register the call (attributable to
    the run that started it); ``on_llm_end`` records its normalized usage;
    ``on_llm_error`` marks it ended without a usable observation. Each event is
    keyed by the LangChain ``run_id`` so duplicate deliveries replace rather
    than add.
    """

    def __init__(self, tracker: Any | None = None, *, provider: str | None = None):
        super().__init__()
        self._tracker = tracker
        self._provider = provider

    @property
    def tracker(self):
        return self._tracker

    def set_tracker(self, tracker) -> None:
        self._tracker = tracker

    def _register(self, run_id: Any) -> None:
        if self._tracker is None or run_id is None:
            return
        call_id = str(run_id)
        # Observation-only registration: the invocation boundary fills role and
        # phase when admission is active; here nothing is admitted.
        self._tracker.start_call(call_id, role=CallRole.REQUIRED, phase="observed")

    def on_llm_start(self, serialized, prompts, *, run_id=None, **kwargs) -> None:
        self._register(run_id)

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs) -> None:
        self._register(run_id)

    def on_llm_end(self, response, *, run_id=None, **kwargs) -> None:
        if self._tracker is None:
            return
        observation = normalize_usage(response, provider=self._provider)
        self._tracker.finish_call(str(run_id), observation)

    def on_llm_error(self, error, *, run_id=None, **kwargs) -> None:
        if self._tracker is None:
            return
        self._tracker.fail_call(str(run_id))

    def on_tool_start(self, serialized, input_str, *, run_id=None, **kwargs) -> None:
        if self._tracker is not None:
            self._tracker.record_tool(str(run_id) if run_id is not None else None)


__all__ = ["UsageCallbackHandler", "normalize_usage"]
