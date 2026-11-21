"""REQ-TA-FR-007/PERF-001: durable measurements and fail-closed experiment resume.

Only allowlisted RunMetrics leave the runner. Configuration/source fingerprints
must match before any resumed provider call; every failed attempt stays on disk.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from tradingagents.evaluation import EvaluationCase, RunMetrics, TokenPricing


def experiment_protocol(cases, baseline, enhanced, repetitions, pricing, factory):
    """REQ-TA-FR-007: compare full inputs by digest without publishing paths/URLs."""
    source_root = Path(__file__).resolve().parents[1]
    sources = {str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest()
               for package in ('tradingagents', 'cli')
               for p in sorted((source_root / package).rglob('*.py'))}
    try:
        factory_file = inspect.getsourcefile(factory)
    except TypeError:
        factory_file = None
    if factory_file:
        sources['factory'] = hashlib.sha256(Path(factory_file).read_bytes()).hexdigest()
    inputs = {'cases': [asdict(c) for c in cases], 'baseline': baseline, 'enhanced': enhanced,
              'repetitions': repetitions, 'pricing': asdict(pricing) if pricing else None,
              'factory': f'{factory.__module__}.{factory.__qualname__}'}
    return {'version': 1,
            'input_digest': hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest(),
            'source_digest': hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()}


def restore_measurement(data):
    """REQ-TA-FR-007: revalidate persisted data, including missing-usage semantics."""
    data = dict(data)
    data['case'] = EvaluationCase(**data['case'])
    data['pricing'] = TokenPricing(**data['pricing']) if data.get('pricing') is not None else None
    data['acceptance_reasons'] = tuple(data.get('acceptance_reasons', ()))
    return RunMetrics(**data)


class RunJournal:
    """REQ-TA-FR-007: atomic per-run records; never repeat a completed run."""

    def __init__(self, root, protocol, resume=False):
        self.root = Path(root)
        self.protocol = protocol
        self.resume = resume
        self.lock = self.root / '.evaluation.lock'
        self.records = self.root / 'measurements'

    def __enter__(self):
        """REQ-TA-FR-007: validate provenance and exclude concurrent paid resume."""
        if self.root.exists():
            if not self.resume:
                raise ValueError('output directory already exists')
            path = self.root / 'protocol.json'
            if not path.is_file() or json.loads(path.read_text()) != self.protocol:
                raise ValueError('resume requires identical source, cases, settings and pricing')
        else:
            self.root.mkdir(parents=True)
            with (self.root / 'protocol.json').open('x', encoding='utf-8') as handle:
                json.dump(self.protocol, handle, indent=2)
        if self.lock.exists():
            try:
                pid = int(self.lock.read_text())
                if pid <= 0:
                    raise ValueError('invalid evaluation lock')
                os.kill(pid, 0)
            except ProcessLookupError:
                self.lock.unlink()
            else:
                raise ValueError('another evaluation process owns this directory')
        with self.lock.open('x') as handle:
            handle.write(str(os.getpid()))
        self.records.mkdir(exist_ok=True)
        return self

    def __exit__(self, *args):
        """REQ-TA-FR-007: release ownership even on interruption or export failure."""
        self.lock.unlink(missing_ok=True)

    def previous(self, key):
        """REQ-TA-FR-007: return the latest attempt; invalid records fail closed."""
        files = sorted(self.records.glob(f'{key}-a*.json'))
        return (restore_measurement(json.loads(files[-1].read_text())), len(files)) if files else (None, 0)

    def save(self, key, attempt, run):
        """REQ-TA-FR-007: fsync then publish one complete record, outside timed work."""
        target = self.records / f'{key}-a{attempt:06d}.json'
        if target.exists():
            raise ValueError('measurement attempt already exists')
        temporary = self.records / f'.{key}-{uuid4().hex}.tmp'
        try:
            with temporary.open('x', encoding='utf-8') as handle:
                json.dump(asdict(run), handle, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
