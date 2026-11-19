"""Unit tests for the isolation preflight (REQ-TA-QR-005, QR005-03).

These exercise the preflight's decision logic without touching the network: the
external probe and the loopback probe are replaced with fakes so each mode's
pass/fail rule is checked deterministically. The real control-vs-isolated run in
a ``--network none`` container is a CI stage, not this offline test.
"""

import pytest

from tools.ci import isolation_preflight


def _patch(monkeypatch, *, external: bool, loopback: bool):
    monkeypatch.setattr(
        isolation_preflight, "_try_external", lambda host, port: (external, "fake")
    )
    monkeypatch.setattr(
        isolation_preflight, "_loopback_ok", lambda: (loopback, "fake")
    )


@pytest.mark.unit
def test_control_passes_when_the_endpoint_is_reachable(monkeypatch, capsys):
    """QR005-03: the control run must confirm the endpoint is reachable."""
    _patch(monkeypatch, external=True, loopback=True)

    assert isolation_preflight.run("control", "example.test", 443) == 0
    assert "PREFLIGHT control PASSED" in capsys.readouterr().out


@pytest.mark.unit
def test_control_fails_when_the_endpoint_is_unreachable(monkeypatch, capsys):
    """QR005-03: a control run that cannot reach the endpoint proves nothing."""
    _patch(monkeypatch, external=False, loopback=True)

    assert isolation_preflight.run("control", "example.test", 443) == 1
    assert "control FAILED" in capsys.readouterr().out


@pytest.mark.unit
def test_isolated_passes_when_the_endpoint_is_blocked(monkeypatch, capsys):
    """QR005-03: in isolation the same endpoint must be refused and loopback
    must still work."""
    _patch(monkeypatch, external=False, loopback=True)

    assert isolation_preflight.run("isolated", "example.test", 443) == 0
    assert "PREFLIGHT isolated PASSED" in capsys.readouterr().out


@pytest.mark.unit
def test_isolated_fails_when_the_endpoint_is_reachable(monkeypatch, capsys):
    """QR005-03: if egress still works in "isolation", the test is meaningless."""
    _patch(monkeypatch, external=True, loopback=True)

    assert isolation_preflight.run("isolated", "example.test", 443) == 1
    assert "isolated FAILED" in capsys.readouterr().out


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["control", "isolated"])
def test_both_modes_require_loopback(monkeypatch, capsys, mode):
    """QR005-03: loopback bind/connect must succeed regardless of egress mode."""
    _patch(monkeypatch, external=(mode == "control"), loopback=False)

    assert isolation_preflight.run(mode, "example.test", 443) == 1
    assert "loopback bind/connect failed" in capsys.readouterr().out


@pytest.mark.unit
def test_argparse_rejects_an_unknown_mode():
    """QR005-03: only ``control`` and ``isolated`` are valid modes."""
    with pytest.raises(SystemExit):
        isolation_preflight.main(["preflight", "sideways"])
