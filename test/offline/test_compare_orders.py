"""Unit tests for the QR005-04 order comparison (REQ-TA-QR-005).

``tools/ci/compare_orders.py`` reads the junitxml files the isolated CI stage
produces. These tests feed it synthetic XML so the pass/fail rules are checked
deterministically and offline; the real seeded runs happen in the container job.
"""

import xml.etree.ElementTree as ET

import pytest

from tools.ci import compare_orders


def _write_junit(path, ids):
    """Write a minimal junitxml listing ``ids`` (``class::name``) in order."""
    suite = ET.Element("testsuite", name="pytest")
    for node in ids:
        classname, _, name = node.partition("::")
        ET.SubElement(suite, "testcase", classname=classname, name=name)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _write_all(dir_path, *, default, seed_42, seed_42_repeat, seed_5351):
    _write_junit(dir_path / compare_orders.DEFAULT_XML, default)
    _write_junit(dir_path / compare_orders.SEED_42_XML, seed_42)
    _write_junit(dir_path / compare_orders.SEED_42_REPEAT_XML, seed_42_repeat)
    _write_junit(dir_path / compare_orders.SEED_5351_XML, seed_5351)


_BASE = ["a::1", "a::2", "b::3", "b::4", "c::5"]
_SEEDED = ["c::5", "a::2", "b::4", "a::1", "b::3"]


@pytest.mark.unit
def test_passes_with_identical_sets_a_reorder_and_a_reproducible_seed(tmp_path):
    """QR005-04: same set, a reordered seed, and a reproducible seed 42 pass."""
    _write_all(
        tmp_path,
        default=_BASE,
        seed_42=_SEEDED,
        seed_42_repeat=_SEEDED,
        seed_5351=["b::3", "c::5", "a::1", "b::4", "a::2"],
    )

    assert compare_orders.compare(tmp_path) == 0


@pytest.mark.unit
def test_fails_when_a_seed_selects_a_different_set(tmp_path, capsys):
    """QR005-04: a run whose selected set differs from default fails."""
    _write_all(
        tmp_path,
        default=_BASE,
        seed_42=_SEEDED,
        seed_42_repeat=_SEEDED,
        seed_5351=["c::5", "a::2", "b::4", "a::1"],  # missing b::3
    )

    assert compare_orders.compare(tmp_path) == 1
    assert "different set" in capsys.readouterr().out


@pytest.mark.unit
def test_fails_when_no_seed_reorders(tmp_path, capsys):
    """QR005-04: if every seed matches the default order, order-independence is
    unproven and the check fails."""
    _write_all(
        tmp_path,
        default=_BASE,
        seed_42=_BASE,
        seed_42_repeat=_BASE,
        seed_5351=_BASE,
    )

    assert compare_orders.compare(tmp_path) == 1
    assert "no seed reordered" in capsys.readouterr().out


@pytest.mark.unit
def test_fails_when_a_seed_does_not_reproduce(tmp_path, capsys):
    """QR005-04: seed 42 must reproduce its order on the repeat run."""
    _write_all(
        tmp_path,
        default=_BASE,
        seed_42=_SEEDED,
        seed_42_repeat=list(reversed(_SEEDED)),
        seed_5351=["b::3", "c::5", "a::1", "b::4", "a::2"],
    )

    assert compare_orders.compare(tmp_path) == 1
    assert "did not reproduce" in capsys.readouterr().out


@pytest.mark.unit
def test_fails_when_an_artifact_is_missing(tmp_path, capsys):
    """QR005-04: a missing junitxml (a run that did not happen) fails."""
    _write_junit(tmp_path / compare_orders.DEFAULT_XML, _BASE)

    assert compare_orders.compare(tmp_path) == 1
    assert "missing junitxml" in capsys.readouterr().out
