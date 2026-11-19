"""Isolation preflight for REQ-TA-QR-005 / Issue #32 QR005-03.

Runs *outside* pytest, before the suite, in the same environment the suite runs
in. It proves the environment itself confines egress — independently of the
pytest ``_no_network`` fixture — by exercising one controlled non-loopback
endpoint and the loopback interface:

- ``control`` mode: the controlled endpoint MUST be reachable (a normal
  container on the default network reaches it), so the check is meaningful.
- ``isolated`` mode: the same endpoint MUST be refused (e.g. ``--network none``),
  and a ``127.0.0.1`` bind/connect MUST still succeed (loopback is local IPC).

Usage:

    python tools/ci/isolation_preflight.py control  [--host H --port P]
    python tools/ci/isolation_preflight.py isolated [--host H --port P]

Exit 0 when the observed behaviour matches the mode; non-zero otherwise. The
printed ``PREFLIGHT ...`` lines are the artifact a PR keeps as evidence.
"""

import argparse
import socket
import sys

DEFAULT_HOST = "1.1.1.1"
DEFAULT_PORT = 443
CONNECT_TIMEOUT = 5.0


def _try_external(host: str, port: int) -> tuple[bool, str]:
    """Return (reachable, reason) for a TCP connect to ``host:port``."""
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
            return True, "connected"
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _loopback_ok() -> tuple[bool, str]:
    """Return (ok, reason) for a loopback bind + connect round trip."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=CONNECT_TIMEOUT):
                return True, f"127.0.0.1:{port} reachable"
        except OSError as exc:
            return False, f"{type(exc).__name__}: {exc}"
    finally:
        server.close()


def run(mode: str, host: str, port: int) -> int:
    failures: list[str] = []

    reachable, external_reason = _try_external(host, port)
    print(f"PREFLIGHT external {host}:{port} reachable={reachable} ({external_reason})")

    loopback_ok, loopback_reason = _loopback_ok()
    print(f"PREFLIGHT loopback ok={loopback_ok} ({loopback_reason})")

    if mode == "control":
        if not reachable:
            failures.append(
                f"control mode expected {host}:{port} reachable, but it was not ({external_reason})"
            )
    elif mode == "isolated":
        if reachable:
            failures.append(
                f"isolated mode expected {host}:{port} blocked, but it was reachable"
            )
    else:  # pragma: no cover - argparse restricts the choices
        failures.append(f"unknown mode {mode!r}")

    if not loopback_ok:
        failures.append(f"loopback bind/connect failed as required ({loopback_reason})")

    if failures:
        for failure in failures:
            print(f"::error::isolation preflight ({mode}): {failure}")
        print(f"PREFLIGHT {mode} FAILED: {len(failures)} problem(s)")
        return 1

    print(f"PREFLIGHT {mode} PASSED")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["control", "isolated"])
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv[1:])
    return run(args.mode, args.host, args.port)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
