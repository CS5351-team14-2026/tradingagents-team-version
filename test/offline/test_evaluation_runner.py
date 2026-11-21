"""REQ-TA-FR-007 / PERF-001: real adapter tested with deterministic fake graph."""
import copy
import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from tradingagents.evaluation import EvaluationCase
from tradingagents.evaluation_runner import UsageObserver, prepare_configs, run_comparison


class FakeGraph:
    """REQ-TA-FR-007: provider substitute; records isolation and callback traffic."""
    instances = []

    def __init__(self, selected_analysts, config, callbacks):
        self.config, self.observer = config, callbacks[0]
        self.instances.append(self)

    def propagate(self, ticker, day):
        self.observer.on_llm_start({}, [], run_id='call')
        self.observer.on_llm_end(SimpleNamespace(generations=[[SimpleNamespace(
            message=SimpleNamespace(usage_metadata={'input_tokens': 100, 'output_tokens': 20}))]]), run_id='call')
        return {'investment_debate_state': {'count': 2}}, 'Hold'


def configs():
    """REQ-TA-FR-007: fixed models, explicit temperature, differing rounds."""
    from tradingagents.default_config import DEFAULT_CONFIG
    return prepare_configs(DEFAULT_CONFIG, {'temperature': 0},
                           {'temperature': 0, 'max_debate_rounds': 1})


def test_three_cases_repeated_and_isolated(tmp_path):
    """REQ-TA-FR-007 / PERF-001: 18 runs, real callback plumbing, no shared memory."""
    before, after = configs()
    saved = copy.deepcopy((before, after))
    FakeGraph.instances = []
    ticks = iter(range(36))
    cases = [EvaluationCase(t, '2026-01-05') for t in ['AAPL', 'NVDA', '0700.HK']]
    result = run_comparison(cases, before, after, tmp_path / 'experiment',
                            graph_factory=FakeGraph, clock=lambda: next(ticks))
    assert len(result.runs) == 18
    assert result.summary()['successful_pairs'] == 9
    assert result.summary()['baseline']['median_seconds'] == 1
    assert result.summary()['median_runtime_reduction_percent'] == 0
    assert all(r.total_tokens == 120 and r.debate_rounds == 1 for r in result.runs)
    assert len({g.config['memory_log_path'] for g in FakeGraph.instances}) == 18
    assert (before, after) == saved
    assert 'backend_url' not in result.to_dict()['runs'][0]['settings']


def test_missing_partial_duplicate_usage():
    """REQ-TA-FR-007: callbacks cannot hide missing telemetry or double-count."""
    observer = UsageObserver()
    observer.on_llm_start({}, [], run_id='a')
    observer.on_chat_model_start({}, [], run_id='a')
    assert observer.snapshot()['llm_calls'] == 1
    assert not observer.snapshot()['usage_complete']
    response = SimpleNamespace(generations=[[SimpleNamespace(message=SimpleNamespace(
        usage_metadata={'input_tokens': 0, 'output_tokens': 0}))]])
    observer.on_llm_end(response, run_id='a')
    assert observer.snapshot()['usage_complete']
    observer.on_llm_start({}, [], run_id='b')
    assert not observer.snapshot()['usage_complete']


def test_failures_retained_without_credentials(tmp_path):
    """REQ-TA-FR-007: failure is not a fast success or a raw exception export."""
    class Broken:
        def __init__(self, **kwargs):
            raise RuntimeError('secret-placeholder')
    before, after = configs()
    result = run_comparison([EvaluationCase('AAPL', '2026-01-05')], before, after,
                            tmp_path / 'fail', graph_factory=Broken, repetitions=1)
    assert result.summary()['failed_pairs'] == 1
    assert result.summary()['baseline']['samples'] == 0
    assert 'secret-placeholder' not in json.dumps(result.to_dict())


@pytest.mark.parametrize('overrides', [{'unknown': 1}, {'temperature': 1},
                                      {'analysts': []}, {'max_tool_rounds': 0}])
def test_invalid_or_unfair_configs(overrides):
    """REQ-TA-FR-007: reject uncontrolled comparisons before calling providers."""
    from tradingagents.default_config import DEFAULT_CONFIG
    with pytest.raises(ValueError):
        prepare_configs(DEFAULT_CONFIG, {'temperature': 0}, overrides)


def test_cli_no_live_means_no_calls():
    """REQ-TA-FR-007: explicit acknowledgement required before any file/provider use."""
    from cli.main import app
    result = CliRunner().invoke(app, ['compare', '--cases', 'missing', '--baseline', 'missing',
                                     '--enhanced', 'missing', '--output', 'missing'])
    assert result.exit_code == 1 and 'No calls made' in result.output


def test_cli_exports_three_cases(tmp_path, monkeypatch):
    """REQ-TA-FR-007: CLI through the public runner and actual serializers."""
    import tradingagents.evaluation_runner as adapter
    from cli.main import app
    real = adapter.run_comparison
    def fake(*args, **kwargs):
        return real(*args, **kwargs, graph_factory=FakeGraph)
    monkeypatch.setattr(adapter, 'run_comparison', fake)
    case_file, config = tmp_path / 'cases.json', tmp_path / 'config.json'
    case_file.write_text(json.dumps([{'ticker': t, 'analysis_date': '2026-01-05'}
                                    for t in ['AAPL', 'NVDA', '0700.HK']]))
    config.write_text(json.dumps({'temperature': 0}))
    output = tmp_path / 'output'
    args = ['compare', '--cases', str(case_file), '--baseline', str(config),
            '--enhanced', str(config), '--output', str(output), '--live']
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert len(json.loads((output / 'comparison.json').read_text())['runs']) == 18
    assert (output / 'comparison.csv').exists()
    assert CliRunner().invoke(app, args).exit_code == 1


def test_summary_uses_only_successful_pairs():
    """REQ-TA-PERF-001: hand-calculated medians and explicit failure accounting."""
    from tradingagents.evaluation import ComparisonResult, RunMetrics
    case = EvaluationCase('AAPL', '2026-01-05')
    result = ComparisonResult([
        RunMetrics(case, 'baseline', 1, 1), RunMetrics(case, 'enhanced', 1, 2),
        RunMetrics(case, 'baseline', 2, 3), RunMetrics(case, 'enhanced', 2, 4),
        RunMetrics(case, 'baseline', 3, 100), RunMetrics(case, 'enhanced', 3, 0, status='failed'),
    ])
    summary = result.summary()
    assert summary['baseline']['median_seconds'] == 2
    assert summary['enhanced']['median_seconds'] == 3
    assert summary['median_runtime_reduction_percent'] == -50
    assert summary['failed_pairs'] == 1
    assert summary['target_verdict'] == 'not_assessed'


def test_missing_usage_and_invalid_graph_result(tmp_path):
    """REQ-TA-FR-007: malformed upstream output does not crash a batch."""
    class Invalid:
        def __init__(self, **kwargs):
            pass
        def propagate(self, *args):
            return None, None
    before, after = configs()
    result = run_comparison([EvaluationCase('AAPL', '2026-01-05')], before, after,
                            tmp_path / 'invalid', graph_factory=Invalid, repetitions=1)
    assert all(r.failure_reason == 'RUN_ERROR' for r in result.runs)
    assert all(r.total_tokens is None for r in result.runs)


def test_pricing_refuses_mixed_model_tiers(tmp_path):
    """REQ-TA-FR-007: cannot apply one fabricated price to multiple models."""
    from tradingagents.evaluation import TokenPricing
    before, after = configs()
    before['deep_think_llm'] = after['deep_think_llm'] = 'model-a'
    before['quick_think_llm'] = after['quick_think_llm'] = 'model-b'
    with pytest.raises(ValueError, match='single-rate'):
        run_comparison([EvaluationCase('AAPL', '2026-01-05')], before, after,
                       tmp_path / 'price', pricing=TokenPricing(1, 2))
    assert not (tmp_path / 'price').exists()
