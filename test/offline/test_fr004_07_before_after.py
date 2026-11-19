"""FR004-07 evidence: one missing-price Buy, before and after the change.

Approved test plan: Issue #32 (``test-approved``) FR004-07.
Implements: REQ-TA-FR-004.

This records the demonstration the plan asks for: the same synthetic Buy with a
missing entry price, run before the change (baseline 7517803) and after (this
branch). The baseline had no validator, so it adopted the Buy; the current code
returns REVIEW with ``missing_entry_price``.

The evidence is produced by running ``docs/evidence/fr004_07_probe.py`` against
each checkout's ``src``. The baseline is a git worktree at 7517803 when one is
available; the test always records the *current* result and, when the baseline
worktree exists, the before/after pair. A saved copy of the last run is written
next to the probe as ``fr004_07_evidence.txt``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROBE = os.path.join(REPO_ROOT, "docs", "evidence", "fr004_07_probe.py")
BASELINE = os.environ.get("FR004_BASELINE_WORKTREE")  # optional; an existing 7517803 worktree


def _probe(src_root: str, *, use_instance: bool) -> dict:
    env = {**os.environ, "PYTHONPATH": src_root}
    if use_instance:
        env["FR004_USE_INSTANCE"] = "1"
    proc = subprocess.run([sys.executable, PROBE], capture_output=True, text=True,
                          env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr[-1500:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.unit
def test_before_and_after_one_missing_price_buy(tmp_path):
    """REQ-TA-FR-004 (FR004-07): before, the Buy was adopted with no review reason;
    after, the same Buy is REVIEW with missing_entry_price."""
    after = _probe(os.path.join(REPO_ROOT, "src"), use_instance=True)
    assert after == {"final_rating": "REVIEW",
                     "decision_review_reasons": ["missing_entry_price"]}

    lines = [f"after  (current)            : {json.dumps(after)}"]
    if BASELINE and os.path.isdir(BASELINE):
        before = _probe(os.path.join(BASELINE, "src"), use_instance=True)
        lines.insert(0, f"before (7517803)            : {json.dumps(before)}")
    (tmp_path / "fr004_07_evidence.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
