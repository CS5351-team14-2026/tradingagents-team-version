"""Command-line entry point for the Gate 4 offline pre-check.

Writes two artefacts the CI wrapper will consume in Phase 2:

- ``result.json`` — the machine-readable :func:`evaluate_cases` report
  (overall status + per-case audit status + exit code).
- ``summary.txt`` — a short human-readable summary.

Exit codes (``0``/``1``/``2``): ``PASS``/``NOT_APPLICABLE`` → 0, ``FAIL`` → 1,
``INFRASTRUCTURE_ERROR`` → 2. An unreadable or malformed case file is an
infrastructure error, not a content failure.

Usage::

    python -m tools.sem_eval.cli --cases test/fixtures/gate4/pm_cases.json \
        --out /tmp/gate4

This round does not modify GitHub Actions; the CI wrapper is Phase 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.sem_eval.evaluator import (
    MODE_OFFLINE_PRECHECK,
    CaseSchemaError,
    UnsupportedModeError,
    evaluate_cases,
    exit_code_for,
    load_cases,
    render_summary,
)


def _load(cases_path: str) -> list[dict]:
    return load_cases(cases_path)


def _infra_report(mode: str, reason: str) -> dict:
    """A typed INFRASTRUCTURE_ERROR report (never carries raw exception text)."""
    return {
        "mode": mode,
        "status": "INFRASTRUCTURE_ERROR",
        "exit_code": exit_code_for("INFRASTRUCTURE_ERROR"),
        "reason": reason,
        "results": [],
        "counts": {},
        "mismatches": [],
        "errors": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="path to pm_cases.json")
    parser.add_argument("--out", required=True, help="output directory for result.json + summary.txt")
    parser.add_argument(
        "--mode",
        default=MODE_OFFLINE_PRECHECK,
        help=f"evaluation mode (Phase 1 supports {MODE_OFFLINE_PRECHECK!r} only)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        cases = _load(args.cases)
    except CaseSchemaError as exc:
        # A malformed case (e.g. ``expected_reasons: null``) is an infrastructure
        # problem, not a content failure. Keep a readable reason, never raw text.
        report = _infra_report(args.mode, f"case_schema_error:{exc}")
    except (OSError, json.JSONDecodeError) as exc:
        report = _infra_report(args.mode, f"case_file_unreadable:{type(exc).__name__}")
    else:
        try:
            report = evaluate_cases(cases, mode=args.mode)
        except UnsupportedModeError as exc:
            report = _infra_report(args.mode, f"unsupported_mode:{exc}")

    (out_dir / "result.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = render_summary(report)
    (out_dir / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    print(summary)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
