"""A temporary controlled TCP endpoint for the QR005 isolation preflight.

Issue #32 QR005-03 asks for "a numeric endpoint on a controlled non-loopback
network that a control run can reach": this starts a plain TCP listener on the
CI runner so a bridge-network container can connect to it while a
``--network none`` container cannot. It is not part of the test suite; the CI
job starts it in the background, records its port, and stops it afterwards.

Usage:

    python tools/ci/controlled_endpoint.py --host 0.0.0.0 --port 0 --port-file /tmp/port

With ``--port 0`` the OS picks a free port; ``--port-file`` receives the chosen
port so the workflow can pass the same number to the preflight in both modes.
The process serves until it receives SIGTERM/SIGINT.
"""

import argparse
import socket
import sys
from pathlib import Path


def serve(host: str, port: int, port_file: Path | None) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(16)
    chosen = server.getsockname()[1]
    if port_file is not None:
        port_file.write_text(str(chosen), encoding="utf-8")
    print(f"controlled endpoint listening on {host}:{chosen}", flush=True)
    try:
        while True:
            conn, _ = server.accept()
            conn.close()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--port-file", default=None)
    args = parser.parse_args(argv[1:])
    serve(args.host, args.port, Path(args.port_file) if args.port_file else None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
