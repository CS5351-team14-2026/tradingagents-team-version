"""FR004-06: the real ``python -m cli.main`` run, offline, shows REVIEW for a
decoded Buy whose price is missing, and the run's report and state log agree.

Approved test plan: Issue #32 (``test-approved``) FR004-06.
Implements: REQ-TA-FR-004; REQ-TA-INV-001.

A subprocess is used on purpose: this is the CLI entry point as a user runs it
(``python -m cli.main``), not ``run_analysis`` called in-process. External
services are replaced at the *process boundary* by a ``sitecustomize`` module
placed on ``PYTHONPATH``: it stubs the vendor router and the LLM tier client
before ``cli.main`` imports them, so the real CLI, graph, validator,
persistence and rendering all execute unmodified.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRADE_DATE = "2026-01-09"

# The stub installed before cli.main imports anything. It replaces the vendor
# router's network methods and the LLM tier client; everything the CLI, graph
# and report code do with them runs for real.
SITECUSTOMIZE = textwrap.dedent(
    '''
    import os


    def _install():
        # The offline end-to-end test double answers the analyst tool loop and the
        # agent schemas; importing it here runs the same model the e2e suite uses,
        # so only the external services are replaced, not the graph.
        import test_graph_end_to_end as upstream

        from tradingagents.dataflows import router
        for method, vendors in router.VENDOR_METHODS.items():
            for vendor in vendors:
                vendors[vendor] = (lambda *a, _m=method, **k: f"{_m} data")

        import pandas as pd
        from tradingagents.dataflows.vendors.yahoo import market as yahoo_market, snapshot
        prices = pd.DataFrame({
            "Date": pd.bdate_range(end=os.environ["FR004_DATE"], periods=60),
            "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1_000_000,
        })
        snapshot.load_ohlcv = lambda *a, **k: prices.copy()
        yahoo_market.yf.Ticker = lambda s: type("T", (), {"info": {"longName": "NVIDIA"}})()
        from tradingagents.agents.analysts import sentiment_analyst
        sentiment_analyst.fetch_stocktwits_messages = lambda *a, **k: "no posts"
        sentiment_analyst.fetch_reddit_posts = lambda *a, **k: "no posts"
        from tradingagents.agents import context
        context._identity.cache_clear()

        from langchain_core.runnables import RunnableLambda
        from tradingagents.agents import schemas
        from tradingagents.graph import trading_graph

        entry = os.environ.get("FR004_ENTRY")
        entry = None if entry in (None, "") else entry

        class _Model(upstream.ScriptedModel):
            def with_structured_output(self, schema, **kwargs):
                def answer(_prompt):
                    self._count()
                    if schema is schemas.PortfolioDecision:
                        return schemas.PortfolioDecision(
                            rating=schemas.PortfolioRating.BUY, confidence="medium",
                            executive_summary="Enter now.", investment_thesis="Breakout.",
                            entry_price=entry, stop_loss=90.0)
                    return upstream.STRUCTURED[schema]
                return RunnableLambda(answer)

        trading_graph.create_tier_client = (
            lambda config, tier, **k: type("C", (), {"get_llm": lambda s: _Model(structured=True)})())


    _install()
    '''
)

# The stored entry price the stub PM answers with (and the code under test reads
# as "a price the model wrote"). ``15%`` is the FR004-03 invalid case; an absent
# value is the FR004-04/07 missing case.
ENV_COMMON = {
    "TRADINGAGENTS_LLM_PROVIDER": "openai",
    "TRADINGAGENTS_QUICK_THINK_LLM": "q",
    "TRADINGAGENTS_DEEP_THINK_LLM": "d",
    "TRADINGAGENTS_OUTPUT_LANGUAGE": "English",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS": "1",
    "TRADINGAGENTS_MAX_RISK_ROUNDS": "1",
    "FR004_DATE": TRADE_DATE,
    "OPENAI_API_KEY": "placeholder",
}


def _run_cli(tmp_path, *, entry, home):
    """Run ``python -m cli.main`` as a subprocess, offline, and return the result."""
    harness = tmp_path / "harness"
    harness.mkdir()
    (harness / "sitecustomize.py").write_text(SITECUSTOMIZE)

    results = tmp_path / "results"
    cache = tmp_path / "cache"
    env = {
        **os.environ,
        **ENV_COMMON,
        "PYTHONPATH": f"{harness}{os.pathsep}{REPO_ROOT}/src{os.pathsep}{REPO_ROOT}/test/offline",
        "TRADINGAGENTS_RESULTS_DIR": str(results),
        "TRADINGAGENTS_CACHE_DIR": str(cache),
        "TRADINGAGENTS_MEMORY_LOG_PATH": str(tmp_path / "memory" / "trading_memory.md"),
        "HOME": str(home),
    }
    if entry is not None:
        env["FR004_ENTRY"] = entry
    else:
        env.pop("FR004_ENTRY", None)

    proc = subprocess.run(
        [sys.executable, "-m", "cli.main",
         "--ticker", "NVDA", "--date", TRADE_DATE, "--analysts", "market",
         "--save", "--no-show", "--no-html"],
        cwd=str(tmp_path / "harness"), env=env, capture_output=True, text=True, timeout=600,
    )
    return proc, results, cache


@pytest.mark.unit
def test_the_cli_shows_review_when_the_final_buy_has_no_price(tmp_path):
    """REQ-TA-FR-004 (FR004-06): a decoded Buy with no entry price is REVIEW. The
    real CLI prints a review notice, saves a report headed REVIEW, and writes a
    state log whose final_rating and decision_review_reasons agree."""
    home = tmp_path / "home"
    home.mkdir()
    proc, results, _cache = _run_cli(tmp_path, entry=None, home=home)

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-3000:]
    assert "review" in out.lower(), out[-3000:]

    log_path = results / "NVDA" / "TradingAgentsStrategy_logs" / f"full_states_log_{TRADE_DATE}.json"
    assert log_path.exists(), list(results.rglob("*"))
    log = json.loads(log_path.read_text())
    assert log["final_rating"] == "REVIEW"
    assert log["decision_review_reasons"] == ["missing_entry_price"]


@pytest.mark.unit
def test_a_valid_buy_is_not_reviewed_by_the_cli(tmp_path):
    """REQ-TA-FR-004 (FR004-07 control): the same CLI run with a valid price is
    Buy, with empty review reasons, so the gate does not reject valid inputs."""
    home = tmp_path / "home"
    home.mkdir()
    proc, results, _cache = _run_cli(tmp_path, entry="100", home=home)

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-3000:]
    log_path = results / "NVDA" / "TradingAgentsStrategy_logs" / f"full_states_log_{TRADE_DATE}.json"
    log = json.loads(log_path.read_text())
    assert log["final_rating"] == "Buy"
    assert log["decision_review_reasons"] == []
