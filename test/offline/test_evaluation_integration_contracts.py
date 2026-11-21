"""FR-007 integration regressions grounded in the real PERF-001 failures."""
import copy
import json

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas import PortfolioDecision


@pytest.mark.parametrize('field', ['supporting_factors', 'opposing_factors'])
def test_claim_schema_rejects_four_factors_without_dropping_them(field):
    """ADR-001 / FR-005 / INV-005: enforce the existing three-per-side limit."""
    payload = {'rating': 'Hold', 'confidence': 'medium', 'executive_summary': 'Wait.',
               'investment_thesis': 'Mixed evidence.', field: [
                   {'text': f'Claim {i}', 'source_id': 'market_report',
                    'observation_date': '2026-01-05'} for i in range(4)]}
    with pytest.raises(ValidationError):
        PortfolioDecision.model_validate(payload)
    assert len(payload[field]) == 4  # never silently trim an inconvenient claim
    assert PortfolioDecision.model_json_schema()['properties'][field]['maxItems'] == 3
    payload[field] = payload[field][:3]
    assert len(getattr(PortfolioDecision.model_validate(payload), field)) == 3


@pytest.mark.parametrize('caller_stats', [False, True])
def test_real_graph_persists_usage_before_writing_state(tmp_path, monkeypatch, caller_stats):
    """QR-004 / FR-002 / FR-007: direct and CLI-style callers persist real usage."""
    from cli.stats_handler import StatsCallbackHandler
    from offline import test_graph_end_to_end as upstream
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph import trading_graph

    upstream.offline.__wrapped__(monkeypatch, tmp_path)

    class Metered(upstream.ScriptedModel):
        def _generate(self, *args, **kwargs):
            result = super()._generate(*args, **kwargs)
            result.generations[0].message.usage_metadata = {
                'input_tokens': 2, 'output_tokens': 1, 'total_tokens': 3}
            return result

    def client(config, tier, **kwargs):
        return upstream._Client(Metered(structured=True, callbacks=kwargs.get('callbacks')))

    monkeypatch.setattr(trading_graph, 'create_tier_client', client)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / 'results'), data_cache_dir=str(tmp_path / 'cache'),
               memory_log_path=str(tmp_path / 'memory.md'), checkpoint_enabled=False,
               token_budget=None)
    stats = StatsCallbackHandler() if caller_stats else None
    graph = trading_graph.TradingAgentsGraph(config=cfg, profile='quick',
                                             callbacks=[stats] if stats else None)
    graph.propagate('NVDA', upstream.TRADE_DATE)
    files = list((tmp_path / 'results').rglob('full_states_log*.json'))
    assert len(files) == 1
    metadata = json.loads(files[0].read_text())['run_settings']['run_metadata']
    assert metadata['usage_complete']
    assert metadata['llm_calls'] > 0
    assert metadata['total_tokens'] == 3 * metadata['llm_calls']
    assert metadata['tokens_in'] == 2 * metadata['llm_calls']
    if stats:
        assert metadata['llm_calls'] == stats.get_stats()['llm_calls']
        assert metadata['tool_calls'] == stats.get_stats()['tool_calls']


@pytest.mark.parametrize('structured', [True, False])
def test_confidence_is_reported_from_typed_decision_only(structured):
    """FR-007: export a real typed confidence, never infer it from fallback prose."""
    from offline import test_decision_validation_routes as routes

    model = routes._RouteModel(
        schema_replies=(routes._mapping(confidence='high'),) if structured else ('raise', 'raise'),
        json_replies=('raise',),
        plain_reply='**Rating**: Hold\n**Confidence**: high',
    )
    result = routes._run(model)
    assert result['pm_confidence'] == ('high' if structured else None)
