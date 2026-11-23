"""Score fixed Portfolio Manager cases with the existing claim audit.

Phase 1 is offline and deterministic: a *case* is a frozen final-state dict
(hand-authored analyst reports + ``material_claims``) whose claims are judged by
:func:`tradingagents.reporting.audit_material_claims` — the same audit the
production run uses. No model is invoked.

Two status vocabularies are kept strictly separate:

Per-case *audit status* (what the audit said about this case's claims):
``ACCEPTED`` / ``DOWNGRADED`` / ``NOT_ASSESSED``.

Overall *evaluation status* (interface fixed by test plan #81):
``PASS`` / ``FAIL`` / ``NOT_APPLICABLE`` / ``INFRASTRUCTURE_ERROR``.

For ``mode == "offline_precheck"``:

- every fixed case matches its expectation → ``PASS``;
- any case does not match (expected vs observed differs) → ``FAIL``;
- an empty case set, an unavailable environment, an evaluator exception, or an
  unexpected skip → ``INFRASTRUCTURE_ERROR`` (never ``PASS``).

Real-model semantic thresholds remain TBD: a ``PASS`` here means "the offline
pre-check cases matched", **not** "the semantic evaluation passed". Error
evidence never carries raw exception text or credentials — it is reduced to a
redacted, typed reason.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from tradingagents.reporting import audit_material_claims

# Per-case audit status, straight from the claim audit.
CASE_RESULT_STATUSES = frozenset({"ACCEPTED", "DOWNGRADED", "NOT_ASSESSED"})
# Overall evaluation status (test plan #81).
EVAL_STATUSES = frozenset({"PASS", "FAIL", "NOT_APPLICABLE", "INFRASTRUCTURE_ERROR"})
# Overall status -> process exit code (interface for the CI wrapper).
EXIT_CODES = {"PASS": 0, "FAIL": 1, "INFRASTRUCTURE_ERROR": 2, "NOT_APPLICABLE": 0}

MODE_OFFLINE_PRECHECK = "offline_precheck"
# Phase 1 evaluates offline cases only. Any other mode is rejected so CI cannot
# mistake an offline pass for a real-model semantic replay (thresholds are TBD).
SUPPORTED_MODES = frozenset({MODE_OFFLINE_PRECHECK})


class CaseSchemaError(ValueError):
    """A case file violates the expected schema (a typed, safe failure)."""


class UnsupportedModeError(ValueError):
    """A mode other than the supported offline pre-check was requested."""


def exit_code_for(status: str) -> int:
    """Map an overall status to its process exit code (0/1/2)."""
    return EXIT_CODES[status]


def _validate_case(index: int, case: Any) -> None:
    """Validate one case's required fields and expected-field *types*.

    ``expected_status`` must be a string when present; ``expected_reasons`` must
    be a list (of strings) when present, and may be omitted. A ``null`` here is a
    malformed case, not "no reasons": it must fail loudly, not crash the CLI.
    """
    if not isinstance(case, dict):
        raise CaseSchemaError(f"case[{index}] is not an object")
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id:
        raise CaseSchemaError(f"case[{index}] is missing a string 'id'")
    if not isinstance(case.get("state"), dict):
        raise CaseSchemaError(f"case {case_id!r} is missing a 'state' object")

    if "expected_status" in case and not isinstance(case["expected_status"], str):
        raise CaseSchemaError(f"case {case_id!r}: 'expected_status' must be a string")
    if "expected_reasons" in case:
        reasons = case["expected_reasons"]
        if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
            raise CaseSchemaError(
                f"case {case_id!r}: 'expected_reasons' must be a list of strings, not {type(reasons).__name__}"
            )


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate a JSON case list.

    Raises :class:`CaseSchemaError` for any structural or expected-field type
    problem (``expected_reasons: null``, a non-list, a non-string entry, etc.).
    The CLI turns this into an ``INFRASTRUCTURE_ERROR`` with a readable summary.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise CaseSchemaError("pm_cases.json must be a JSON list")
    case_ids: set[str] = set()
    for index, case in enumerate(data):
        _validate_case(index, case)
        case_id = case["id"]
        if case_id in case_ids:
            raise CaseSchemaError(f"duplicate case id {case_id!r}")
        case_ids.add(case_id)
    return data


def _redact_error(exc: BaseException) -> str:
    """A safe, typed error token — never the raw message or a credential."""
    return f"evaluator_error:{type(exc).__name__}"


def evaluate_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Audit one case's claims; return its observable result.

    An evaluator exception is reported as an ``evaluator_exception`` flag with a
    redacted error token, not raw exception text. Expected vs observed is
    included so the JSON speaks for itself.
    """
    case_id = case.get("id", "<unknown>")
    expected_reasons = case.get("expected_reasons")
    if not isinstance(expected_reasons, list):
        # A malformed expectation is an infrastructure problem, not a content
        # mismatch; surface it as an error even when called outside load_cases.
        return {
            "id": case_id,
            "audit_status": None,
            "evaluator_exception": True,
            "error": "case_schema_error:expected_reasons",
            "expected_status": case.get("expected_status"),
            "expected_reasons": [],
            "observed_status": None,
            "observed_reasons": [],
            "claims_total": None,
            "claims_attributed": None,
            "unsupported_claim_ids": [],
            "matches_expectation": False,
        }
    try:
        audit = audit_material_claims(case["state"])
    except Exception as exc:  # noqa: BLE001 - reported as an infra error, never hidden
        return {
            "id": case_id,
            "audit_status": None,
            "evaluator_exception": True,
            "error": _redact_error(exc),
            "expected_status": case.get("expected_status"),
            "expected_reasons": list(expected_reasons),
            "observed_status": None,
            "observed_reasons": [],
            "claims_total": None,
            "claims_attributed": None,
            "unsupported_claim_ids": [],
            "matches_expectation": False,
        }

    observed_status = audit["status"]
    observed_reasons = list(audit["reasons"])
    audit_status = observed_status if observed_status in CASE_RESULT_STATUSES else None
    reason_match = sorted(expected_reasons) == sorted(observed_reasons)
    matches = observed_status == case.get("expected_status") and reason_match
    return {
        "id": case_id,
        "audit_status": audit_status,
        "evaluator_exception": False,
        "error": None,
        "expected_status": case.get("expected_status"),
        "expected_reasons": expected_reasons,
        "observed_status": observed_status,
        "observed_reasons": observed_reasons,
        "claims_total": audit["claims_total"],
        "claims_attributed": audit["claims_attributed"],
        "unsupported_claim_ids": list(audit["unsupported_claim_ids"]),
        "matches_expectation": matches,
    }


def evaluate_cases(
    cases: Iterable[Mapping[str, Any]],
    *,
    mode: str = MODE_OFFLINE_PRECHECK,
    env_ok: bool = True,
    env_error: str | None = None,
) -> dict[str, Any]:
    """Evaluate every case and aggregate into an overall-status report.

    ``mode="offline_precheck"`` (default): every case matching its expectation
    → ``PASS``; any mismatch → ``FAIL``. An empty case set, ``env_ok=False`` (a
    missing credential, an interpreted timeout, etc.), any evaluator exception,
    or an unexpected skip → ``INFRASTRUCTURE_ERROR``. A run never reports
    ``PASS`` when it could not actually evaluate the cases.

    ``env_error`` is a short reason token; it must not contain a credential or
    raw exception text (the caller passes a typed reason). The report carries the
    overall ``status`` plus the matching :func:`exit_code_for` value.

    Only :data:`MODE_OFFLINE_PRECHECK` is supported in Phase 1: any other mode
    (for example ``"semantic_replay"``) raises :class:`UnsupportedModeError`
    rather than scoring offline cases under a real-replay label.
    """
    if mode not in SUPPORTED_MODES:
        raise UnsupportedModeError(
            f"mode {mode!r} is not supported; Phase 1 supports {sorted(SUPPORTED_MODES)}"
        )
    cases = list(cases)

    def report(status: str, *, reason: str | None, results: list[dict[str, Any]]) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for result in results:
            key = result["audit_status"] or "ERROR"
            counts[key] = counts.get(key, 0) + 1
        mismatches = [r["id"] for r in results if not r["matches_expectation"]]
        errors = [r["id"] for r in results if r.get("evaluator_exception")]
        return {
            "mode": mode,
            "status": status,
            "exit_code": exit_code_for(status),
            "reason": reason,
            "results": results,
            "counts": counts,
            "mismatches": mismatches,
            "errors": errors,
        }

    if not env_ok:
        return report("INFRASTRUCTURE_ERROR", reason=env_error or "environment_not_ready", results=[])
    if not cases:
        return report("INFRASTRUCTURE_ERROR", reason="empty_case_set", results=[])

    results = [evaluate_case(case) for case in cases]
    if any(r.get("evaluator_exception") for r in results):
        return report("INFRASTRUCTURE_ERROR", reason="evaluator_exception", results=results)
    if all(r["matches_expectation"] for r in results):
        return report("PASS", reason=None, results=results)
    return report("FAIL", reason="expectation_mismatch", results=results)


def render_summary(report: Mapping[str, Any]) -> str:
    """A short human-readable summary of an :func:`evaluate_cases` report."""
    lines = [
        f"Gate 4 PM semantic eval — overall status: {report['status']} "
        f"(exit {report['exit_code']})",
        f"  mode: {report.get('mode')}",
    ]
    if report.get("reason"):
        lines.append(f"  reason: {report['reason']}")
    for result in report.get("results", []):
        observed = result.get("observed_status") or "-"
        reasons = ", ".join(result.get("observed_reasons", [])) or "-"
        mark = "ok" if result.get("matches_expectation") else "MISMATCH"
        lines.append(
            f"  [{mark}] {result['id']}: audit={result.get('audit_status') or '-'} "
            f"observed={observed} ({reasons})"
        )
        if result.get("error"):
            lines.append(f"        error: {result['error']}")
    if report.get("counts"):
        joined = ", ".join(f"{k}={v}" for k, v in sorted(report["counts"].items()))
        lines.append(f"  counts: {joined}")
    if report.get("mismatches"):
        lines.append(f"  expectation mismatches: {', '.join(report['mismatches'])}")
    return "\n".join(lines)
