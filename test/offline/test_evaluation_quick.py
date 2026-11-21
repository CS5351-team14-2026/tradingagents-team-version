"""REQ-TA-FR-007 / PERF-001: Quick trial using real graph and scripted providers."""
import pytest

from tradingagents.default_config import DEFAULT_CONFIG, resolve_profile
from tradingagents.evaluation import EvaluationCase, export_comparison
from tradingagents.evaluation_runner import prepare_configs, run_comparison


def test_quick_resolution_and_override():
    """Use FR-001 mapping, preserve explicit overrides, leave baseline unchanged."""
    before, quick = prepare_configs(DEFAULT_CONFIG, {'temperature': 0},
                                    {'temperature': 0, 'profile': 'quick'})
    assert before['profile'] is None
    assert quick['analysts'] == ['market', 'news']
    assert quick['max_tool_rounds'] == 3
    assert quick['evaluation_profile_overrides'] == {}
    _, override = prepare_configs(DEFAULT_CONFIG, {'temperature': 0},
                                  {'temperature': 0, 'profile': 'quick', 'max_tool_rounds': 2})
    assert override['max_tool_rounds'] == 2
    assert override['evaluation_profile_overrides'] == {'max_tool_rounds': 2}
    with pytest.raises(ValueError):
        prepare_configs(DEFAULT_CONFIG, {'temperature': 0}, {'profile': 'unknown'})


def test_quick_real_graph_trial(tmp_path, monkeypatch):
    """Real LangGraph orchestration; simulated LLM/data, NOT performance evidence."""
    from offline import test_graph_end_to_end as upstream
    from tradingagents.graph import trading_graph

    # Reuse teammate's deterministic provider/data setup, without changing it.
    data_calls = upstream.offline.__wrapped__(monkeypatch, tmp_path)
    model = upstream.ScriptedModel(structured=True)
    monkeypatch.setattr(trading_graph, 'create_tier_client',
                        lambda *a, **kw: upstream._Client(model))
    before, quick = prepare_configs(DEFAULT_CONFIG, {'temperature': 0},
                                    {'temperature': 0, 'profile': 'quick'})
    instances = []
    def factory(**kwargs):
        graph = trading_graph.TradingAgentsGraph(**kwargs)
        if kwargs.get('profile') == 'quick':
            assert graph.profile_resolution.resolved_settings() == resolve_profile('quick').resolved_settings()
        instances.append(graph)
        return graph
    result = run_comparison([EvaluationCase('NVDA', upstream.TRADE_DATE)], before, quick,
                            tmp_path / 'trial', repetitions=1, graph_factory=factory)
    assert all(r.status == 'completed' for r in result.runs)
    assert result.runs[1].settings['profile'] == 'quick'
    assert model.calls and data_calls
    assert len(instances) == 2
    assert result.summary()['target_verdict'] == 'not_assessed'
    export_comparison(result, tmp_path / 'trial.json')
