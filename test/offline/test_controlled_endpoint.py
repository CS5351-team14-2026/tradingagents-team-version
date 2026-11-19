"""Unit tests for the controlled endpoint (REQ-TA-QR-005, QR005-03).

The endpoint is a plain TCP listener the CI job starts so a bridge container can
reach it and a ``--network none`` container cannot. These tests exercise the
local bind/port-file behaviour using the same narrowly scoped 127.0.0.1
exception the loopback callback test uses (Issue #32 §41); the real control-vs-
isolated containment happens in the CI container job.
"""

import socket
import threading

import pytest

from tools.ci import controlled_endpoint

# The suite refuses every connection; re-patch 127.0.0.1 on top of that guard
# for the local listener round trip, exactly as the loopback callback test does.
_CONNECT, _GETADDRINFO = socket.socket.connect, socket.getaddrinfo


def _allow_loopback(monkeypatch):
    refused_connect, refused_lookup = socket.socket.connect, socket.getaddrinfo
    monkeypatch.setattr(socket.socket, "connect", lambda sock, address: (
        _CONNECT if address[0] == "127.0.0.1" else refused_connect)(sock, address))
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: (
        _GETADDRINFO if host == "127.0.0.1" else refused_lookup)(host, *a, **k))


def _start(tmp_path):
    port_file = tmp_path / "port"
    threading.Thread(
        target=controlled_endpoint.serve,
        args=("127.0.0.1", 0, port_file),
        daemon=True,
    ).start()
    for _ in range(100):
        if port_file.exists() and port_file.read_text():
            break
        threading.Event().wait(0.02)
    return int(port_file.read_text())


@pytest.mark.unit
def test_it_binds_a_free_port_and_writes_it(tmp_path, monkeypatch):
    """QR005-03: binding port 0 picks a free port that the workflow reuses, and a
    loopback client can reach it."""
    _allow_loopback(monkeypatch)
    port = _start(tmp_path)

    assert port > 0
    with socket.create_connection(("127.0.0.1", port), timeout=2):
        pass


@pytest.mark.unit
def test_it_accepts_and_closes_a_connection(tmp_path, monkeypatch):
    """QR005-03: the listener accepts a client and drops it, so a reachability
    probe sees a completed TCP handshake then a close."""
    _allow_loopback(monkeypatch)
    port = _start(tmp_path)

    with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
        assert conn.recv(1) == b""  # server closed its side after accept
