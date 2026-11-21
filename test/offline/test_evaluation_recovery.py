"""REQ-TA-FR-007: durable paid-run recovery with strict protocol identity."""
import copy
import json

import pytest

from tradingagents.evaluation import EvaluationCase
from tradingagents.evaluation_runner import run_comparison

from .test_evaluation_runner import FakeGraph, configs


class InterruptOnce(FakeGraph):
    """REQ-TA-FR-007: emulate interruption after the first measured run."""
    count = 0
    interrupt = True

    def propagate(self, ticker, day):
        type(self).count += 1
        if type(self).count == 2 and type(self).interrupt:
            type(self).interrupt = False
            raise KeyboardInterrupt()
        return super().propagate(ticker, day)


class FailOnce(FakeGraph):
    """REQ-TA-FR-007: an explicit retry must not erase the failed attempt."""
    count = 0

    def propagate(self, ticker, day):
        type(self).count += 1
        if type(self).count == 2:
            raise ConnectionError('secret-placeholder')
        return super().propagate(ticker, day)


def test_resume_does_not_repeat_completed_paid_run(tmp_path):
    """REQ-TA-FR-007: an interrupted pair resumes only its unfinished side."""
    before, after = configs()
    case = [EvaluationCase('AAPL', '2026-01-05')]
    root = tmp_path / 'run'
    InterruptOnce.count, InterruptOnce.interrupt = 0, True
    with pytest.raises(KeyboardInterrupt):
        run_comparison(case, before, after, root, repetitions=1, graph_factory=InterruptOnce)
    assert len(list((root / 'measurements').glob('*.json'))) == 1
    result = run_comparison(case, before, after, root, repetitions=1,
                            graph_factory=InterruptOnce, resume=True)
    assert InterruptOnce.count == 3
    assert len(result.runs) == 2
    assert all(r.status == 'completed' for r in result.runs)


def test_resume_refuses_changed_settings_before_calls(tmp_path):
    """REQ-TA-PERF-001: changing the experiment cannot silently reuse samples."""
    before, after = configs()
    case = [EvaluationCase('AAPL', '2026-01-05')]
    root = tmp_path / 'run'
    FailOnce.count = 0
    run_comparison(case, before, after, root, repetitions=1, graph_factory=FailOnce)
    changed = copy.deepcopy(before)
    changed['max_tokens'] = after['max_tokens'] = 8192
    with pytest.raises(ValueError, match='identical'):
        run_comparison(case, changed, after, root, repetitions=1,
                       graph_factory=FailOnce, resume=True)
    assert FailOnce.count == 2


def test_explicit_retry_preserves_failure_and_reuses_success(tmp_path):
    """REQ-TA-FR-007: failed attempts persist, completed runs are never re-billed."""
    before, after = configs()
    case = [EvaluationCase('AAPL', '2026-01-05')]
    root = tmp_path / 'run'
    FailOnce.count = 0
    first = run_comparison(case, before, after, root, repetitions=1, graph_factory=FailOnce)
    assert first.summary()['failed_pairs'] == 1
    # --resume alone reports a known failure; it is not consent to another call.
    run_comparison(case, before, after, root, repetitions=1, graph_factory=FailOnce, resume=True)
    assert FailOnce.count == 2
    final = run_comparison(case, before, after, root, repetitions=1,
                           graph_factory=FailOnce, resume=True, retry_failed=True)
    assert FailOnce.count == 3 and final.summary()['failed_pairs'] == 0
    records = [json.loads(p.read_text()) for p in (root / 'measurements').glob('*.json')]
    assert len(records) == 3 and sum(r['status'] == 'failed' for r in records) == 1
    assert 'secret-placeholder' not in json.dumps(records)


def test_resume_rejects_source_fingerprint_mismatch(tmp_path):
    """FR-007 / PERF-001: source revisions must not be mixed into one dataset."""
    before, after = configs()
    root = tmp_path / 'run'
    case = [EvaluationCase('AAPL', '2026-01-05')]
    FailOnce.count = 0
    run_comparison(case, before, after, root, repetitions=1, graph_factory=FailOnce)
    protocol = json.loads((root / 'protocol.json').read_text())
    protocol['source_digest'] = 'old-revision'
    (root / 'protocol.json').write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match='identical'):
        run_comparison(case, before, after, root, repetitions=1,
                       graph_factory=FailOnce, resume=True, retry_failed=True)
    assert FailOnce.count == 2


def test_cli_resume_archives_exports_and_makes_no_new_calls(tmp_path, monkeypatch):
    """FR-007: --resume preserves old exports and does not re-run completed work."""
    from typer.testing import CliRunner

    from cli.main import app
    from tradingagents import evaluation_runner as adapter

    real = adapter.run_comparison
    monkeypatch.setattr(adapter, 'run_comparison',
                        lambda *a, **kw: real(*a, **kw, graph_factory=FakeGraph))
    config, cases, root = tmp_path / 'config.json', tmp_path / 'cases.json', tmp_path / 'out'
    config.write_text(json.dumps({'temperature': 0}))
    cases.write_text(json.dumps([{'ticker': 'AAPL', 'analysis_date': '2026-01-05'}]))
    args = ['compare', '--baseline', str(config), '--enhanced', str(config),
            '--cases', str(cases), '--output', str(root), '--smoke', '--live']
    FakeGraph.instances = []
    first = CliRunner().invoke(app, args)
    assert first.exit_code == 0, first.output
    previous = (root / 'comparison.json').read_text()
    second = CliRunner().invoke(app, [*args, '--resume'])
    assert second.exit_code == 0, second.output
    assert len(FakeGraph.instances) == 2
    assert (root / 'comparison.json').read_text() == previous
    assert len(list((root / 'export-history').iterdir())) == 2
