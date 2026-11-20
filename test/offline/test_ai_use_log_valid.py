"""The AI-use log must stay valid YAML (REQ gate 6; guards against bad merges).

``docs/ai-use-log.yaml`` is a YAML *list of mappings*. A bad merge (historically
``merge=union``, which concatenates lines and interleaves multi-line entries) can
leave a bare line with no ``key:`` and break ``yaml.safe_load`` — which is exactly
what failed gate 6 in CI. This offline test runs the same structural validator on
the committed file, so a corrupted log fails the normal suite before merge.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_LOG = _ROOT / "docs" / "ai-use-log.yaml"
_VALIDATOR = _ROOT / "tools" / "ci" / "validate_ai_use_log.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_ai_use_log", _VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_ai_use_log_is_valid_yaml_and_well_formed():
    """REQ gate 6: the committed AI-use log parses and every entry has its fields."""
    pytest.importorskip("yaml")
    assert _LOG.is_file(), "docs/ai-use-log.yaml is missing"
    validator = _load_validator()
    assert validator.main(["validate_ai_use_log.py", str(_LOG)]) == 0


@pytest.mark.unit
def test_ai_use_log_has_no_bare_conflict_artifact_lines():
    """A merge artifact (a bare branch/line with no ``key:``) must not survive."""
    lines = _LOG.read_text(encoding="utf-8").splitlines()
    offenders = []
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        # A line at column 0 that is not a top-level key (``entries:``) or a list
        # item (``- ...``) or a document marker is a merge artifact.
        if indent == 0 and not (stripped.startswith("- ") or stripped == "entries:"
                                or line.startswith("---")):
            offenders.append(f"{number}: {line!r}")
    assert offenders == [], "bare/conflict-artifact lines found: " + "; ".join(offenders)
