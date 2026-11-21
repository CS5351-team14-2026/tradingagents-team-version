"""REQ-TA-FR-007 / PERF-001: QR-001 failures must never become fast successes."""
import json

import pytest

from offline.test_evaluation_runner import FakeGraph, configs
from tradingagents.evaluation import EvaluationCase
from tradingagents.evaluation_runner import run_comparison
from tradingagents.failure import FailureCode


@pytest.mark.parametrize('code', list(FailureCode))
@pytest.mark.parametrize('location', ['state', 'metadata', 'lifecycle'])
def test_controlled_failure_is_retained_and_excluded(tmp_path, code, location):
    """FR-007 / PERF-001 / QR-001: REVIEW return is not execution success."""
    class Controlled(FakeGraph):
        def propagate(self, ticker, day):
            state, _ = super().propagate(ticker, day)
            if location == 'state':
                state['run_failure'] = {'code': code.value, 'diagnostic': 'private-provider-text'}
            return state, 'REVIEW'

        def run_settings(self):
            return {'run_metadata': {
                'status': 'failed' if location == 'lifecycle' else 'completed',
                'failure': {'code': code.value, 'diagnostic': 'private-provider-text'}
                if location == 'metadata' else None,
            }}

    before, after = configs()
    result = run_comparison([EvaluationCase('AAPL', '2026-01-05')], before, after,
                            tmp_path / 'controlled', repetitions=1, graph_factory=Controlled)
    assert len(result.runs) == 2
    assert all(r.status == 'failed' and r.failure_reason == 'CONTROLLED_FAILURE'
               for r in result.runs)
    assert all(r.total_tokens == 120 for r in result.runs)
    assert result.summary()['failed_pairs'] == 1
    assert result.summary()['successful_pairs'] == 0
    assert result.summary()['median_runtime_reduction_percent'] == 'unavailable'
    assert 'private-provider-text' not in json.dumps(result.to_dict())


def test_review_without_execution_failure_stays_completed(tmp_path):
    """FR-007 / QR-001: report rejection alone does not invent a graph failure."""
    class Review(FakeGraph):
        def propagate(self, ticker, day):
            state, _ = super().propagate(ticker, day)
            state['claim_acceptance'] = {'status': 'REJECTED', 'reasons': ['NO_DATED_OBSERVATION']}
            return state, 'REVIEW'

    before, after = configs()
    result = run_comparison([EvaluationCase('AAPL', '2026-01-05')], before, after,
                            tmp_path / 'review', repetitions=1, graph_factory=Review)
    assert all(r.status == 'completed' for r in result.runs)
    assert result.summary()['successful_pairs'] == 1
    assert result.summary()['accepted_report_pairs'] == 0


def test_real_graph_controlled_timeout_persists_observed_usage(tmp_path, monkeypatch):
    """FR-007 / QR-001 / QR-004: timeout persistence keeps actual partial usage."""
    from offline import test_qr001_provider_timeout as upstream

    upstream.offline.__wrapped__(monkeypatch, tmp_path)

    class MeteredTimeout(upstream._TimeoutModel):
        def _generate(self, *args, **kwargs):
            response = super()._generate(*args, **kwargs)
            response.generations[0].message.usage_metadata = {
                'input_tokens': 2, 'output_tokens': 1, 'total_tokens': 3}
            return response

    model = MeteredTimeout(structured=True, fail_at=10)
    graph = upstream._graph(tmp_path, monkeypatch, model, checkpoint_enabled=False)
    state, rating = graph.propagate('NVDA', upstream.TRADE_DATE)
    assert rating == 'REVIEW' and state['run_failure']['code'] == 'PROVIDER_TIMEOUT'
    paths = list((tmp_path / 'r').rglob('run_record_*.json'))
    assert len(paths) == 1
    metadata = json.loads(paths[0].read_text())['run_metadata']
    assert metadata['status'] == 'failed'
    assert metadata['failure']['code'] == 'PROVIDER_TIMEOUT'
    assert metadata['llm_calls'] > 1
    assert metadata['tokens_in'] > 0 and metadata['tokens_out'] > 0
    assert metadata['usage_complete'] is False  # failed call cannot invent usage
