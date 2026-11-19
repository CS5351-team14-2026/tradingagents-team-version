"""FR004-07 evidence: one missing-price Buy, before and after the change.

Run with a given checkout's ``src`` on the path (see the runner in the test). It
drives the real Portfolio Manager node with a decoded Buy that omits entry_price,
and prints the rating and review reasons the node produced. On the baseline the
reasons key does not exist; that is printed as ``<absent>``.
"""

from __future__ import annotations

import json
import os
import sys

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from tradingagents.agents import schemas
from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager

DECISION = {
    "rating": "Buy", "confidence": "medium",
    "executive_summary": "Enter now.", "investment_thesis": "Breakout.",
    "stop_loss": 90.0,          # entry_price deliberately omitted
}


class _PM(BaseChatModel):
    @property
    def _llm_type(self):
        return "fr004-07"

    def with_structured_output(self, schema, method=None, **kwargs):
        if os.environ.get("FR004_USE_INSTANCE"):
            return RunnableLambda(lambda _p: schemas.PortfolioDecision(
                rating=schemas.PortfolioRating.BUY, confidence="medium",
                executive_summary="s", investment_thesis="t", stop_loss=90.0))
        return RunnableLambda(lambda _p: dict(DECISION))

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="**Rating**: Buy"))])


STATE = {
    "company_of_interest": "NVDA", "past_context": "",
    "risk_debate_state": {
        "history": "h", "aggressive_history": "", "conservative_history": "",
        "neutral_history": "", "current_aggressive_response": "",
        "current_conservative_response": "", "current_neutral_response": "", "count": 1,
    },
    "market_report": "Close 100.", "sentiment_report": "s", "news_report": "n",
    "fundamentals_report": "f", "investment_plan": "p",
    "trader_investment_plan": "Entry 100 / Stop 90",
}


def main() -> int:
    out = create_portfolio_manager(_PM())(dict(STATE))
    print(json.dumps({
        "final_rating": out.get("final_rating"),
        "decision_review_reasons": out.get("decision_review_reasons", "<absent>"),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
