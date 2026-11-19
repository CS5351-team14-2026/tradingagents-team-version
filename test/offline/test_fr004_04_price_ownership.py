"""FR004-04: the validator reads only the final structured decision's prices.

Approved test plan: Issue #32 (``test-approved``) FR004-04.
Implements: REQ-TA-FR-004.

A final Buy that omits a price is REVIEW with the matching ``missing_*`` code,
even when a compatible price sits in the Trader's proposal, an analyst report or
the decision prose. Upstream values are never used to fill a final field. The
only thing replaced is the model response boundary; the node, the validator and
the retry/fallback order all run for real.
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager

# A compatible price, placed everywhere a validator might be tempted to borrow
# from. None of it may reach the final decision's price fields.
BORROWABLE = 100.0


class _PM(BaseChatModel):
    """A schema bridge that answers the PM with a chosen final decision."""

    decision: dict
    calls: list = []

    @property
    def _llm_type(self) -> str:
        return "fr004-04"

    def with_structured_output(self, schema, method=None, **kwargs):
        return RunnableLambda(lambda _p: (self.calls.append(1) or dict(self.decision)))

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append("plain")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content=f"**Rating**: Buy\n\nBuy at {BORROWABLE} with a stop at 90."))])


def _state(**overrides):
    """A PM state whose upstream context carries compatible prices."""
    state = {
        "company_of_interest": "NVDA",
        "past_context": "",
        "risk_debate_state": {
            "history": "Risk debate history.",
            "aggressive_history": "", "conservative_history": "", "neutral_history": "",
            "current_aggressive_response": "", "current_conservative_response": "",
            "current_neutral_response": "", "count": 1,
        },
        "market_report": f"Close was {BORROWABLE}; support at 90.",
        "sentiment_report": "Sentiment report.",
        "news_report": "News report.",
        "fundamentals_report": "Fundamentals report.",
        "investment_plan": "Research plan.",
        # The Trader proposal carries a compatible price and stop.
        "trader_investment_plan": (
            f"**Action**: Buy\n**Entry Price**: {BORROWABLE}\n**Stop Loss**: 90.0\n"
            "FINAL TRANSACTION PROPOSAL: **BUY**"),
    }
    state.update(overrides)
    return state


def _run(decision, **state_overrides):
    model = _PM(decision=decision, calls=[])
    return model, create_portfolio_manager(model)(_state(**state_overrides))


def _buy(**price_fields):
    return {"rating": "Buy", "confidence": "medium",
            "executive_summary": "s", "investment_thesis": "t", **price_fields}


@pytest.mark.unit
def test_a_missing_entry_is_not_filled_from_the_trader_proposal():
    """REQ-TA-FR-004 (FR004-04): the final Buy omits entry_price; the Trader's
    proposal has one, but the decision is REVIEW with missing_entry_price."""
    model, out = _run(_buy(stop_loss=90.0))
    assert out["final_rating"] == "REVIEW"
    assert out["decision_review_reasons"] == ["missing_entry_price"]
    assert model.calls == [1], "no retry or fallback borrows a price"


@pytest.mark.unit
def test_a_missing_stop_is_not_filled_from_the_analyst_report():
    """REQ-TA-FR-004 (FR004-04): the analyst report names a support level; the
    final Buy's missing stop is still a missing_stop_loss REVIEW."""
    model, out = _run(_buy(entry_price=100.0))
    assert out["final_rating"] == "REVIEW"
    assert out["decision_review_reasons"] == ["missing_stop_loss"]
    assert model.calls == [1]


@pytest.mark.unit
def test_both_missing_is_not_filled_from_prose():
    """REQ-TA-FR-004 (FR004-04): neither price is given, and the surrounding
    prose has both; the final decision is REVIEW with both missing codes."""
    model, out = _run(_buy())
    assert out["final_rating"] == "REVIEW"
    assert out["decision_review_reasons"] == ["missing_entry_price", "missing_stop_loss"]
    assert model.calls == [1]


@pytest.mark.unit
def test_an_explicitly_null_price_is_missing_not_borrowed():
    """REQ-TA-FR-004 (FR004-04): a null price is "not given", not "borrow it"."""
    model, out = _run(_buy(entry_price=None, stop_loss=None))
    assert out["decision_review_reasons"] == ["missing_entry_price", "missing_stop_loss"]
    assert model.calls == [1]


@pytest.mark.unit
def test_a_valid_final_field_is_kept_and_the_missing_one_is_reported():
    """REQ-TA-FR-004 (FR004-04): the final decision supplies a valid stop; only
    the absent entry is a missing_entry_price REVIEW, and nothing else is used."""
    _, out = _run(_buy(stop_loss=90.0))
    assert out["final_rating"] == "REVIEW"
    assert out["decision_review_reasons"] == ["missing_entry_price"]
