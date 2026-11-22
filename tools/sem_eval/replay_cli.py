"""Single-case Portfolio Manager replay (Gate 4, Phase 2B step 1).

Runs exactly one fixed case through :mod:`tools.sem_eval.replay` and writes the
same two artefacts the CI wrapper consumes:

- ``result.json`` — the replay report (``mode="semantic_replay"``,
  ``status="OBSERVE"``, ``thresholds="TBD"``; exit 0), or a redacted
  ``INFRASTRUCTURE_ERROR`` (exit 2).
- ``summary.txt`` — a short human-readable summary.

A real run requires an explicit ``--provider`` and ``--model`` (the deep-tier
model); the credential is read from the environment by the provider client, never
passed on the command line. Offline tests call :func:`main` with an injected
``llm_factory`` and never touch the network.

Usage::

    python -m tools.sem_eval.replay_cli \
        --cases test/fixtures/gate4/pm_cases.json --case-id valid_dated_claim \
        --provider deepseek --model deepseek-chat --out docs/evidence/gate4/<date>/case-01
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.sem_eval.evaluator import CaseSchemaError, exit_code_for, load_cases
from tools.sem_eval.replay import (
    MODE_SEMANTIC_REPLAY,
    run_replay,
)


def _summary(report: dict[str, Any]) -> str:
    lines = [
        f"Gate 4 PM replay (single case) — overall status: {report['status']} "
        f"(exit {report['exit_code']})",
        f"  mode: {report['mode']}  thresholds: {report['thresholds']}",
    ]
    if report.get("reason"):
        lines.append(f"  reason: {report['reason']}")
    for result in report.get("results", []):
        observed = result.get("observed_status") or "-"
        reasons = ", ".join(result.get("observed_reasons", [])) or "-"
        lines.append(
            f"  case {result['id']}: audit={result.get('audit_status') or '-'} "
            f"observed={observed} ({reasons}) "
            f"rating={result.get('final_rating') or '-'}"
        )
        if result.get("error"):
            lines.append(f"        error: {result['error']}")
    return "\n".join(lines)


def _infra_error(reason: str) -> dict[str, Any]:
    return {
        "mode": MODE_SEMANTIC_REPLAY,
        "status": "INFRASTRUCTURE_ERROR",
        "exit_code": exit_code_for("INFRASTRUCTURE_ERROR"),
        "reason": reason,
        "thresholds": "TBD",
        "results": [],
        "counts": {},
        "mismatches": [],
        "errors": [],
    }


def _write(out_dir: Path, report: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = _summary(report)
    (out_dir / "summary.txt").write_text(summary + "\n", encoding="utf-8")


def main(
    argv: list[str] | None = None,
    *,
    llm_factory: Any | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="path to a case-list JSON file")
    parser.add_argument("--case-id", required=True, help="the id of the single case to replay")
    parser.add_argument("--out", required=True, help="output directory for result.json + summary.txt")
    parser.add_argument("--provider", help="LLM provider (required for a real run)")
    parser.add_argument("--model", help="deep-tier model id (required for a real run)")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)

    def fail(reason: str) -> int:
        report = _infra_error(reason)
        _write(out_dir, report)
        print(_summary(report))
        return report["exit_code"]

    # Load and validate the case file BEFORE building any model factory, so an
    # invalid case never constructs a model client. Reasons are fixed codes only
    # (never the raw exception text or an input value).
    try:
        cases = load_cases(args.cases)
    except CaseSchemaError:
        return fail("case_schema_error")
    except UnicodeDecodeError:
        # The file exists but is not valid UTF-8: an infrastructure problem, not
        # content. Still write the artefacts and return exit 2.
        return fail("case_file_not_utf8")
    except (OSError, json.JSONDecodeError) as exc:
        return fail(f"case_file_unreadable:{type(exc).__name__}")

    selected = [c for c in cases if c.get("id") == args.case_id]
    if not selected:
        return fail("case_not_found")

    # Only now build the model factory: tests inject one; a real run needs an
    # explicit provider + deep model (credential read from the environment).
    factory = llm_factory
    if factory is None:
        if not args.provider or not args.model:
            return fail("missing_provider_or_model")
        from tools.sem_eval.replay import provider_llm_factory

        factory = provider_llm_factory(args.provider, args.model)

    report = run_replay(selected, llm_factory=factory)
    _write(out_dir, report)
    print(_summary(report))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
