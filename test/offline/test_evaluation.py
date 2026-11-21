"""REQ-TA-FR-007 / REQ-TA-PERF-001: independent, network-free comparison cases.

Expected percentages and costs are hand-calculated, not computed by the tested
helpers. Formal architecture ADR pending; scope approved in the local plan.
"""

import csv
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from tradingagents.evaluation import (
    ComparisonResult,
    EvaluationCase,
    RunMetrics,
    TokenPricing,
    export_comparison,
    percentage_reduction,
)


def _pair(case=None, **enhanced_changes):
    """REQ-TA-FR-007: one measured pair with a known 25%/50% improvement."""
    case = case or EvaluationCase("AAPL", "2026-01-05")
    baseline = RunMetrics(case, "baseline", 1, 20.0, llm_calls=4,
                          tokens_in=600, tokens_out=200, usage_complete=True,
                          debate_rounds=2, recommendation="Hold")
    enhanced = replace(baseline, variant="enhanced", elapsed_seconds=15.0,
                       tokens_in=300, tokens_out=100, llm_calls=2,
                       debate_rounds=1, **enhanced_changes)
    return baseline, enhanced


def test_comparison_three_cases_and_known_percentages():
    """REQ-TA-FR-007: three cases retain raw runs and hand-checked reductions."""
    runs = [run for ticker in ("AAPL", "NVDA", "0700.HK")
            for run in _pair(EvaluationCase(ticker, "2026-01-05"))]
    result = ComparisonResult(runs)
    assert len(result.runs) == 6
    assert [row["ticker"] for row in result.comparison_rows()] == ["AAPL", "NVDA", "0700.HK"]
    for row in result.comparison_rows():
        assert row["runtime_reduction_percent"] == 25.0
        assert row["token_reduction_percent"] == 50.0
    assert result.to_dict()["performance_target"] == "TBD"
    assert result.to_dict()["runs"][0]["recommendation"] == "Hold"
    assert result.to_dict()["runs"][0]["confidence"] == "unavailable"


@pytest.mark.parametrize(("baseline", "enhanced", "expected"), [
    (20, 30, -50), (20, 20, 0), (20, 0, 100),
    (0, 10, None), (0, 0, None), (None, 3, None), (3, None, None),
])
def test_reduction_boundary_cases(baseline, enhanced, expected):
    """REQ-TA-FR-007: preserve slowdowns and distinguish zero from missing."""
    assert percentage_reduction(baseline, enhanced) == expected


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "20"])
def test_invalid_measurements_rejected(bad):
    """REQ-TA-FR-007: negative test for invalid/unknown measurement encoding."""
    with pytest.raises(ValueError):
        percentage_reduction(bad, 1)
    with pytest.raises(ValueError):
        replace(_pair()[0], elapsed_seconds=bad)


@pytest.mark.parametrize(("incoming", "outgoing", "complete", "total", "usage"), [
    (None, None, False, "unavailable", "unavailable"),
    (100, None, False, "unavailable", "partial"),
    (100, 10, False, "unavailable", "partial"),
    (0, 0, True, 0, "complete"),
])
def test_missing_partial_and_genuine_zero_usage(incoming, outgoing, complete, total, usage):
    """REQ-TA-FR-007: unknown totals must not become zero or an underestimate."""
    baseline, enhanced = _pair()
    enhanced = replace(enhanced, tokens_in=incoming, tokens_out=outgoing, usage_complete=complete)
    data = ComparisonResult((baseline, enhanced)).to_dict()
    assert data["runs"][1]["total_tokens"] == total
    assert data["runs"][1]["usage_status"] == usage
    assert data["runs"][1]["estimated_cost_usd"] == "unavailable"
    assert data["comparisons"][0]["token_reduction_percent"] == (100 if complete else "unavailable")


def test_cost_requires_complete_usage_and_explicit_prices():
    """REQ-TA-FR-007: $2/M * 600 + $8/M * 200 = $0.0028."""
    run = _pair()[0]
    assert run.estimated_cost_usd is None
    priced = replace(run, pricing=TokenPricing(2, 8))
    assert priced.estimated_cost_usd == pytest.approx(0.0028)
    assert replace(priced, usage_complete=False).estimated_cost_usd is None
    assert replace(priced, pricing=TokenPricing(0, 0)).estimated_cost_usd == 0


def test_failed_pair_is_retained_without_speedup_claim():
    """REQ-TA-FR-007 / PERF-001: a fast failure is not a performance gain."""
    baseline, enhanced = _pair()
    failed = replace(enhanced, status="failed", elapsed_seconds=0.01)
    data = ComparisonResult((baseline, failed)).to_dict()
    assert data["runs"][1]["status"] == "failed"
    assert data["runs"][1]["elapsed_seconds"] == 0.01
    assert data["comparisons"][0]["comparison_status"] == "failed_pair"
    assert data["comparisons"][0]["runtime_reduction_percent"] == "unavailable"
    assert data["comparisons"][0]["token_reduction_percent"] == "unavailable"


def test_matching_cases_and_repetitions_are_required():
    """REQ-TA-FR-007: reject mismatched dates, duplicate variants and missing pairs."""
    baseline, enhanced = _pair()
    for runs in ([], [baseline], [baseline, baseline, enhanced],
                 [baseline, replace(enhanced, repetition=2)],
                 [baseline, replace(enhanced, case=EvaluationCase("AAPL", "2026-01-06"))]):
        with pytest.raises(ValueError):
            ComparisonResult(runs)
    two_repeats = ComparisonResult((baseline, enhanced,
                                   replace(baseline, repetition=2), replace(enhanced, repetition=2)))
    assert len(two_repeats.comparison_rows()) == 2


@pytest.mark.parametrize(("field", "value"), [
    ("variant", "quick"), ("repetition", 0), ("repetition", True),
    ("status", "unknown"), ("tokens_in", -1), ("tokens_out", 1.2),
    ("llm_calls", True), ("debate_rounds", -1), ("usage_complete", "yes"),
    ("tokens_in", None), ("confidence", float("nan")),
])
def test_run_contract_rejects_invalid_fields(field, value):
    """REQ-TA-FR-007: enforce the record contract before export."""
    with pytest.raises(ValueError):
        replace(_pair()[0], **{field: value})


@pytest.mark.parametrize(("ticker", "day"), [("", "2026-01-05"), ("AAPL", "2026-1-5"),
                                             ("AAPL", "2026-02-30"), ("AAPL", "20260105")])
def test_invalid_case_rejected(ticker, day):
    """REQ-TA-FR-007: dates are canonical, not silently normalized."""
    with pytest.raises(ValueError):
        EvaluationCase(ticker, day)


def test_inputs_are_immutable_and_list_is_not_retained():
    """REQ-TA-FR-007: comparison must not mutate its source observations."""
    baseline, enhanced = _pair()
    supplied = [baseline, enhanced]
    result = ComparisonResult(supplied)
    supplied.clear()
    assert result.runs == (baseline, enhanced)
    with pytest.raises(FrozenInstanceError):
        baseline.status = "failed"


def test_json_and_csv_round_trip_preserves_measurement_semantics(tmp_path):
    """REQ-TA-FR-007: verify exported files rather than serializer internals."""
    result = ComparisonResult(_pair())
    json_file = export_comparison(result, tmp_path / "评测.json")
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert data["runs"][0]["tokens_in"] == 600
    assert data["runs"][1]["llm_calls"] == 2
    assert data["comparisons"][0]["runtime_reduction_percent"] == 25
    csv_file = export_comparison(result, tmp_path / "evaluation.csv", "csv")
    with csv_file.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[0]["tokens_in"] == "600"
    assert rows[1]["token_reduction_percent"] == "50.0"
    assert rows[1]["confidence"] == "unavailable"
    assert rows[1]["performance_target"] == "TBD"


@pytest.mark.parametrize("format", ["json", "csv"])
def test_export_preserves_existing_files(tmp_path, format):
    """REQ-TA-FR-007: negative test prevents accidental loss of earlier evidence."""
    destination = tmp_path / "existing"
    destination.write_text("previous experiment", encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_comparison(ComparisonResult(_pair()), destination, format)
    assert destination.read_text() == "previous experiment"


def test_invalid_format_creates_no_file(tmp_path):
    """REQ-TA-FR-007: reject unsupported exports before modifying disk."""
    destination = tmp_path / "invalid"
    with pytest.raises(ValueError, match="format"):
        export_comparison(ComparisonResult(_pair()), destination, "xml")
    assert not destination.exists()


@pytest.mark.parametrize("format", ["json", "csv"])
def test_overflow_cannot_export_a_nonfinite_percentage(tmp_path, format):
    """REQ-TA-FR-007: extreme inputs must not leak infinity into either format."""
    baseline, enhanced = _pair()
    result = ComparisonResult((replace(baseline, elapsed_seconds=1e-300),
                               replace(enhanced, elapsed_seconds=1e300)))
    destination = tmp_path / "overflow"
    with pytest.raises(ValueError, match="finite"):
        export_comparison(result, destination, format)
    assert not destination.exists()
