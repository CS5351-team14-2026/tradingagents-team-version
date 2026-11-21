# SEC-001 trace — secret redaction and leakage prevention

Requirement: REQ-TA-SEC-001 (security) — "no configured secret appears
unredacted in logs, reports, prompts, test fixtures, commits, or transcripts."
Test plan: Issue #50. Owner: Alex. Decision record: ADR-006.

## Redaction contract

- Shared utility: `src/tradingagents/redaction.py`.
- Marker: `[REDACTED]` (stable, deterministic, idempotent).
- Handles strings and structured objects (copies, never mutates caller data);
  safe on malformed input; no provider-SDK imports; no environment reads; does
  not record which value triggered redaction.
- High-confidence shapes only (token prefixes, PEM blocks, header values,
  URL userinfo, sensitive-name assignments, absolute user paths). Ordinary
  model names, tickers, public URLs, UUIDs, hashes, HTTP codes, and numeric
  token counts are preserved.

## Protected output boundaries

- Provider/CLI errors: `redact_text` before user-visible print (CLI) and in the
  graph's warning logs for settle/memory failures.
- `message_tool.log`: both write points sanitized at the write boundary.
- QR-004 records: safe by allowlist (no agent text/secrets serialized) — proved by tests.
- Full-state logs: free-text report/history fields redacted at write (`_redact_state_log_text`).
- Reports (Markdown + HTML): agent-generated section text redacted at serialization (`write_report_tree`).
- FR-008 replay validation: already rejects secret/path-like values without
  echoing them (unchanged; regression-tested).

## detect-secrets PR gate

- Pinned `detect-secrets==1.5.0` (dev extra).
- CI job `secret-scan`: scans tracked files and compares against the reviewed
  `.secrets.baseline`; only NEW findings block a PR; scanner errors fail closed.
- Baseline freezes pre-existing synthetic/test/documentation findings (14 files,
  17 findings) so they are recorded, not hidden.
- Narrow fixture exemption: `test/offline/test_sec001_redaction.py` builds
  synthetic secret-like values in code; exempted explicitly, not by directory.

## Source → code → test

| Aspect | Code | Test |
|---|---|---|
| text redaction | `redaction.redact_text` | `test_sec001_redaction.py` (shapes, headers, url, env, pem, paths, idempotency, false positives) |
| structured redaction | `redaction.redact`, `redact_exception` | nested/non-string/unicode/malformed/type-preserving |
| message_tool.log | `cli/run.py` write decorators | `test_message_tool_log_writes_are_sanitized` |
| CI gate logic | `.github/workflows/ci.yml` `secret-scan` | `test_scanner_gate_logic_blocks_on_findings_and_passes_clean` |

## Known limitations

- Not general-purpose DLP; only the high-confidence patterns SEC-001 names.
- Baseline can mask a *pre-existing* finding in a baselined file; new findings
  in those files are still caught.
- Prompt/tool sanitization is at the log-write boundary only (no logging redesign).
