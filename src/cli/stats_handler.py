"""CLI statistics: one accounting source over the shared usage ledger (REQ-TA-FR-002).

Implements: ADR-004; REQ-TA-FR-002; REQ-TA-QR-004.

``StatsCallbackHandler`` is the CLI's window onto a run's usage. It no longer
keeps its own token accumulator: it owns a
:class:`~tradingagents.run_budget.RunBudgetTracker` and delegates LLM/tool
observation to :class:`~tradingagents.llm_clients.usage.UsageCallbackHandler`,
so the CLI path and the graph share one accounting implementation. The tracker
is exposed as ``.tracker`` for the graph's observation scope and the budget
result.

``get_stats()`` keeps the shape the CLI display and run record already read
(``tokens_in``/``tokens_out``/``llm_calls``/``tool_calls``), and adds
``usage_complete`` so a partial or unavailable report is never mistaken for a
complete total (ADR-004 D2).
"""

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from tradingagents.llm_clients.usage import UsageCallbackHandler
from tradingagents.run_budget import RunBudgetTracker


class StatsCallbackHandler(BaseCallbackHandler):
    """Tracks LLM calls, tool calls, and token usage for one run.

    Observation is delegated to a shared ``UsageCallbackHandler`` over this
    handler's ``RunBudgetTracker``; the tracker is the single ledger both the
    CLI and the graph read.
    """

    def __init__(self, tracker: RunBudgetTracker | None = None) -> None:
        super().__init__()
        self.tracker = tracker or RunBudgetTracker()
        self._usage = UsageCallbackHandler(self.tracker)

    # LangChain dispatches these to every handler. Forwarding keeps this
    # handler's callbacks consistent with a bare UsageCallbackHandler.
    def on_llm_start(self, serialized, prompts, *, run_id=None, **kwargs: Any) -> None:
        self._usage.on_llm_start(serialized, prompts, run_id=run_id, **kwargs)

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs: Any) -> None:
        self._usage.on_chat_model_start(serialized, messages, run_id=run_id, **kwargs)

    def on_llm_end(self, response, *, run_id=None, **kwargs: Any) -> None:
        self._usage.on_llm_end(response, run_id=run_id, **kwargs)

    def on_llm_error(self, error, *, run_id=None, **kwargs: Any) -> None:
        self._usage.on_llm_error(error, run_id=run_id, **kwargs)

    def on_tool_start(self, serialized, input_str, *, run_id=None, **kwargs: Any) -> None:
        self._usage.on_tool_start(serialized, input_str, run_id=run_id, **kwargs)

    def get_stats(self) -> dict[str, Any]:
        """Current usage as the CLI display and run record read it.

        Token totals are the summed reported counts; completeness is reported
        separately so a partial or unavailable total is never presented as a
        complete one. Before any call, counts are zero and usage is not yet
        complete (an empty run reported nothing).
        """
        snap = self.tracker.snapshot()
        return {
            "llm_calls": snap.llm_calls,
            "tool_calls": snap.tool_calls,
            "tokens_in": snap.tokens_in or 0,
            "tokens_out": snap.tokens_out or 0,
            "total_tokens": snap.total_tokens,
            "known_tokens": snap.known_tokens,
            "usage_complete": snap.usage_complete,
            "budget": snap.to_metadata(),
        }
