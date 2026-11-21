"""Default-selection collection rules (REQ-TA-QR-005, QR005-01).

The offline suite is what CI blocks on: it must select the deterministic cases
under ``test/offline/`` and exclude ``integration`` cases. These checks run a
real ``--collect-only`` from the repository root so they observe the same
selection the default ``pytest`` invocation uses.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _collect(paths: list[str]) -> list[str]:
    """Return the node IDs a default ``pytest --collect-only`` selects."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [line for line in result.stdout.splitlines() if "::" in line]


@pytest.mark.unit
def test_default_selection_includes_the_offline_suite():
    """QR005-01: collecting ``test/offline`` yields offline node IDs (the suite
    CI blocks on), not an empty or live set."""
    node_ids = _collect(["test/offline"])

    assert node_ids
    assert all(node.startswith("test/offline/") for node in node_ids)


@pytest.mark.unit
def test_default_selection_excludes_integration_cases():
    """QR005-01: a case marked ``integration`` is deselected by the default
    ``-m "not integration"`` selection, so the offline run stays network-free.

    ``test/offline/test_deepseek_reasoning.py`` carries the one integration-marked
    class in the offline tree; it must not appear in a default collection.
    """
    node_ids = _collect(["test/offline/test_deepseek_reasoning.py"])

    assert node_ids
    assert not any("TestDeepSeekLiveStructuredOutput" in node for node in node_ids)


@pytest.mark.unit
def test_this_requirements_own_offline_cases_are_selected():
    """QR005-01: the tests written for this requirement live under ``test/offline``
    and are picked up by the default selection."""
    node_ids = _collect([
        "test/offline/test_suite_isolation.py",
        "test/offline/test_seeded_order_plugin.py",
        "test/offline/test_offline_selection.py",
    ])

    assert any("test_suite_isolation.py" in node for node in node_ids)
    assert any("test_seeded_order_plugin.py" in node for node in node_ids)
