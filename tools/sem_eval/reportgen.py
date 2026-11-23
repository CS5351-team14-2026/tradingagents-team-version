"""Generate the Gate 4 evaluation report for the *current PR* (Phase 3C).

Produces a fresh report (never the archived baseline) with:

- ``candidate_sha`` — the commit under evaluation (the PR head);
- ``case_version`` — a SHA-256 over the case inputs + expected answers, so a case
  edit is visible;
- ``model_config`` — effective provider/model/temperature (verbatim);
- per-case results (via :func:`tools.sem_eval.replay.run_baseline`) plus a
  top-level view that :func:`tools.sem_eval.ci_entry.evaluate_pr` consumes.

Offline tests inject an ``llm_factory`` and a ``sha``; the real path is only run
inside a **trusted execution environment** (the CI job with the owner's secret,
or the owner's machine). This module never reads a credential itself: the
provider factory it can build reads the key from the environment, and only when
the caller has chosen the live path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from tools.sem_eval.replay import LlmFactory, run_baseline

REPORT_SCHEMA = 1

# Providers with a native (non OpenAI-compatible) client in llm_clients.factory.
_NATIVE_PROVIDERS = frozenset({"anthropic", "google", "azure", "bedrock"})


def resolve_candidate_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The candidate version's full config (``DEFAULT_CONFIG`` overlaid by ``config``)."""
    from tradingagents.default_config import DEFAULT_CONFIG

    resolved = dict(DEFAULT_CONFIG)
    if config:
        resolved.update(config)
    return resolved


def effective_pm_model_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The effective Portfolio Manager (deep-tier) model configuration.

    Reuses the application's own resolution so the gate never keeps a separate
    whitelist: the provider/model come from ``create_tier_client``'s tier logic,
    and the non-sensitive sampling/reasoning settings come from
    ``build_llm_kwargs`` (temperature, reasoning effort, thinking level, token
    cap). This is the *candidate version's* configuration, not an archived one.
    """
    resolved = resolve_candidate_config(config)
    from tradingagents.llm_clients.factory import build_llm_kwargs, tier_provider

    provider = tier_provider(resolved, "deep")
    # build_llm_kwargs keys off ``llm_provider``; use the deep-tier provider so
    # provider-specific reasoning settings resolve for the tier actually used.
    kwargs = build_llm_kwargs({**resolved, "llm_provider": provider})
    cfg: dict[str, Any] = {
        "provider": provider,
        "model": resolved.get("deep_think_llm"),
    }
    for key in ("temperature", "reasoning_effort", "thinking_level", "effort",
                "max_tokens", "max_output_tokens"):
        if key in kwargs:
            cfg[key] = kwargs[key]
    return cfg


def candidate_llm_factory(config: Mapping[str, Any] | None = None) -> LlmFactory:
    """A factory building the deep-tier client from the candidate config.

    Delegates to the application's ``create_tier_client`` so the *same* provider /
    model / temperature / reasoning settings reach the real client that the
    production graph would use. The client reads its credential from the
    environment; no key is taken or stored here. Built lazily so offline tests
    that inject a double never import a provider SDK.
    """
    def _factory() -> Any:
        from tradingagents.llm_clients.factory import create_tier_client

        client = create_tier_client(resolve_candidate_config(config), "deep")
        return client.get_llm() if hasattr(client, "get_llm") else client

    return _factory


def validate_pm_model_config(config: Mapping[str, Any] | None = None) -> tuple[bool, str | None]:
    """Whether the candidate's PM model config is usable.

    Returns ``(ok, reason)`` with a fixed safe code when not ok:

    - ``missing_model`` — no deep-tier model id resolved;
    - ``unsupported_provider`` — the provider has no client in llm_clients;
    - ``missing_credential`` — the provider's key env var is unset.

    A provider that requires no key (bedrock/sign-in/local) passes the credential
    check. This never reads the key value, only whether it is present. No model
    whitelist is kept: support is exactly "does llm_clients build this provider".
    """
    model_config = effective_pm_model_config(config)
    provider = (model_config.get("provider") or "").lower()
    if not model_config.get("model"):
        return False, "missing_model"
    from tradingagents.llm_clients.factory import create_llm_client  # noqa: F401 - existence
    from tradingagents.llm_clients.openai_client import is_openai_compatible

    if provider not in _NATIVE_PROVIDERS and not is_openai_compatible(provider):
        return False, "unsupported_provider"
    from tradingagents.llm_clients.api_key_env import get_api_key_env

    key_env = get_api_key_env(provider)
    if key_env is not None and not _env_present(key_env):
        return False, "missing_credential"
    return True, None


def _env_present(name: str) -> bool:
    import os

    value = os.environ.get(name, "")
    return bool(value) and value != "placeholder"


def _hash(value: Any) -> str:
    """A stable SHA-256 over a JSON-serialisable value (dict order normalised)."""
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def case_version(cases: Iterable[Mapping[str, Any]]) -> str:
    """A content hash of the case set (inputs + expected answers)."""
    return _hash(list(cases))


def _safe_model_config(model_config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Record only non-sensitive config keys; never endpoints or credentials."""
    allowed = (
        "provider", "model", "temperature", "reasoning_effort", "thinking_level",
        "effort", "max_tokens", "max_output_tokens", "repetitions",
        "config_overridden",
    )
    config = dict(model_config or {})
    return {key: config[key] for key in allowed if key in config}


def build_report(
    cases: Iterable[Mapping[str, Any]],
    *,
    llm_factory: LlmFactory,
    candidate_sha: str,
    model_config: Mapping[str, Any],
    repetitions: int,
) -> dict[str, Any]:
    """Run the replay for the current PR and return a report envelope."""
    cases = list(cases)
    baseline = run_baseline(
        cases,
        llm_factory=llm_factory,
        repetitions=repetitions,
        model_config=_safe_model_config(model_config),
    )
    return {
        "schema": REPORT_SCHEMA,
        "candidate_sha": candidate_sha,
        "case_version": case_version(cases),
        "model_config": _safe_model_config(model_config),
        "repetitions": repetitions,
        "thresholds": "TBD",
        # The replay body (status OBSERVE/INFRASTRUCTURE_ERROR, per-case results).
        "replay": baseline,
    }


def finalize_verdict(report: Mapping[str, Any], ci_result: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``report`` carrying the final gate verdict.

    Adds ``final_decision`` (one of #81's four statuses), ``failed_rules`` (fixed
    codes from the gate's FAIL runs), ``cases`` (per-case decision + reasons), and
    ``exit_code``. The report envelope and its ``replay`` body are preserved.
    """
    finalized = dict(report)
    finalized["final_decision"] = ci_result.get("status")
    finalized["exit_code"] = ci_result.get("exit_code")
    finalized["blocks_merge"] = ci_result.get("blocks_merge")
    # Preserve the CI reason and the full-evidence cases that did not meet
    # acceptance (with their run reasons), so the report explains a FAIL.
    finalized["reason"] = ci_result.get("reason")
    finalized["unmet_cases"] = list(ci_result.get("unmet_cases") or [])
    # Surface completeness so a reviewer downloading report.json sees exactly
    # which fixed cases / run numbers were missing or malformed.
    gate = ci_result.get("gate") or {}
    completeness = ci_result.get("completeness") or gate.get("completeness")
    finalized["completeness"] = completeness or {}
    cases_view = []
    failed_rules: list[str] = []
    for case in gate.get("cases", []):
        cases_view.append({
            "id": case.get("id"),
            "decision": case.get("decision"),
            "runs": [{
                "repetition": r.get("repetition"),
                "decision": r.get("decision"),
                "reasons": r.get("reasons"),
                # Provenance: keep the model's own rating, the app-validated
                # rating + reasons, and the audit result distinct.
                "model_rating": r.get("model_rating"),
                "applied_rating": r.get("applied_rating", r.get("pm_decision")),
                "applied_review_reasons": list(r.get("applied_review_reasons") or []),
                "review_origin": r.get("review_origin"),
                "audit_status": r.get("audit_status"),
                "audit_reasons": list(r.get("audit_reasons") or []),
            } for r in case.get("runs", [])],
        })
        for run in case.get("runs", []):
            if run.get("decision") == "FAIL":
                for reason in run.get("reasons", []):
                    if reason not in failed_rules:
                        failed_rules.append(reason)
    finalized["failed_rules"] = failed_rules
    finalized["cases"] = cases_view
    return finalized


def _has_provenance_view(run: Mapping[str, Any]) -> bool:
    """Whether a finalized per-run view carries S2 provenance fields."""
    return any(k in run for k in ("model_rating", "applied_rating", "review_origin"))


def render_summary(report: Mapping[str, Any]) -> str:
    """A short readable summary of a report envelope (includes the verdict)."""
    lines = [
        "Gate 4 evaluation report",
        f"  candidate_sha: {report.get('candidate_sha')}",
        f"  case_version: {report.get('case_version')}",
        f"  model_config: {report.get('model_config')}",
        f"  repetitions: {report.get('repetitions')}",
        f"  thresholds: {report.get('thresholds')}",
    ]
    if "final_decision" in report:
        lines.append(
            f"  final_decision: {report.get('final_decision')} "
            f"(exit {report.get('exit_code')}, blocks_merge={report.get('blocks_merge')})"
        )
        if report.get("reason"):
            lines.append(f"  reason: {report.get('reason')}")
        completeness = report.get("completeness") or {}
        if completeness and completeness.get("ok") is False:
            lines.append("  completeness: INCOMPLETE")
            for problem in completeness.get("problems") or []:
                lines.append(f"    - {problem}")
        failed = report.get("failed_rules") or []
        lines.append(f"  failed_rules: {', '.join(failed) if failed else 'none'}")
        unmet = report.get("unmet_cases") or []
        if unmet:
            lines.append("  unmet_cases:")
            for case in unmet:
                why = ", ".join(case.get("reasons") or []) or "-"
                lines.append(f"    - {case.get('id')}: {why}")
    replay = report.get("replay", {})
    lines.append(f"  replay_status: {replay.get('status')}")
    # Prefer the finalized case view when present; else the replay aggregate.
    case_views = report.get("cases")
    if case_views:
        for case in case_views:
            run_dec = ",".join(
                f"#{r.get('repetition')}={r.get('decision')}" for r in case.get("runs", [])
            )
            lines.append(f"  case {case.get('id')}: {case.get('decision')} [{run_dec}]")
            # Provenance: show the model's own rating vs the app-validated rating
            # vs the audit, so a reviewer can tell an app downgrade from a model
            # choice without opening the JSON.
            for run in case.get("runs", []):
                if not _has_provenance_view(run):
                    continue
                model = run.get("model_rating") or "unknown"
                applied = run.get("applied_rating") or "unknown"
                applied_why = ", ".join(run.get("applied_review_reasons") or []) or "-"
                audit = run.get("audit_status") or "unknown"
                audit_why = ", ".join(run.get("audit_reasons") or []) or "-"
                origin = run.get("review_origin") or "-"
                lines.append(
                    f"    #{run.get('repetition')}: model={model} "
                    f"validated={applied} ({applied_why}) review_origin={origin} "
                    f"audit={audit} ({audit_why})"
                )
    else:
        for case in replay.get("cases", []):
            agg = case.get("aggregate", {})
            lines.append(
                f"  case {case.get('id')}: runs={agg.get('runs')} "
                f"status={agg.get('status_counts')} "
                f"attributed={agg.get('claims_attributed')}/{agg.get('claims_total')} "
                f"errors={agg.get('errors')}"
            )
    return "\n".join(lines)


def write_report(report: Mapping[str, Any], out_dir: str | Path) -> tuple[Path, Path]:
    """Write ``report.json`` + ``summary.txt``; return their paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "report.json"
    summary_path = out / "summary.txt"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(render_summary(report) + "\n", encoding="utf-8")
    return json_path, summary_path


__all__ = [
    "REPORT_SCHEMA",
    "build_report",
    "candidate_llm_factory",
    "case_version",
    "effective_pm_model_config",
    "finalize_verdict",
    "render_summary",
    "resolve_candidate_config",
    "validate_pm_model_config",
    "write_report",
]
