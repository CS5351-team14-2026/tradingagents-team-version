# Option ledger

> Deliverable D2.11: options that were rejected or deferred, and the condition
> under which each should be reconsidered. Requirement-level reasons are in
> `docs/req/requirements.yaml` (`candidate`/`wont` entries) and the
> rationale section of `docs/architecture/evaluation-table.md`.

## Requirement-level options not pursued

| Option | Status | Why not now | Reconsider when |
| --- | --- | --- | --- |
| Structured Bull/Bear debate protocol (FR-003) | `wont` | Adds schema and tokens to the debate without a consumer; the final-decision contract already bounds output | A downstream consumer needs per-round structure (e.g. debate analytics) |
| Four-value run-status enum (FR-006) | `wont` | The acceptance verdict answers trust without a second vocabulary; data-quality gating partially covered by vendor errors and point-in-time rules | A status consumer outside the report appears (dashboard, API) |
| Token-cost target (COST-001) | `wont` | Cost was demonstrated through the paired evaluation instead; a standalone cost threshold would duplicate PERF-001's measurement | Pricing is configured and billing-grade cost must be asserted |
| Prompt-semantic-evaluation gate as a requirement (GOV-001) | `wont` as a requirement | The gate is recorded as DEBT-003 with grounded trigger paths; building the fixed eval set was out of the window | A fixed eval set exists and prompt changes become frequent |
| Credential governance requirement (GOV-002) | `wont` as a requirement | Behaviour delivered by SEC-001 (ADR-006) + the key registry; the governance wrapper added no new enforcement | Multiple credential stores appear |
| Run-config traceability requirement (GOV-003) | `wont` as a requirement | Delivered de facto by `run_settings` + QR-004 run metadata | A consumer needs a formally versioned settings schema |
| Data-chain governance requirement (GOV-004) | `wont` as a requirement | Behaviour already exists (explicit chains, no silent fallback) and is documented in the runtime policy catalog | Vendor chain configuration becomes multi-tenant |
| Checkpoint-signature requirement (GOV-005) | `wont` as a requirement | Behaviour exists and is tested; a requirement wrapper added no enforcement | Checkpoint sharing across users appears |
| No-silent-failure invariant (INV-004) | `wont` | Covered concretely by QR-001 failure codes + acceptance verdict | Mandatory-agent failure needs its own machine-readable status distinct from QR-001 codes |
| Credential-leak invariant (INV-006) | `wont` | Folded into SEC-001, which is CI-enforced | A leak vector outside logs/reports/commits appears |

## Technical options rejected during design

| Option | Rejected in | Why | Reconsider when |
| --- | --- | --- | --- |
| CLI-only token accounting | ADR-004 | API callers would bypass the ceiling | Never (graph-level is strictly better) |
| Cancelling in-flight provider calls on budget exhaustion | ADR-004 | Providers do not offer reliable cancellation; claiming a hard cap would be dishonest | Provider API exposes cancellation |
| LLM-as-judge for claim attribution | ADR-001 | Non-deterministic, cannot be a zero-tolerance gate, costs tokens | A human-review triage layer needs triage assistance |
| Forcing `REVIEW` when claims are unaccepted | ADR-001 §4 | Rating semantics belong to INV-001/FR-004; conflating them hides the reason | Never (separation is deliberate) |
| Putting `claim_enforcement` into `run_settings()` | ADR-001 implementation | `run_settings` feeds the run signature; adding a key would invalidate every existing checkpoint | A settings-schema version bump is planned |
| Extracting every prompt into `prompts/*.yaml` | evaluation-table row 9 | Large risky refactor late in the project; versioned snapshots suffice for governance | Prompt churn requires file-level diffs |
| Unbounded retry on provider failures | ADR-005 | Unbounded latency; the case is a controlled failure instead | Provider offers idempotent retries with budget awareness |
| Codex as the implementation harness (FR-002 first attempt) | Team review | Course requires OpenCode; the first FR-002 implementation was redone with OpenCode (#48) and the Codex transcript retained as process evidence | Never for graded code; the record stays as report material |
| Squash-merging every PR | Branch model | Loses stepwise history on `main`? — Actually kept: squash is the team convention for `integration`; process evidence lives in transcripts and the AI-use log, so squash is retained | A deliverable requires stepwise commit history on `main` |
| Rewriting the two `ubuntu`-authored commits | Team decision | Branch protection forbids force-push (`allow_force_pushes: false`, `enforce_admins: true`); rewriting was abandoned rather than disabling protection | Repo admin can relax protection temporarily without risk |
