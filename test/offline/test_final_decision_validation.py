"""FR-004 acceptance: the validator, and the run it produces end to end.

Approved test plan: Issue #32 (``test-approved``), cases FR004-01..FR004-07 and
INV001-01/02. Implements: REQ-TA-FR-004; REQ-TA-INV-001.

The route tests in ``test_decision_validation_routes.py`` pin *which* binding ran;
these pin the contract itself (the pure validator and the normalisation rules)
and that a real graph run persists and renders a REVIEW decision consistently.
"""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from tradingagents.agents.rating import (
    RATING_REVIEW,
    REASON_INVALID_ENTRY_PRICE,
    REASON_INVALID_STOP_LOSS,
    REASON_MISSING_ENTRY_PRICE,
    REASON_MISSING_STOP_LOSS,
    REASON_UNRESOLVED_RATING,
    normalise_price,
    validate_final_decision,
)
from tradingagents.agents.schemas import (
    PortfolioDecision,
    StrictJSONDecodeError,
    decode_strict_json,
)

# ---------------------------------------------------------------------------
# FR004-01: all five ratings, valid prices, and normalisation.
# ---------------------------------------------------------------------------

VALID = {"entry_price": 100.0, "stop_loss": 90.0}


@pytest.mark.unit
@pytest.mark.parametrize("rating", ["Buy", "Overweight", "Hold", "Underweight", "Sell"])
def test_each_rating_is_accepted_with_supplied_valid_prices(rating):
    """REQ-TA-FR-004 (FR004-01): each tier is accepted when the prices it carries
    are valid, and the normalised values come back as floats."""
    final, reasons, prices = validate_final_decision(rating, VALID)
    assert final == rating
    assert reasons == []
    assert prices == {"entry_price": 100.0, "stop_loss": 90.0}


@pytest.mark.unit
def test_a_number_and_its_text_forms_normalise_to_the_same_float():
    """REQ-TA-FR-004 (FR004-01): 100 and "100"/"+100"/"1e2"/" 100 " all give 100.0."""
    for raw in (100, "100", "+100", "1e2", " 100 "):
        assert normalise_price(raw) == 100.0
        assert isinstance(normalise_price(raw), float)


@pytest.mark.unit
def test_a_large_integer_rounds_per_binary64():
    """REQ-TA-FR-004 (FR004-01): 9007199254740993 does not round-trip exactly;
    the contract uses ordinary binary64 rounding and adds no exactness guarantee."""
    assert normalise_price(9007199254740993) == 9007199254740992.0


@pytest.mark.unit
def test_optional_prices_may_be_absent_for_a_non_entry_rating():
    """REQ-TA-FR-004 (FR004-01): Hold/Underweight/Sell pass with no prices."""
    for rating in ("Hold", "Underweight", "Sell"):
        final, reasons, prices = validate_final_decision(rating, {})
        assert (final, reasons, prices) == (rating, [], {})


# ---------------------------------------------------------------------------
# FR004-02: missing required prices carry the exact missing code.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("rating", ["Buy", "Overweight"])
def test_a_missing_required_price_is_review_with_the_missing_code(rating):
    """REQ-TA-FR-004 (FR004-02): an entry/stop that is absent or null is REVIEW."""
    final, reasons, _ = validate_final_decision(
        rating, {"entry_price": 100.0, "stop_loss": None})
    assert final == RATING_REVIEW
    assert reasons == [REASON_MISSING_STOP_LOSS]


@pytest.mark.unit
def test_both_required_prices_missing_accumulates_entry_then_stop():
    """REQ-TA-FR-004 (FR004-02): both missing -> entry then stop, in order."""
    final, reasons, _ = validate_final_decision("Buy", {})
    assert final == RATING_REVIEW
    assert reasons == [REASON_MISSING_ENTRY_PRICE, REASON_MISSING_STOP_LOSS]


# ---------------------------------------------------------------------------
# FR004-03: a supplied price that is not a valid price is REVIEW with the
# invalid code; entry-then-stop ordering; no invalid price is published.
# ---------------------------------------------------------------------------

INVALID_VALUES = [
    0, -0.0, -1, -1.5,
    1e309,          # overflow to +inf as a float
    1e-400,         # underflow to 0.0
    True, False,
    "", "   ",
    "$100", "1,000", "15%", "150-160", "about 150",
    "1e", ".", "1.2.3", "nan", "NaN", "Infinity", "-Infinity",
    math.nan, math.inf, -math.inf,
    # FR004-03 (Issue #32): a leading dot is not a price, Unicode/fullwidth
    # digits are not ASCII digits, and an integer too large for a finite float
    # is REVIEW (never an OverflowError).
    ".5", ".5 ", "５０", "５０.５", "１００",
    10**400, "1" + "0" * 400,
]


@pytest.mark.unit
@pytest.mark.parametrize("bad", INVALID_VALUES, ids=[repr(v) for v in INVALID_VALUES])
def test_an_invalid_supplied_price_is_review_with_the_invalid_code(bad):
    """REQ-TA-FR-004 (FR004-03): with the other field valid, one bad price ->
    exactly its invalid code. A blank string is invalid, not missing."""
    final, reasons, prices = validate_final_decision(
        "Buy", {"entry_price": bad, "stop_loss": 90.0})
    assert final == RATING_REVIEW
    assert reasons == [REASON_INVALID_ENTRY_PRICE]
    assert "entry_price" not in prices


@pytest.mark.unit
def test_missing_and_invalid_are_ordered_entry_then_stop():
    """REQ-TA-FR-004 (FR004-03): the mixed cases list entry's reason first."""
    assert validate_final_decision(
        "Buy", {"stop_loss": "nope"})[1] == [REASON_MISSING_ENTRY_PRICE, REASON_INVALID_STOP_LOSS]
    assert validate_final_decision(
        "Buy", {"entry_price": "nope"})[1] == [REASON_INVALID_ENTRY_PRICE, REASON_MISSING_STOP_LOSS]
    assert validate_final_decision(
        "Buy", {"entry_price": "nope", "stop_loss": "nope"})[1] == [
            REASON_INVALID_ENTRY_PRICE, REASON_INVALID_STOP_LOSS]


@pytest.mark.unit
def test_a_price_too_large_for_a_float_is_review_not_an_overflow():
    """REQ-TA-FR-004 (FR004-03): an integer beyond the finite-float range is a
    supplied invalid price -> REVIEW, never an uncaught ``OverflowError``."""
    for huge in (10**400, 10**5000, "1" + "0" * 400):
        final, reasons, prices = validate_final_decision(
            "Buy", {"entry_price": huge, "stop_loss": 90.0})
        assert (final, reasons) == (RATING_REVIEW, [REASON_INVALID_ENTRY_PRICE])
        assert "entry_price" not in prices


@pytest.mark.unit
def test_ordinary_decimal_and_exponent_forms_remain_valid():
    """REQ-TA-FR-004 (FR004-03): tightening the grammar leaves ``0.5`` and
    ``1e2`` (leading integer digit) valid; only a missing integer part is not."""
    assert normalise_price(0.5) == 0.5
    assert normalise_price("0.5") == 0.5
    assert normalise_price("1e2") == 100.0
    final, reasons, _ = validate_final_decision(
        "Buy", {"entry_price": "0.5", "stop_loss": "1e2"})
    assert (final, reasons) == ("Buy", [])


# ---------------------------------------------------------------------------
# INV001-01/02: an unresolved rating is REVIEW, and a fullwidth-colon rating is
# still readable (the registry's corrected example).
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_unresolved_rating_short_circuits_to_unresolved():
    """REQ-TA-INV-001 (INV001-01): no rating -> exactly ["unresolved_rating"],
    even when malformed prices came with it."""
    final, reasons, prices = validate_final_decision(
        None, {"entry_price": "15%", "stop_loss": -1})
    assert (final, reasons, prices) == (RATING_REVIEW, [REASON_UNRESOLVED_RATING], {})


# ---------------------------------------------------------------------------
# Strict JSON: a bare NaN/Infinity token is a decoding failure.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_a_bare_non_finite_token_fails_strict_decoding(token):
    """REQ-TA-FR-004 (FR004-05): strict decoding refuses the bare token."""
    with pytest.raises(StrictJSONDecodeError):
        decode_strict_json('{"rating": "Buy", "entry_price": ' + token + '}')


@pytest.mark.unit
def test_a_normal_json_body_still_decodes_strictly():
    """A well-formed body decodes; only the non-finite tokens are refused."""
    assert decode_strict_json('{"rating": "Buy", "entry_price": 100}') == {
        "rating": "Buy", "entry_price": 100}


@pytest.mark.unit
def test_a_decision_built_from_raw_keeps_the_price_as_written():
    """REQ-TA-FR-004: the schema must not coerce a written price, so the
    validator can tell "15%" from "absent"."""
    decision = PortfolioDecision.model_validate(
        {"rating": "Buy", "confidence": "medium", "executive_summary": "s",
         "investment_thesis": "t", "entry_price": "15%", "stop_loss": 172.0})
    assert decision.entry_price == "15%"


# ---------------------------------------------------------------------------
# FR004-06 / FR004-07: a real graph run persists and renders REVIEW.
# ---------------------------------------------------------------------------

from offline import test_graph_end_to_end as upstream  # noqa: E402
from tradingagents.agents import context, schemas  # noqa: E402
from tradingagents.agents.analysts import sentiment_analyst  # noqa: E402
from tradingagents.dataflows import router  # noqa: E402
from tradingagents.dataflows.vendors.yahoo import market as yahoo_market, snapshot  # noqa: E402
from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.graph import trading_graph  # noqa: E402
from tradingagents.reporting import write_report_tree  # noqa: E402

TRADE_DATE = "2026-01-09"


@pytest.fixture
def offline(monkeypatch):
    for method, vendors in router.VENDOR_METHODS.items():
        for vendor in vendors:
            monkeypatch.setitem(vendors, vendor, lambda *a, _m=method, **k: f"{_m} data")
    prices = pd.DataFrame({
        "Date": pd.bdate_range(end=TRADE_DATE, periods=60),
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1_000_000,
    })
    monkeypatch.setattr(snapshot, "load_ohlcv", lambda *a, **k: prices.copy())
    monkeypatch.setattr(sentiment_analyst, "fetch_stocktwits_messages", lambda *a, **k: "no posts")
    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts", lambda *a, **k: "no posts")
    monkeypatch.setattr(yahoo_market.yf, "Ticker", lambda s: type("T", (), {"info": {"longName": "NVIDIA"}})())
    context._identity.cache_clear()


class _BuyModel(upstream.ScriptedModel):
    """The e2e ScriptedModel, but the PM answers Buy with a chosen entry price."""

    entry_price: object = 100.0

    def with_structured_output(self, schema, **kwargs):
        from langchain_core.runnables import RunnableLambda

        def answer(_prompt):
            self._count()
            if schema is schemas.PortfolioDecision:
                return schemas.PortfolioDecision(
                    rating=schemas.PortfolioRating.BUY, confidence="medium",
                    executive_summary="Enter now.", investment_thesis="Breakout.",
                    entry_price=self.entry_price, stop_loss=90.0)
            return upstream.STRUCTURED[schema]

        return RunnableLambda(answer)


def _graph(tmp_path, monkeypatch, entry_price):
    import copy
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / "results"), data_cache_dir=str(tmp_path / "cache"),
               memory_log_path=str(tmp_path / "log.md"))
    model = _BuyModel(structured=True, entry_price=entry_price)
    monkeypatch.setattr(trading_graph, "create_tier_client",
                        lambda config, tier, **k: type("C", (), {"get_llm": lambda s: model})())
    return trading_graph.TradingAgentsGraph(config=cfg, debug=False)


@pytest.mark.unit
def test_a_rejected_decision_is_review_everywhere_it_is_recorded(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-004 (FR004-06): a Buy with an invalid price is REVIEW in the
    returned rating, the state log, the Markdown header, the HTML header and the
    memory entry; the reasons are persisted too."""
    graph = _graph(tmp_path, monkeypatch, entry_price="15%")

    state, signal = graph.propagate("NVDA", TRADE_DATE)

    assert signal == state["final_rating"] == RATING_REVIEW
    assert state["decision_review_reasons"] == [REASON_INVALID_ENTRY_PRICE]
    # FR004-01: a REVIEW publishes no prices in the final state.
    assert state["final_prices"] == {}

    log = json.loads(
        (tmp_path / "results" / "NVDA" / "TradingAgentsStrategy_logs"
         / f"full_states_log_{TRADE_DATE}.json").read_text())
    assert log["final_rating"] == RATING_REVIEW
    assert log["decision_review_reasons"] == [REASON_INVALID_ENTRY_PRICE]
    # FR004-01: and the run-state JSON records {} for a REVIEW.
    assert log["final_prices"] == {}

    write_report_tree(state, "NVDA", tmp_path / "report", settings=graph.run_settings(), html=True)
    markdown = (tmp_path / "report" / "complete_report.md").read_text()
    assert "- Rating: REVIEW" in markdown
    assert "Review reasons: invalid_entry_price" in markdown
    html = (tmp_path / "report" / "complete_report.html").read_text()
    assert 'class="rating review">REVIEW</span>' in html

    entries = graph.memory_log.load_entries()
    assert entries and entries[-1]["rating"] == RATING_REVIEW


@pytest.mark.unit
def test_a_valid_decision_is_not_reviewed(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-004 (FR004-07): the same run with a valid price is Buy, with no
    review reasons and no review line in the report."""
    graph = _graph(tmp_path, monkeypatch, entry_price=100.0)

    state, signal = graph.propagate("NVDA", TRADE_DATE)

    assert signal == state["final_rating"] == "Buy"
    assert state["decision_review_reasons"] == []
    # FR004-01: an accepted decision publishes the validated prices (floats).
    assert state["final_prices"] == {"entry_price": 100.0, "stop_loss": 90.0}

    log = json.loads(
        (tmp_path / "results" / "NVDA" / "TradingAgentsStrategy_logs"
         / f"full_states_log_{TRADE_DATE}.json").read_text())
    assert log["final_prices"] == {"entry_price": 100.0, "stop_loss": 90.0}

    write_report_tree(state, "NVDA", tmp_path / "report", settings=graph.run_settings(), html=True)
    markdown = (tmp_path / "report" / "complete_report.md").read_text()
    assert "- Rating: Buy" in markdown
    assert "Review reasons:" not in markdown


@pytest.mark.unit
def test_a_state_without_final_prices_reads_back_as_empty(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-004 (FR004-01): a state written before this field existed (no
    ``final_prices`` key) is persisted as {} rather than failing."""
    import copy

    graph = trading_graph.TradingAgentsGraph(config=copy.deepcopy(DEFAULT_CONFIG))
    graph.config = {**graph.config, "results_dir": str(tmp_path / "results")}

    old_state = {
        "company_of_interest": "NVDA", "trade_date": TRADE_DATE,
        "market_report": "m", "sentiment_report": "s", "news_report": "n",
        "fundamentals_report": "f",
        "investment_debate_state": {"bull_history": "", "bear_history": "", "history": "",
                                    "current_response": ""},
        "trader_investment_plan": "t",
        "risk_debate_state": {"aggressive_history": "", "conservative_history": "",
                              "neutral_history": "", "history": ""},
        "investment_plan": "p", "final_trade_decision": "**Rating**: Buy",
        "final_rating": "Buy",
        # deliberately no "final_prices" key: an older saved state
    }

    graph._log_state(TRADE_DATE, old_state)

    log = json.loads(
        (tmp_path / "results" / "NVDA" / "TradingAgentsStrategy_logs"
         / f"full_states_log_{TRADE_DATE}.json").read_text())
    assert log["final_prices"] == {}
