"""REQ-TA-FR-005: every rendered report carries the "not investment advice" notice."""

import pytest

from tradingagents.reporting import NOT_INVESTMENT_ADVICE, write_report_tree


def _state(**overrides):
    state = {
        "trade_date": "2026-11-14",
        "market_report": "Market report.",
        "final_trade_decision": "**Rating**: Overweight\n\nAdd on weakness.",
        "final_rating": "Overweight",
    }
    state.update(overrides)
    return state


@pytest.mark.unit
def test_the_markdown_report_contains_the_not_investment_advice_notice(tmp_path):
    report = write_report_tree(_state(), "NVDA", tmp_path).read_text(encoding="utf-8")

    assert NOT_INVESTMENT_ADVICE in report
    assert "not investment advice" in report.lower()


@pytest.mark.unit
def test_the_html_report_contains_the_not_investment_advice_notice(tmp_path):
    write_report_tree(_state(), "NVDA", tmp_path)
    page = (tmp_path / "complete_report.html").read_text(encoding="utf-8")

    assert NOT_INVESTMENT_ADVICE in page
    assert 'class="disclaimer"' in page


@pytest.mark.unit
def test_the_notice_is_present_when_no_decision_could_be_read(tmp_path):
    write_report_tree({}, "NVDA", tmp_path)

    assert NOT_INVESTMENT_ADVICE in (tmp_path / "complete_report.md").read_text(encoding="utf-8")
    assert NOT_INVESTMENT_ADVICE in (tmp_path / "complete_report.html").read_text(
        encoding="utf-8")


@pytest.mark.unit
def test_the_ledger_text_cannot_inject_markup(tmp_path):
    claims = [
        {"kind": "supporting", "text": "<script>alert(1)</script>",
         "source_id": "market_report", "observation_date": "2026-11-14"},
    ]
    write_report_tree(_state(material_claims=claims), "NVDA", tmp_path)
    page = (tmp_path / "complete_report.html").read_text(encoding="utf-8")

    assert "<script>alert" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
