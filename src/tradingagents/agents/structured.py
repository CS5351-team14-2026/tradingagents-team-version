"""Shared helpers for invoking an agent with structured output and a graceful fallback.

The Portfolio Manager, Trader, and Research Manager all follow the same
canonical pattern:

1. At agent creation, wrap the LLM with ``with_structured_output(Schema)``
   so the model returns a typed Pydantic instance. If the provider does
   not support structured output (rare; mostly older Ollama models), the
   wrap is skipped and the agent uses free-text generation instead.
2. At invocation, run the structured call and render the result back to
   markdown. If the structured call itself fails for any reason
   (malformed JSON from a weak model, transient provider issue), fall
   back to a plain ``llm.invoke`` when the run budget admits that retry.

Centralising the pattern here keeps the agent factories small and ensures
all three agents log the same warnings when fallback fires.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from tradingagents.llm_clients.invocation import (
    BudgetInvocationRefused,
    CallSpec,
    invoke_with_budget,
)
from tradingagents.run_budget import BudgetLedgerError, CallRole

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Schema-only structured output binds exactly one tool (the schema itself), so a
# model that reaches for a search tool emits an unknown tool call and the whole
# structured attempt is discarded for a free-text retry. Agents on this path
# state the constraint explicitly rather than relying on the binding alone
# (#1130).
NO_EXTERNAL_TOOLS = (
    "Use only the evidence provided in this prompt. Do not call external tools "
    "or search the web; if something is missing, say so explicitly."
)


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Any | None:
    """Return ``llm.with_structured_output(schema)`` or ``None`` if unsupported.

    Logs a warning when the binding fails so the user understands the agent
    will use free-text generation for every call instead of one-shot fallback.
    """
    try:
        return llm.with_structured_output(schema)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning(
            "%s: provider does not support with_structured_output (%s); "
            "falling back to free-text generation",
            agent_name, exc,
        )
        return None


def invoke_structured(
    structured_llm: Any | None,
    prompt: Any,
    agent_name: str,
    *,
    phase: str | None = None,
    first_role: CallRole = CallRole.REQUIRED,
) -> T | None:
    """Run the structured call, retrying once; ``None`` when it still fails.

    ``prompt`` is whatever the underlying LLM accepts (a string for chat
    invocations, a list of message dicts for chat models that take that
    shape), so a caller can forward the same value to its free-text fallback.
    A budget refusal propagates without starting a later retry or fallback.
    """
    if structured_llm is None:
        return None
    for attempt in range(2):
        try:
            result = invoke_with_budget(
                structured_llm,
                prompt,
                call=CallSpec(
                    phase=phase or agent_name,
                    role=first_role if attempt == 0 else CallRole.OPTIONAL,
                ),
            )
            if result is None:
                # A thinking model can answer in plain text instead of calling
                # the tool, leaving the parser with nothing to return. Treat it
                # as a structured miss and retry, then fall back with a reason.
                raise ValueError("structured output returned no parsed result")
            return result
        except (BudgetInvocationRefused, BudgetLedgerError):
            # A refused optional retry is a control outcome, not a provider
            # error that authorizes another fallback (REQ-TA-FR-002).
            raise
        except Exception as exc:
            if attempt == 0:
                logger.warning(
                    "%s: structured-output invocation failed (%s); retrying the "
                    "structured call once",
                    agent_name, exc,
                )
                continue
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )
            return None
    return None


def invoke_structured_or_freetext(
    structured_llm: Any | None,
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
    *,
    phase: str | None = None,
) -> str:
    """Render a structured result, or admit a free-text fallback after provider failure."""
    result = invoke_structured(structured_llm, prompt, agent_name, phase=phase)
    if result is not None:
        return render(result)
    # An unsupported binding made no request; its plain call is still the
    # required first attempt. After an attempted structured request it is an
    # optional fallback, admitted against the latest recorded usage.
    return invoke_with_budget(
        plain_llm,
        prompt,
        call=CallSpec(
            phase=phase or agent_name,
            role=CallRole.REQUIRED if structured_llm is None else CallRole.OPTIONAL,
        ),
    ).content
