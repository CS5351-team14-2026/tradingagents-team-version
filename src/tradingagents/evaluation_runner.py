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
from tradingagents.evaluation_checkpoint import RunJournal, experiment_protocol
from tradingagents.llm_clients.usage import normalize_usage

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

    def __init__(self, progress=None):
        self.lock = threading.Lock()
        self.started = set()
        self.usage = {}
        self.timings = {}
        self.progress = progress

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        # REQ-TA-FR-007: deduplicate constructor/config callback delivery.
        with self.lock:
            self.started.add(run_id)
            self.timings.setdefault(run_id, {"start": perf_counter(), "status": "pending"})
            calls = len(self.started)
        if self.progress:
            self.progress({"event": "llm_start", "calls": calls})

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        # REQ-TA-FR-007: identical counting semantics for chat models.
        self.on_llm_start(serialized, messages, run_id=run_id)

    def on_llm_end(self, response, *, run_id, **kwargs):
        # REQ-TA-FR-007: one usage record per observed call.
        observation = normalize_usage(response)
        incoming, outgoing = observation.tokens_in, observation.tokens_out
        valid = observation.state == 'complete'
        with self.lock:
            self.started.add(run_id)
            self.usage[run_id] = (incoming, outgoing) if valid else None
            item = self.timings.setdefault(run_id, {"start": perf_counter()})
            item.update(status="completed", seconds=perf_counter() - item['start'],
                        usage_status=observation.state)
            # REQ-TA-PERF-001: safe termination metadata, never model text.
            try:
                metadata = response.generations[0][0].message.response_metadata
            except (AttributeError, IndexError, TypeError):
                metadata = {}
            finish = metadata.get('finish_reason') if isinstance(metadata, dict) else None
            if finish in {'stop', 'length', 'tool_calls', 'content_filter'}:
                item['finish_reason'] = finish
        if self.progress:
            self.progress({"event": "llm_end", "calls": len(self.started), "seconds": item['seconds']})

    def on_llm_error(self, error, *, run_id, **kwargs):
        """REQ-TA-FR-007: expose safe failure timing, never raw exception text."""
        with self.lock:
            self.started.add(run_id)
            self.usage[run_id] = None
            item = self.timings.setdefault(run_id, {"start": perf_counter()})
            item.update(status="failed", seconds=perf_counter() - item['start'], error_type=type(error).__name__)
            code = getattr(error, 'status_code', None)
            if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
                item['http_status'] = code
        if self.progress:
            self.progress({"event": "llm_error", "error_type": type(error).__name__})

    def diagnostics(self):
        """REQ-TA-PERF-001: call timings can overlap; do not sum as wall time."""
        with self.lock:
            return {"calls": [{k: v for k, v in item.items() if k != 'start'}
                              for item in self.timings.values()]}

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
                   graph_factory=None, clock=perf_counter, pricing=None, progress=None,
                   resume=False, retry_failed=False):
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
    if retry_failed and not resume:
        raise ValueError('retry-failed requires explicit resume')
    root = Path(work_dir)
    protocol = experiment_protocol(cases, baseline, enhanced, repetitions, pricing, graph_factory)
    with RunJournal(root, protocol, resume=resume) as journal:
        return _run_cases(cases, baseline, enhanced, root, repetitions, graph_factory,
                          clock, pricing, progress, journal, retry_failed)


def _run_cases(cases, baseline, enhanced, root, repetitions, graph_factory,
               clock, pricing, progress, journal, retry_failed):
    """REQ-TA-FR-007: resume completed observations, retain every failed attempt."""
    runs = []
    for index, case in enumerate(cases):
        for repeat in range(1, repetitions + 1):
            order = [('baseline', baseline), ('enhanced', enhanced)]
            if (index + repeat) % 2 == 0:
                order.reverse()
            for variant, original in order:
                key = f'case-{index}-repeat-{repeat}-{variant}'
                previous, attempts = journal.previous(key)
                if previous is not None:
                    if previous.case != case or previous.variant != variant or previous.repetition != repeat:
                        raise ValueError('checkpoint identity mismatch')
                    if previous.status == 'completed' or not retry_failed:
                        runs.append(previous)
                        if progress:
                            progress({"event": "run_resumed", "ticker": case.ticker,
                                      "variant": variant, "status": previous.status})
                        continue
                cfg = copy.deepcopy(original)
                folder = root / (key if not attempts else f'{key}-attempt-{attempts + 1}')
                cfg.update(results_dir=str(folder / 'results'),
                           data_cache_dir=str(folder / 'cache'),
                           memory_log_path=str(folder / 'memory.md'),
                           checkpoint_enabled=False)
                observer = UsageObserver(progress=progress)
                if progress:
                    progress({"event": "run_start", "ticker": case.ticker, "variant": variant, "repetition": repeat})
                start = clock()
                state, rating, status, reason = {}, None, 'completed', None
                error_type = None
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
                    # FR-007 / PERF-001 / QR-001: controlled failures return
                    # REVIEW without raising. Read the public canonical record;
                    # never count these short runs as performance successes.
                    settings_reader = getattr(graph, 'run_settings', None)
                    record = settings_reader() if callable(settings_reader) else {}
                    metadata = record.get('run_metadata', {}) if isinstance(record, dict) else {}
                    if not isinstance(metadata, dict):
                        metadata = {}
                    if (metadata.get('status') == 'failed' or state.get('run_failure')
                            or metadata.get('failure')):
                        status, reason = 'failed', 'CONTROLLED_FAILURE'
                except Exception as exc:
                    error_type = type(exc).__name__
                    # REQ-TA-FR-007: never export raw exceptions carrying credentials.
                    state, rating, status, reason = {}, None, 'failed', 'RUN_ERROR'
                elapsed = clock() - start
                turns = state.get('investment_debate_state', {}).get('count')
                rounds = turns // 2 if isinstance(turns, int) and turns >= 0 and turns % 2 == 0 else None
                acceptance = state.get('claim_acceptance') or {}
                if not isinstance(acceptance, dict):
                    acceptance = {}
                observed_settings = {k: copy.deepcopy(original.get(k)) for k in SETTING_KEYS}
                if status == 'completed' and hasattr(graph, 'profile_resolution'):
                    observed_settings.update(graph.profile_resolution.resolved_settings())
                runs.append(RunMetrics(case, variant, repeat, elapsed, status=status,
                                       debate_rounds=rounds, recommendation=rating,
                                       confidence=state.get('pm_confidence', state.get('confidence')), pricing=pricing,
                                       failure_reason=reason,
                                       acceptance_status=acceptance.get('status', 'NOT_ASSESSED'),
                                       acceptance_reasons=tuple(acceptance.get('reasons') or ()),
                                       diagnostics={**observer.diagnostics(),
                                                    "run_error_type": error_type,
                                                    "decision_review_reasons": state.get('decision_review_reasons', [])},
                                       settings=observed_settings,
                                       **observer.snapshot()))
                journal.save(key, attempts + 1, runs[-1])
                if progress:
                    progress({"event": "run_end", "ticker": case.ticker, "variant": variant,
                              "status": status, "seconds": elapsed, "acceptance": acceptance.get('status', 'NOT_ASSESSED')})
    return ComparisonResult(runs)
