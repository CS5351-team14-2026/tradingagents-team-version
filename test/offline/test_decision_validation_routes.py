"""FR-004 route tests: a price the model wrote is validated before it is adopted.

Approved test plan: Issue #32 (``test-approved``), cases FR004-03 and FR004-05.
Implements: REQ-TA-FR-004; REQ-TA-FR-002; REQ-TA-INV-001.

These drive the *real* Portfolio Manager node with the *real* bindings and the
real retry/fallback order. Only the model response boundary is replaced, so
``bind_structured``, the ``json_mode`` retry, the budget admission gates and the
node wiring all execute as in a run.

Two kinds of route test are here on purpose:

- **binding-level** (``_RouteModel``): the bridge answers with the payload shape
  a provider returns (raw mapping, raw JSON text, validated instance). These pin
  which binding ran, which is how the no-retry rule is observed.
- **parse-level** (``_TextModel``): the bridge hands back raw text, so the
  project's own parsing code (``PortfolioDecision.model_validate_json`` /
  ``model_validate``) runs unmodified. These pin what the parser must be able to
  see, without requiring ``PortfolioDecision`` itself to hold an illegal string.

Stage 1 of the plan: this file is written before the validator exists. Tests
that need it fail with the missing ``decision_review_reasons`` key (or the
model's own unbuilt field), never with a collection error: nothing imports the
unbuilt validator at module scope.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating
from tradingagents.llm_clients.invocation import admit_optional
from tradingagents.run_budget import (
    REASON_RECORDED_USAGE_REACHED_LIMIT,
    CallRole,
    RunBudgetContext,
    RunBudgetTracker,
    StartDecision,
)

# A PM answer the model wrote. ``"15%"`` is a price: the contract says it is
# *invalid* (never a silent null-out that would read as "missing").
INVALID_PRICE = "15%"
VALID_STOP = 172.0

DECISION_FIELDS = {
    "rating": "Buy",
    "confidence": "medium",
    "executive_summary": "Enter on the breakout confirmation.",
    "investment_thesis": "Volume and guidance both support the move.",
}

# The required price for a Buy, as the contract will require it.
REQUIRED_PRICES = {"entry_price": 100.0, "stop_loss": VALID_STOP}


def _mapping(**overrides) -> dict:
    return {**DECISION_FIELDS, **REQUIRED_PRICES, **overrides}


PM_STATE = {
    "company_of_interest": "NVDA",
    "past_context": "",
    "risk_debate_state": {
        "history": "Risk debate history.",
        "aggressive_history": "",
        "conservative_history": "",
        "neutral_history": "",
        "current_aggressive_response": "",
        "current_conservative_response": "",
        "current_neutral_response": "",
        "count": 1,
    },
    "market_report": "Market report.",
    "sentiment_report": "Sentiment report.",
    "news_report": "News report.",
    "fundamentals_report": "Fundamentals report.",
    "investment_plan": "Research plan.",
    "trader_investment_plan": "Trader plan.",
}


class _Calls(BaseChatModel):
    """Records which binding ran, in order: ``schema``/``json``/``plain``."""

    schema_calls: list = Field(default_factory=list)
    json_calls: list = Field(default_factory=list)
    plain_calls: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "route-scripted"

    @property
    def route(self) -> list[str]:
        return (
            ["schema"] * len(self.schema_calls)
            + ["json"] * len(self.json_calls)
            + ["plain"] * len(self.plain_calls)
        )


def _answer(calls: list, replies: list, prompt):
    calls.append(1)
    if not replies:
        raise ValueError("scripted bridge ran out of replies")
    reply = replies.pop(0)
    if reply == "raise":
        raise ValueError("function calling failed")
    return reply


class _RouteModel(_Calls):
    """Answers each binding with a scripted payload.

    ``schema_replies`` answers ``with_structured_output(schema)`` and
    ``json_replies`` the ``method="json_mode"`` retry, consumed in order.
    """

    schema_replies: tuple = ()
    json_replies: tuple = ()
    plain_reply: str = "**Rating**: Buy"

    def with_structured_output(self, schema, method=None, **kwargs):
        if method == "json_mode":
            return RunnableLambda(lambda p: _answer(self.json_calls, self._json, p))
        return RunnableLambda(lambda p: _answer(self.schema_calls, self._schema, p))

    def __init__(self, **data):
        super().__init__(**data)
        self._schema = list(self.schema_replies)
        self._json = list(self.json_replies)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.plain_calls.append(1)
        if self.plain_reply == "raise":
            raise ValueError("plain call failed")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.plain_reply))])


class _TextModel(_Calls):
    """Hands raw text to the project's own parser at each binding.

    The schema binding is a plain pass-through (whatever the project does with
    the return value is what is tested), and the JSON binding is left to the
    project, which calls ``PortfolioDecision.model_validate_json`` on the text.
    """

    schema_text: str = "raise"
    json_text: str = "raise"
    plain_reply: str = "**Rating**: Buy"

    def with_structured_output(self, schema, method=None, **kwargs):
        target = self.json_calls if method == "json_mode" else self.schema_calls
        text = self.json_text if method == "json_mode" else self.schema_text
        return RunnableLambda(lambda p: _answer(target, [text], p))

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.plain_calls.append(1)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.plain_reply))])


def _run(model, *, budget=None):
    """Drive the real node, with an optional real budget context bound."""
    node = create_portfolio_manager(model)
    if budget is None:
        return node(dict(PM_STATE))
    with RunBudgetContext(budget).activate():
        return node(dict(PM_STATE))


def _reasons(result) -> list[str]:
    """The review reasons a validated run must publish (FR-004)."""
    assert "decision_review_reasons" in result, (
        "REQ-TA-FR-004: the PM node must publish decision_review_reasons; "
        f"got keys {sorted(result)}"
    )
    return result["decision_review_reasons"]


class _ExhaustOnCallBudget(RunBudgetTracker):
    """A tracker that is available for the first N optional admissions, then spent.

    The PM node charges its calls through the callback handler, not through
    ``admit_optional``, so a test cannot spend the budget by ordering scripted
    replies alone. Recording usage up front would also stop the *structured
    retry* (``invoke_structured`` asks ``admit_optional("retry")`` before its
    second attempt) and the route would never reach the JSON bridge.

    To exhaust the budget *after* the structured retry and *before* the
    free-text fallback, this subclass admits a fixed number of optional calls
    and refuses every later one. That is the same admission decision the real
    ledger makes once recorded usage meets the limit; only the trigger differs,
    and the helper says so.
    """

    admit_optional_calls: int = 1

    def try_start(self, *, call_id, role, phase):
        if CallRole(role) is CallRole.OPTIONAL:
            if self.admit_optional_calls <= 0:
                return StartDecision(
                    allowed=False,
                    reason_codes=(REASON_RECORDED_USAGE_REACHED_LIMIT,),
                )
            self.admit_optional_calls -= 1
        return super().try_start(call_id=call_id, role=role, phase=phase)


def _exhaust_after_optional(calls: int) -> _ExhaustOnCallBudget:
    """A real tracker that admits ``calls`` optional admissions, then refuses."""
    tracker = _ExhaustOnCallBudget(limit=100)
    tracker.admit_optional_calls = calls
    return tracker


# ---------------------------------------------------------------------------
# FR004-05 (1): the first structured answer decodes and its price is invalid.
# REVIEW with invalid_entry_price; no JSON retry, no free text.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_structured_invalid_price_is_review_without_a_retry():
    """REQ-TA-FR-004 (Issue #32 FR004-03/05): the structured answer carries
    ``entry_price="15%"``, so the decision is REVIEW with
    ``invalid_entry_price`` and neither later binding runs."""
    model = _RouteModel(
        schema_replies=(_mapping(entry_price=INVALID_PRICE),),
        json_replies=(_mapping(),),
        plain_reply="**Rating**: Buy",
    )

    result = _run(model)

    assert result["final_rating"] == "REVIEW"
    assert _reasons(result) == ["invalid_entry_price"]
    assert model.route == ["schema"], "a decoded invalid price must not be retried"


# ---------------------------------------------------------------------------
# FR004-05 (2): both structured attempts miss; the JSON-mode retry decodes a
# body whose price is invalid. Same reasons, and still no free text.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_json_mode_invalid_price_is_review_without_a_text_fallback():
    """REQ-TA-FR-004 (Issue #32 FR004-05): the JSON-mode retry returns a
    decodable body with a bad stop, so the run is REVIEW with the matching
    ``invalid_*`` and free text is never called."""
    model = _RouteModel(
        schema_replies=("raise", "raise"),
        json_replies=(_mapping(stop_loss=INVALID_PRICE),),
        plain_reply="**Rating**: Buy",
    )

    result = _run(model)

    assert result["final_rating"] == "REVIEW"
    assert _reasons(result) == ["invalid_stop_loss"]
    assert model.route == ["schema", "schema", "json"], "free text must not follow a decoded invalid"


# ---------------------------------------------------------------------------
# Same two routes through the project's own parsing layer, with raw text.
# The parser must be able to carry the value the model wrote; the validator,
# not the model, decides the price is bad.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_structured_text_is_parsed_then_rejected_for_its_price():
    """REQ-TA-FR-004 (Issue #32 FR004-03): the first binding returns JSON text a
    schema bridge would parse. Parsing must not silently drop ``"15%"``; the
    validator rejects it, so the run is REVIEW and nothing retries."""
    model = _TextModel(
        schema_text=json.dumps(_mapping(entry_price=INVALID_PRICE)),
        json_text=json.dumps(_mapping()),
        plain_reply="**Rating**: Buy",
    )

    result = _run(model)

    assert result["final_rating"] == "REVIEW"
    assert _reasons(result) == ["invalid_entry_price"]
    assert model.route == ["schema"]


@pytest.mark.unit
def test_the_json_text_is_parsed_then_rejected_for_its_price():
    """REQ-TA-FR-004 (Issue #32 FR004-05): with both structured attempts missing,
    the JSON-mode retry's text is parsed by the project and then rejected for its
    price; free text is not called."""
    model = _TextModel(
        schema_text="raise",
        json_text=json.dumps(_mapping(stop_loss=INVALID_PRICE)),
        plain_reply="**Rating**: Buy",
    )

    result = _run(model)

    assert result["final_rating"] == "REVIEW"
    assert _reasons(result) == ["invalid_stop_loss"]
    assert model.route == ["schema", "schema", "json"]


# ---------------------------------------------------------------------------
# FR004-05 (3): a bare NaN/Infinity token is a decoding failure, not an invalid
# price. The existing order and the existing budget rules apply.
# ---------------------------------------------------------------------------

NON_FINITE_BODIES = {
    "nan": '{"rating": "Buy", "entry_price": NaN, "stop_loss": NaN}',
    "infinity": '{"rating": "Buy", "entry_price": Infinity, "stop_loss": Infinity}',
    "negative-infinity": '{"rating": "Buy", "entry_price": -Infinity, "stop_loss": -Infinity}',
}


@pytest.mark.unit
@pytest.mark.parametrize("token", list(NON_FINITE_BODIES), ids=list(NON_FINITE_BODIES))
def test_a_bare_non_finite_token_is_a_decode_miss(token):
    """REQ-TA-FR-004; REQ-TA-INV-001 (Issue #32 FR004-05): the raw body fails to
    decode, the run follows the existing path to free text, and the reason
    describes what arrived — no ``invalid_*`` invented from a rejected body."""
    model = _RouteModel(
        schema_replies=("raise", "raise"),
        json_replies=(NON_FINITE_BODIES[token],),
        plain_reply="I cannot produce a rating from this data.",
    )

    result = _run(model)

    assert result["final_rating"] == "REVIEW"
    assert _reasons(result) == ["unresolved_rating"]
    assert model.route == ["schema", "schema", "json", "plain"]
    assert result["claim_fallback"] == "free_text"


# ---------------------------------------------------------------------------
# Budget interaction. Two scenarios, because the refusal point differs.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_zero_budget_keeps_the_required_structured_call_only():
    """REQ-TA-FR-002 (D6); REQ-TA-FR-004: a zero budget admits no optional call,
    so the JSON retry and the free-text fallback never run. The required
    structured synthesis still runs exactly once, and the run ends REVIEW."""
    model = _RouteModel(
        schema_replies=("raise", "raise"),
        json_replies=(_mapping(),),
        plain_reply="**Rating**: Buy",
    )
    budget = RunBudgetTracker(0)
    with RunBudgetContext(budget).activate():
        assert admit_optional("pm_json_retry").allowed is False

    result = _run(model, budget=budget)

    assert model.route == ["schema"], "only the required structured attempt runs under a zero budget"
    assert result["final_rating"] == "REVIEW"
    assert _reasons(result) == ["unresolved_rating"]


@pytest.mark.unit
def test_an_exhausted_budget_still_allows_the_retry_then_refuses_free_text():
    """REQ-TA-FR-002; REQ-TA-FR-004 (Issue #32 FR004-05): the structured retry is
    admitted, the JSON retry is admitted, and by the time the free-text fallback
    is asked for the budget refuses it. The JSON body's bare ``NaN`` is a decode
    failure, so no plain call is made and the reason is the one the responses
    support."""
    model = _RouteModel(
        schema_replies=("raise", "raise"),
        json_replies=(NON_FINITE_BODIES["nan"],),
        plain_reply="**Rating**: Buy",
    )
    # The structured retry and the JSON retry are two optional admissions; the
    # free-text fallback is the third and is the one refused.
    budget = _exhaust_after_optional(calls=2)

    result = _run(model, budget=budget)

    assert model.route == ["schema", "schema", "json"]
    assert result["final_rating"] == "REVIEW"
    assert _reasons(result) == ["unresolved_rating"]


# ---------------------------------------------------------------------------
# Guardrails: valid answers keep their baseline outcome, so the new gate cannot
# be satisfied by rejecting everything.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_valid_structured_price_keeps_the_call():
    """REQ-TA-FR-004: a decodable answer with usable prices keeps its rating and
    records no review reasons."""
    model = _RouteModel(schema_replies=(_mapping(),))

    result = _run(model)

    assert result["final_rating"] == "Buy"
    assert _reasons(result) == []
    assert model.route == ["schema"]


@pytest.mark.unit
def test_the_pm_schema_keeps_its_existing_constructor_contract():
    """REQ-TA-FR-004: adding the price fields must not break the callers that
    build a decision without prices; Hold needs none."""
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD, confidence="low",
        executive_summary="s", investment_thesis="t")
    assert decision.entry_price is None
    assert decision.stop_loss is None
