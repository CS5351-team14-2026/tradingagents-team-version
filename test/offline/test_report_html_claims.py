"""The HTML report's evidence ledger: source links, dates, UNSUPPORTED badge."""

import pytest

from tradingagents.reporting import write_report_tree


def _state(**overrides):
    state = {
        "trade_date": "2026-11-14",
        "market_report": "Market report.",
        "news_report": "News report.",
        "trader_investment_plan": "Trader plan.",
        "final_trade_decision": "**Rating**: Overweight\n\nAdd on weakness.",
        "final_rating": "Overweight",
        "material_claims": [
            {"kind": "supporting", "text": "Close was 181.2.",
             "source_id": "market_report", "observation_date": "2026-11-14"},
            {"kind": "supporting", "text": "News flow improved.", "source_id": "news_report"},
            {"kind": "opposing", "text": "Trader cautious.",
             "source_id": "trader_investment_plan"},
        ],
    }
    state.update(overrides)
    return state


def _page(tmp_path, **overrides):
    write_report_tree(_state(**overrides), "NVDA", tmp_path)
    return (tmp_path / "complete_report.html").read_text(encoding="utf-8")


@pytest.mark.unit
def test_each_material_claim_shows_its_source_in_the_page(tmp_path):
    page = _page(tmp_path)

    assert "Evidence Linkage" in page
    assert 'id="claim-s1"' in page and 'id="claim-o1"' in page
    assert "market_report" in page and "Market Analyst" in page
    assert '<a href="#s1-1">Market Analyst</a>' in page
    assert '<time datetime="2026-11-14">2026-11-14</time>' in page


@pytest.mark.unit
def test_the_page_records_the_traceability_status(tmp_path):
    page = _page(tmp_path)

    assert "Traceability" in page and "ACCEPTED" in page
    assert "3/3 claims attributed" in page


@pytest.mark.unit
def test_the_page_marks_unsupported_claims(tmp_path):
    claims = _state()["material_claims"]
    claims[0] = {**claims[0], "source_id": "podcast_transcript"}
    page = _page(tmp_path, material_claims=claims)

    assert "DOWNGRADED" in page
    assert 'class="unsupported">UNSUPPORTED</span>' in page
    assert "UNKNOWN_SOURCE" in page


@pytest.mark.unit
def test_the_page_escapes_claim_text(tmp_path):
    claims = [{"kind": "supporting", "text": "<b>claim</b>",
               "source_id": "market_report", "observation_date": "2026-11-14"}]
    page = _page(tmp_path, material_claims=claims)

    assert "<b>claim</b>" not in page and "&lt;b&gt;claim&lt;/b&gt;" in page
