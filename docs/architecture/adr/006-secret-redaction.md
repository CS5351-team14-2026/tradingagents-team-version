# ADR-006 — Secret redaction at output boundaries and a PR-blocking secret scan

- Status: Proposed (2026-11-21)
- Requirements: REQ-TA-SEC-001 (should, implement #Alex); relates REQ-TA-INV-006
  (frozen/unclaimed), REQ-TA-QR-004, REQ-TA-FR-008
- Supersedes: none. Extends the baseline (AGENTS.md §3) by changing output
  behaviour (CLI errors, warning logs, message_tool.log, reports, state logs).

## Context

REQ-TA-SEC-001 requires that "no configured secret appears unredacted in logs,
reports, prompts, test fixtures, commits, or transcripts." The baseline protects
only a few narrow paths (`dataflows/net.py get_scrubbed` for query-param keys; a
per-vendor scrub in the Alpha Vantage client) and has no repository-wide secret
scan. Changing these output boundaries is a safety-critical baseline change, so
an ADR is required (AGENTS.md §3).

## Decision

1. **One shared, dependency-free sanitizer** — `src/tradingagents/redaction.py`
   with a stable `[REDACTED]` marker, applied only to high-confidence secret
   *shapes* (token prefixes, PEM blocks, auth/cookie header values, URL userinfo,
   sensitive-name assignments, absolute user paths). It copies mappings/sequences
   (never mutates caller data), is safe on malformed input, imports no provider
   SDKs, and reads no environment variables. Ordinary content (model names,
   tickers, public URLs, UUIDs, hashes, HTTP codes, numeric token counts) is
   preserved.

2. **Applied at serialization / write boundaries, not every internal stage:**
   - CLI user-visible errors (`cli/main.py`).
   - Provider/memory warning logs (`graph/trading_graph.py`).
   - Both `message_tool.log` write points (`cli/run.py`).
   - Markdown/HTML report serialization (`reporting.write_report_tree`, via the
     report `parts`; HTML shares those parts).
   - Full-state-log free-text fields (`_log_state` via `_redact_state_log_text`).

   QR-004 run records are safe by construction (the `replayable_settings`
   allowlist excludes secrets/paths; agent text is not serialized into the
   record) — proved by tests, not redacted. FR-008 replay validation already
   rejects secret/path-like values without echoing them (unchanged).

3. **PR-blocking secret scan** — a CI job running pinned
   `detect-secrets==1.5.0`, scanning tracked files and comparing to a reviewed
   `.secrets.baseline`. Only *new* findings block; scanner errors fail closed.
   Pre-existing synthetic/test/doc findings are recorded in the baseline (not
   hidden). Changes to `.secrets.baseline` require a `secret-baseline-approved`
   label so a PR cannot add a secret and re-baseline it in the same change.

## Alternatives considered

- **Redact at every internal processing stage** — rejected: duplicates work,
  risks breaking reproducibility and diagnostics; boundaries are where exposure
  actually happens.
- **Broad word matching (any "token"/"key")** — rejected: false positives would
  corrupt model names, tickers, and metric keys (e.g. `tokens_in`).
- **No scan / scan-only-without-baseline** — rejected: no scan leaves the
  requirement unmet; a scan without a baseline fails on pre-existing synthetic
  fixtures and pressures broad exclusions.
- **Count-by-configured-value only** — out of scope for this ADR; documented as a
  known limitation (custom-format keys without a known prefix).

## Consequences

- Baseline output behaviour changes (CLI errors, logs, `message_tool.log`,
  reports, state logs are sanitized). Reviewed as a safety-critical change.
- `redact()` (structured) is available but must preserve telemetry keys
  (`tokens_in`/`tokens_out`/`input_tokens`/`output_tokens` are in the safe set).
- The merge-blocking property of the scan depends on the check being a required
  status check on `main` (a repository-admin setting, not a PR change).
- Known limitations: custom secrets without a known prefix are not detected by
  pattern; the baseline can mask a pre-existing finding in a baselined file (new
  findings in that file are still caught); exception-signature fallback may
  degrade the exception type when its constructor requires arguments.

## Re-evaluation triggers

- A real secret is observed reaching an unprotected boundary.
- The configured secret formats change materially.
- The team adopts a different scanning tool or a repository-admin change makes
  the scan required.
- INV-006 is unfrozen and scoped.
