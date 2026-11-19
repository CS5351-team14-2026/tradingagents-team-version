"""FR-004 regression: the three defects found after PR #52 (Issue #32; ADR-003).

Approved plan: fix the FR-004 slice landed in PR #52. These tests are written
first, against the *current* integration, and must FAIL there to prove each
defect is real; the matching production fix is written only after they are
reviewed. Implements: REQ-TA-FR-004; REQ-TA-INV-001.

Three defects, one test group each:

1. **Prose Buy/Overweight is adopted.** When structured and JSON-mode both miss,
   the free-text fallback's rating is read but its prices are never validated, so
   a plain-text Buy/Overweight with no prices is adopted instead of REVIEW with
   ``missing_entry_price``/``missing_stop_loss``. Hold is the passing control.

2. **The real JSON-mode wrapper parses a bare ``NaN``.** The decode guard
   (``decode_strict_json``) only sees a *string* body; LangChain's own
   ``PydanticOutputParser`` (``json.loads``) turns a bare ``NaN``/``Infinity`` into
   ``float('nan')`` and hands back a ``PortfolioDecision``, so the strict decoder
   is never reached and the value is misread as a *supplied invalid* price. The
   contract (ADR-003 §6) says a bare non-finite token is a *decoding* failure that
   follows the existing retry/fallback and token budget. A body that is *valid
   JSON but carries a non-finite price* is the contrast: it decodes and is
   directly ``invalid_*`` with no retry. These tests drive the *real*
   ``with_structured_output(method="json_mode")`` through a mocked HTTP response.

3. **REVIEW is not shown in the final-decision region.** With a top-level REVIEW,
   the Markdown report's §V, the HTML body and the CLI panel still print the
   model's own ``**Rating**: Buy`` and its entry instructions, so the decision
   region reads as an executable Buy. The reconciled REVIEW summary must be shown
   there instead.
"""

from __future__ import annotations

import importlib.util
import os
import re

import httpx
import pytest

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.llm_clients.openai_client import OpenAIClient

# Reuse the route harness (scripted bindings, PM_STATE, the budget subclass) so
# this file stays about the three defects, not a second copy of the scaffolding.
_ROUTE_PATH = os.path.join(os.path.dirname(__file__), "test_decision_validation_routes.py")
_spec = importlib.util.spec_from_file_location("_fr004_routes", _ROUTE_PATH)
routes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(routes)

PM_STATE = routes.PM_STATE
_mapping = routes._mapping


# ---------------------------------------------------------------------------
# Defect 1 — a prose-only Buy/Overweight must be REVIEW, with both prices named.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("rating", ["Buy", "Overweight"])
def test_a_prose_only_entry_rating_is_review_with_both_missing_prices(rating):
    """REQ-TA-FR-004 (defect 1): structured and JSON-mode both miss and the
    free-text fallback states a bare ``Buy``/``Overweight`` rating with no price
    levels. The fallback carries no prices, so the decision is REVIEW with both
    missing-price reasons, entry before stop — never an adopted Buy."""
    model = routes._RouteModel(
        schema_replies=("raise", "raise"),
        json_replies=("raise",),
        plain_reply=f"- **Rating**: {rating}\n\nEnter now on breakout confirmation.",
    )

    result = routes._run(model)

    assert model.route == ["schema", "schema", "json", "plain"], (
        "the fallback must actually run to reproduce the prose path"
    )
    assert result["final_rating"] == "REVIEW", (
        "a prose-only Buy/Overweight with no prices is not a tradeable call"
    )
    assert routes._reasons(result) == ["missing_entry_price", "missing_stop_loss"]


@pytest.mark.unit
def test_a_prose_only_hold_is_not_reviewed():
    """REQ-TA-FR-004 (defect 1, passing control): a prose Hold needs no prices, so
    price validation must not turn it into REVIEW. This guards against 'fixing'
    defect 1 by rejecting every prose fallback."""
    model = routes._RouteModel(
        schema_replies=("raise", "raise"),
        json_replies=("raise",),
        plain_reply="- **Rating**: Hold\n\nWait for confirmation before acting.",
    )

    result = routes._run(model)

    assert model.route == ["schema", "schema", "json", "plain"]
    assert result["final_rating"] == "Hold"
    assert routes._reasons(result) == []


# ---------------------------------------------------------------------------
# Defect 2 — the *real* JSON-mode wrapper and a bare non-finite token.
#
# These drive the project's real client (OpenAIClient -> DeepSeekChatOpenAI ->
# langchain ChatOpenAI -> its own with_structured_output(method="json_mode") ->
# PydanticOutputParser), with the HTTP layer replaced by a mock transport. The
# raw response body is kept so the two cases can be told apart.
# ---------------------------------------------------------------------------


def _real_llm(body: str, *, requests: list) -> object:
    """A real DeepSeek chat client whose HTTP layer answers with ``body``.

    ``requests`` is appended to on every call, so a test can assert *how many*
    model calls the route and the token budget allowed.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "deepseek-v4-flash",
            "choices": [
                {"index": 0,
                 "message": {"role": "assistant", "content": body},
                 "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return httpx.Response(200, json=payload)

    return OpenAIClient(
        "deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        provider="deepseek",
        api_key="placeholder",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).get_llm()


# The raw bodies stay strings on purpose: the defect is that LangChain's parser,
# not ``decode_strict_json``, reads the non-finite token. ``json.dumps`` here is
# only used for the *valid* contrast bodies.
BARE_NON_FINITE = {
    "nan": '{"rating": "Buy", "confidence": "medium", "executive_summary": "Enter now.", '
           '"investment_thesis": "Breakout.", "entry_price": NaN, "stop_loss": NaN}',
    "infinity": '{"rating": "Buy", "confidence": "medium", "executive_summary": "Enter now.", '
                '"investment_thesis": "Breakout.", "entry_price": Infinity, "stop_loss": Infinity}',
    "negative-infinity": '{"rating": "Buy", "confidence": "medium", "executive_summary": "Enter now.", '
                         '"investment_thesis": "Breakout.", "entry_price": -Infinity, '
                         '"stop_loss": -Infinity}',
}


@pytest.mark.unit
@pytest.mark.parametrize("token", list(BARE_NON_FINITE), ids=list(BARE_NON_FINITE))
def test_a_bare_non_finite_body_is_a_decode_miss_not_an_invalid_price(token):
    """REQ-TA-FR-004; ADR-003 §6 (defect 2): the raw HTTP body carries a bare
    ``NaN``/``Infinity``/``-Infinity``. Strictly that is not JSON, so the run must
    treat it as a *decoding* failure — a miss that falls through to the existing
    free-text step — and never fabricate ``invalid_*`` reasons from a body it
    could not decode. On the current integration the real wrapper parses it into a
    ``PortfolioDecision`` and the run returns ``invalid_entry_price,
    invalid_stop_loss``; that is the defect this test pins."""
    requests: list = []
    llm = _real_llm(BARE_NON_FINITE[token], requests=requests)
    node = create_portfolio_manager(llm)

    result = node(dict(PM_STATE))

    assert result["final_rating"] == "REVIEW"
    assert result["decision_review_reasons"] == ["unresolved_rating"], (
        "a body that does not decode contributes no field-specific price reason"
    )
    # The miss follows the existing order into the free-text fallback.
    assert result["claim_fallback"] == "free_text"


@pytest.mark.unit
def test_a_bare_nan_still_obeys_the_token_budget():
    """REQ-TA-FR-004; REQ-TA-FR-002 (defect 2): a decode miss does not buy extra
    calls. With the optional budget spent, the free-text fallback is refused and
    the run ends a controlled REVIEW — the same gate a genuine miss already gets."""
    requests: list = []
    llm = _real_llm(BARE_NON_FINITE["nan"], requests=requests)
    node = create_portfolio_manager(llm)
    # The structured retry and the JSON retry are the two optional admissions
    # before the free-text fallback; the fallback is the one refused.
    budget = routes._exhaust_after_optional(calls=2)

    with routes.RunBudgetContext(budget).activate():
        result = node(dict(PM_STATE))

    assert result["final_rating"] == "REVIEW"
    assert result["decision_review_reasons"] == ["unresolved_rating"]
    # No free-text request followed: the run stopped once the budget refused it.
    # Three HTTP calls only — the required structured attempt, its gated retry, and
    # the JSON-mode retry; the refused fallback made no fourth request.
    assert len(requests) == 3, f"expected 3 model calls, saw {len(requests)}"


@pytest.mark.unit
def test_a_decoded_non_finite_price_is_invalid_without_a_retry():
    """REQ-TA-FR-004; ADR-003 §5 (defect 2 contrast): a genuinely *decoded*
    decision whose price is a non-finite ``float`` (``float('nan')``) — no raw JSON
    text with a bare token, the value is already a Python float. This decodes, so
    the price policy runs directly: REVIEW with ``invalid_*`` and no retry and no
    free-text call. It is the counterpart to the bare-token case above; the two are
    told apart by whether a raw body failed to decode, not by the nan-ness alone."""
    # The JSON-mode binding answers with an already-parsed decision carrying a
    # real non-finite float — the "decoded data" case, distinct from a raw body
    # with a bare NaN token.
    model = routes._RouteModel(
        schema_replies=("raise", "raise"),
        json_replies=({
            "rating": "Buy", "confidence": "medium", "executive_summary": "Enter now.",
            "investment_thesis": "Breakout.",
            "entry_price": float("nan"), "stop_loss": 90.0,
        },),
        plain_reply="**Rating**: Buy",
    )

    result = routes._run(model)

    assert result["final_rating"] == "REVIEW"
    assert result["decision_review_reasons"] == ["invalid_entry_price"]
    # A decoded-but-invalid decision is terminal (ADR-003 §5): no later binding.
    assert model.route == ["schema", "schema", "json"]
    assert result["claim_fallback"] is None


# ---------------------------------------------------------------------------
# Defect 3 — REVIEW must own the final-decision region on every surface.
#
# A state as the node would publish it for a decoded Buy the price gate rejected:
# the rating is REVIEW, the reasons are recorded, and the *rendered* decision
# text still begins with the model's ``**Rating**: Buy`` and its entry order.
# ---------------------------------------------------------------------------

REVIEW_STATE = {
    "trade_date": "2026-01-09",
    "final_rating": "REVIEW",
    "decision_review_reasons": ["missing_entry_price", "missing_stop_loss"],
    "final_trade_decision": (
        "**Rating**: Buy\n\n"
        "**Confidence**: high\n\n"
        "**Executive Summary**: Enter now at market; the breakout confirms.\n\n"
        "**Investment Thesis**: Volume and guidance both support the move."
    ),
}

# The phrases that must NOT present the old decision as an executable call.
_STALE_RATING = re.compile(r"\bRating\b\s*[:*]*\s*Buy\b", re.IGNORECASE)
_STALE_INSTRUCTION = re.compile(r"Enter now at market", re.IGNORECASE)


def _assert_review_region(text: str, surface: str) -> None:
    """The final-decision region says REVIEW, names the reasons, and shows no
    stale Buy rating or its entry instruction."""
    assert "REVIEW" in text, f"{surface}: the final-decision region must show REVIEW"
    assert "missing_entry_price" in text, f"{surface}: the missing-price reason must be shown"
    assert "missing_stop_loss" in text, f"{surface}: the missing-price reason must be shown"
    assert not _STALE_RATING.search(text), (
        f"{surface}: a top-level REVIEW must not still present the model's 'Rating: Buy'"
    )
    assert not _STALE_INSTRUCTION.search(text), (
        f"{surface}: a top-level REVIEW must not still present the entry instruction"
    )


@pytest.mark.unit
def test_the_markdown_report_shows_review_in_the_final_decision_section():
    """REQ-TA-FR-004; ADR-003 §7 (defect 3): the Markdown report's Portfolio
    Manager section (§V) shows the REVIEW summary, not the model's Buy rating and
    entry order."""
    from tradingagents.reporting import _report_document, _report_parts

    parts = _report_parts(REVIEW_STATE)
    sections = [
        f"## {heading}\n\n" + "\n\n".join(f"### {agent}\n{text}" for agent, _f, text in written)
        for heading, _folder, written in parts
    ]
    document = _report_document("NVDA", REVIEW_STATE, None, sections)
    section_v = document[document.index("## V. Portfolio Manager Decision"):]
    _assert_review_region(section_v, "markdown §V")


@pytest.mark.unit
def test_the_html_body_shows_review_in_the_final_decision_section():
    """REQ-TA-FR-004; ADR-003 §7 (defect 3): the HTML report body's Portfolio
    Manager section shows the REVIEW summary, not ``Rating: Buy``."""
    from tradingagents.report_html import render_report
    from tradingagents.reporting import _report_parts

    html = render_report("NVDA", REVIEW_STATE, None, _report_parts(REVIEW_STATE))
    marker = html.index("Portfolio Manager</h3>")
    body = html[marker:]
    _assert_review_region(re.sub(r"<[^>]+>", " ", body), "html §V")


@pytest.mark.unit
def test_the_cli_panel_shows_review_in_the_final_decision_section():
    """REQ-TA-FR-004; ADR-003 §7 (defect 3): the CLI's complete-report display
    (``display_complete_report``) shows REVIEW in the Portfolio Manager panel,
    not the model's Buy rating and entry order."""
    from rich.console import Console

    import cli.display as display

    buffer = []
    capture_console = Console(file=type("S", (), {
        "write": lambda _self, text: buffer.append(text),
        "flush": lambda _self: None,
    })(), width=120, force_terminal=False, no_color=True)
    original = display.console
    display.console = capture_console
    try:
        display.display_complete_report(dict(REVIEW_STATE))
    finally:
        display.console = original

    rendered = "".join(buffer)
    section_v = rendered[rendered.index("Portfolio Manager"):]
    _assert_review_region(section_v, "cli panel")


# ---------------------------------------------------------------------------
# Defect 3 (live path) — the *streamed* live Portfolio Manager panel must also
# reconcile a REVIEW, not only the saved report/complete-report display.
#
# This drives the real ``run_analysis`` stream loop with a REVIEW-producing
# model, and records the ``final_trade_decision`` report section the live panel
# is fed. The section must be the REVIEW summary (with its reasons), never the
# model's superseded Buy and entry order.
# ---------------------------------------------------------------------------


class _RecordingBuffer:
    """The CLI message buffer seam, recording the sections the live panel shows."""

    def __init__(self):
        self.selected_analysts = []
        self.messages = []
        self.tool_calls = []
        self.agent_status = {}
        self.sections = {}
        self.report_sections = {}
        self._processed_message_ids = set()

    def init_for_analysis(self, selected_analysts):
        self.selected_analysts = list(selected_analysts)

    def add_message(self, kind, content):
        self.messages.append((0.0, kind, content))

    def add_tool_call(self, name, args):
        self.tool_calls.append((0.0, name, args))

    def update_report_section(self, section, content):
        self.sections[section] = content
        self.report_sections[section] = content

    def update_agent_status(self, *a):
        pass


class _ReviewClient:
    """A tier client whose PM answer is a Buy that will be gated to REVIEW."""

    def __init__(self, model):
        self.model = model

    def get_llm(self):
        return self.model


@pytest.mark.unit
def test_the_live_panel_shows_review_in_the_final_decision_section(monkeypatch, tmp_path):
    """REQ-TA-FR-004; ADR-003 §8 (defect 3, live path): during a real streamed run,
    the Portfolio Manager section fed to the live panel is the REVIEW summary with
    its reasons — not the model's Buy text. A structured Buy missing its entry
    price is REVIEW (``missing_entry_price``)."""
    import copy

    import pandas as pd
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.runnables import RunnableLambda
    from pydantic import Field

    import cli.run as cli_run
    from cli.models import AnalystType
    from tradingagents.agents import context, schemas
    from tradingagents.agents.analysts import sentiment_analyst
    from tradingagents.dataflows import router
    from tradingagents.dataflows.vendors.yahoo import market as yahoo_market, snapshot
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph import trading_graph

    trade_date = "2026-01-10"
    text = "Report.\n\n**Rating**: Buy\n\nFINAL TRANSACTION PROPOSAL: **BUY**"
    structured = {
        schemas.ResearchPlan: schemas.ResearchPlan(
            recommendation=schemas.PortfolioRating.BUY, rationale="r", strategic_actions="a"),
        schemas.TraderProposal: schemas.TraderProposal(action=schemas.TraderAction.BUY, reasoning="r"),
        # A Buy with no entry price: the price gate makes this REVIEW.
        schemas.PortfolioDecision: schemas.PortfolioDecision(
            rating=schemas.PortfolioRating.BUY, confidence="medium",
            executive_summary="Enter now at market.",
            entry_price=None, stop_loss=None,
            investment_thesis="Breakout."),
        schemas.SentimentReport: schemas.SentimentReport(
            overall_band=schemas.SentimentBand.NEUTRAL, overall_score=5.0,
            confidence="low", narrative="n"),
    }
    args = {"symbol": "NVDA", "ticker": "NVDA", "curr_date": trade_date,
            "start_date": "2026-01-02", "end_date": trade_date, "indicator": "rsi",
            "topic": "Fed rate cut", "freq": "quarterly"}

    class _Model(BaseChatModel):
        tools: tuple = ()
        calls: list = Field(default_factory=list)

        @property
        def _llm_type(self):
            return "fr004-live-review"

        def bind_tools(self, tools, **kwargs):
            return self.model_copy(update={"tools": tuple(tools)})

        def with_structured_output(self, schema, **kwargs):
            return RunnableLambda(lambda _: self.calls.append(1) or structured[schema])

        def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
            self.calls.append(1)
            if self.tools and not isinstance(messages[-1], ToolMessage):
                calls = [{"name": t.name, "id": f"call_{i}",
                          "args": {k: v for k, v in args.items()
                                   if k in t.tool_call_schema.model_json_schema()["properties"]}}
                         for i, t in enumerate(self.tools)]
                message = AIMessage(content="", tool_calls=calls)
            else:
                message = AIMessage(content=text)
            return ChatResult(generations=[ChatGeneration(message=message)])

    # Offline doubles for the external services (same shape as the e2e harness).
    for method, vendors in router.VENDOR_METHODS.items():
        for vendor in vendors:
            monkeypatch.setitem(vendors, vendor, lambda *a, _m=method, **k: f"{_m} data")
    prices = pd.DataFrame({
        "Date": pd.bdate_range(end=trade_date, periods=60),
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1_000_000,
    })
    monkeypatch.setattr(snapshot, "load_ohlcv", lambda *a, **k: prices.copy())
    monkeypatch.setattr(sentiment_analyst, "fetch_stocktwits_messages", lambda *a, **k: "no posts")
    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts", lambda *a, **k: "no posts")
    monkeypatch.setattr(yahoo_market.yf, "Ticker", lambda s: type("T", (), {"info": {"longName": "X"}})())
    context._identity.cache_clear()
    monkeypatch.setattr(trading_graph, "create_tier_client",
                        lambda config, tier, **k: _ReviewClient(_Model()))

    buffer = _RecordingBuffer()
    monkeypatch.setattr(cli_run, "message_buffer", buffer)
    monkeypatch.setattr(cli_run, "create_layout", lambda: None)
    monkeypatch.setattr(cli_run, "update_display", lambda *a, **k: None)
    monkeypatch.setattr(cli_run, "Live", lambda *a, **k: type(
        "L", (), {"__enter__": lambda s: s, "__exit__": lambda s, *e: False})())
    monkeypatch.setattr(cli_run, "get_user_selections", lambda flags=None: {
        "ticker": "NVDA", "analysis_date": trade_date, "asset_type": "stock",
        "analysts": [AnalystType("market")],
        "research_depth": 1, "quick_think_llm": "q", "deep_think_llm": "d",
        "backend_url": None, "llm_provider": "openai", "google_thinking_level": None,
        "openai_reasoning_effort": None, "anthropic_effort": None, "output_language": "English",
    })
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / "results"), data_cache_dir=str(tmp_path / "cache"),
               memory_log_path=str(tmp_path / "log.md"))
    monkeypatch.setattr(cli_run, "_build_run_config", lambda selections, checkpoint, profile=None: cfg)
    monkeypatch.setattr(cli_run.typer, "prompt", lambda *a, **k: "N")

    cli_run.run_analysis(
        flags={"ticker": "NVDA", "date": trade_date, "analysts": None,
               "save": False, "show": False, "html": None})

    section = buffer.sections.get("final_trade_decision", "")
    # The live panel is fed the run's final decision section; on REVIEW it is the
    # REVIEW summary with its reasons, never the model's Buy text.
    _assert_review_region(section, "cli live panel")
