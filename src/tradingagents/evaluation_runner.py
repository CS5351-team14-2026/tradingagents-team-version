"""REQ-TA-FR-007 / PERF-001: isolated paired runs via public graph interfaces.

Implements the human-approved evaluation plan; no agent/prompt changes.
"""
from __future__ import annotations

import copy
import threading
from pathlib import Path
from time import perf_counter

from langchain_core.callbacks import BaseCallbackHandler

from tradingagents.evaluation import ComparisonResult, RunMetrics, TokenPricing

CONTROL_KEYS = (
    'llm_provider', 'deep_think_provider', 'quick_think_provider',
    'deep_think_llm', 'quick_think_llm', 'temperature', 'data_vendors',
    'tool_vendors', 'output_language', 'google_thinking_level',
    'openai_reasoning_effort', 'anthropic_effort', 'max_tokens', 'llm_max_retries',
)
SETTING_KEYS = (*CONTROL_KEYS, 'max_debate_rounds', 'max_risk_discuss_rounds',
                'max_tool_rounds', 'analysts', 'profile')
OVERRIDE_KEYS = set(SETTING_KEYS)


class UsageObserver(BaseCallbackHandler):
    """REQ-TA-FR-007: thread-safe, per-call usage; absent is never zero."""

    def __init__(self):
        self.lock = threading.Lock()
        self.started = set()
        self.usage = {}

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        # REQ-TA-FR-007: deduplicate constructor/config callback delivery.
        with self.lock:
            self.started.add(run_id)

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        # REQ-TA-FR-007: identical counting semantics for chat models.
        self.on_llm_start(serialized, messages, run_id=run_id)

    def on_llm_end(self, response, *, run_id, **kwargs):
        # REQ-TA-FR-007: one usage record per observed call.
        try:
            usage = response.generations[0][0].message.usage_metadata or {}
        except (AttributeError, IndexError, TypeError):
            usage = {}
        incoming, outgoing = usage.get('input_tokens'), usage.get('output_tokens')
        valid = all(isinstance(x, int) and not isinstance(x, bool) and x >= 0
                    for x in (incoming, outgoing))
        with self.lock:
            self.started.add(run_id)
            self.usage[run_id] = (incoming, outgoing) if valid else None

    def snapshot(self):
        # REQ-TA-FR-007: incomplete calls invalidate complete totals.
        with self.lock:
            known = [u for u in self.usage.values() if u is not None]
            complete = bool(self.started) and len(known) == len(self.started)
            return {"llm_calls": len(self.started),
                        "tokens_in": sum(u[0] for u in known) if known else None,
                        "tokens_out": sum(u[1] for u in known) if known else None,
                        "usage_complete": complete}


def prepare_configs(defaults, baseline_overrides, enhanced_overrides):
    """REQ-TA-FR-007: two explicit configurations with pinned common controls."""
    configs = []
    for overrides in (baseline_overrides, enhanced_overrides):
        if not isinstance(overrides, dict) or set(overrides) - OVERRIDE_KEYS:
            raise ValueError('configuration contains unsupported fields')
        cfg = copy.deepcopy(defaults)
        cfg.update(copy.deepcopy(overrides))
        from tradingagents.default_config import resolve_profile
        profile = overrides.get('profile')
        explicit = {k: overrides[k] for k in ('analysts', 'max_debate_rounds',
                    'max_risk_discuss_rounds', 'max_tool_rounds') if k in overrides}
        resolved = resolve_profile(profile, explicit=explicit, defaults=cfg)
        cfg.update(resolved.resolved_settings())
        cfg['profile'] = profile
        cfg['evaluation_profile_overrides'] = resolved.overrides
        analysts = cfg.setdefault('analysts', ['market', 'social', 'news', 'fundamentals'])
        if not isinstance(analysts, list) or not analysts or any(
            a not in {'market', 'social', 'news', 'fundamentals'} for a in analysts
        ) or len(set(analysts)) != len(analysts):
            raise ValueError('analysts must be a nonempty unique list of supported analysts')
        for key in ('max_debate_rounds', 'max_risk_discuss_rounds', 'max_tool_rounds'):
            value = cfg.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{key} must be a positive integer')
        configs.append(cfg)
    if any(configs[0].get(k) != configs[1].get(k) for k in CONTROL_KEYS):
        raise ValueError('baseline and enhanced must pin identical model/provider/temperature/vendor controls')
    if configs[0].get('temperature') is None:
        raise ValueError('set an explicit identical temperature in both configurations')
    return configs


def run_comparison(cases, baseline, enhanced, work_dir, repetitions=3,
                   graph_factory=None, clock=perf_counter, pricing=None):
    """REQ-TA-FR-007 / PERF-001: alternate order, isolate state, retain failures.

    Timing includes graph construction, analysis and its normal persistence.
    All cases start from empty private memory and cache; exports are not timed.
    Single-rate pricing applies only when both tiers use the same model/provider.
    """
    cases = tuple(cases)
    if not cases or len(set(cases)) != len(cases):
        raise ValueError('cases must be nonempty and unique')
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 1:
        raise ValueError('repetitions must be a positive integer')
    import os
    if os.environ.get('TRADINGAGENTS_PROFILE') and any(
        cfg.get('profile') is None for cfg in (baseline, enhanced)
    ):
        raise ValueError('unset TRADINGAGENTS_PROFILE to measure a no-profile baseline')
    if any(baseline.get(k) != enhanced.get(k) for k in CONTROL_KEYS):
        raise ValueError('baseline and enhanced controls must match')
    if pricing is not None:
        if not isinstance(pricing, TokenPricing):
            raise ValueError('pricing must be TokenPricing')
        cfg = baseline
        if (cfg.get('deep_think_llm') != cfg.get('quick_think_llm') or
            (cfg.get('deep_think_provider') or cfg.get('llm_provider')) !=
                (cfg.get('quick_think_provider') or cfg.get('llm_provider'))):
            raise ValueError('single-rate pricing requires identical model/provider in both tiers')
    if graph_factory is None:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        graph_factory = TradingAgentsGraph
    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=False)
    runs = []
    for index, case in enumerate(cases):
        for repeat in range(1, repetitions + 1):
            order = [('baseline', baseline), ('enhanced', enhanced)]
            if (index + repeat) % 2 == 0:
                order.reverse()
            for variant, original in order:
                cfg = copy.deepcopy(original)
                folder = root / f'case-{index}-repeat-{repeat}-{variant}'
                cfg.update(results_dir=str(folder / 'results'),
                           data_cache_dir=str(folder / 'cache'),
                           memory_log_path=str(folder / 'memory.md'),
                           checkpoint_enabled=False)
                observer = UsageObserver()
                start = clock()
                state, rating, status, reason = {}, None, 'completed', None
                try:
                    graph_kwargs = {'config': cfg, 'callbacks': [observer]}
                    if original.get('profile') is not None:
                        graph_kwargs.update(profile=original['profile'],
                                            explicit_overrides=original.get('evaluation_profile_overrides', {}))
                    else:
                        graph_kwargs['selected_analysts'] = cfg['analysts']
                    graph = graph_factory(**graph_kwargs)
                    state, rating = graph.propagate(case.ticker, case.analysis_date)
                    if not isinstance(state, dict) or not isinstance(rating, str):
                        raise ValueError('invalid graph result')
                except Exception:
                    # REQ-TA-FR-007: never export raw exceptions carrying credentials.
                    state, rating, status, reason = {}, None, 'failed', 'RUN_ERROR'
                elapsed = clock() - start
                turns = state.get('investment_debate_state', {}).get('count')
                rounds = turns // 2 if isinstance(turns, int) and turns >= 0 and turns % 2 == 0 else None
                runs.append(RunMetrics(case, variant, repeat, elapsed, status=status,
                                       debate_rounds=rounds, recommendation=rating,
                                       confidence=state.get('pm_confidence', state.get('confidence')), pricing=pricing,
                                       failure_reason=reason,
                                       settings={k: copy.deepcopy(original.get(k)) for k in SETTING_KEYS},
                                       **observer.snapshot()))
    return ComparisonResult(runs)
