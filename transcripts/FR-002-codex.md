# FR-002 — supervised Codex session record

- Date: 2026-11-18 (Asia/Shanghai).
- Agent: Codex.
- Session identifier: not supplied in the conversation; not fabricated here.
- Starting repository HEAD: `889cc33cf60bc89573159438ff98191e17adba77`.
- Purpose: implement REQ-TA-FR-002 in separately approved stages.

This is a factual session/intervention record, not a verbatim export of all
tool activity. The conversation is the source of the quotations below.

## Initial human instruction and read-only gate

The human requested a read-only repository review and an implementation plan
for the authoritative REQ-TA-FR-002. Before approval, no code, tests,
configuration, documents or AI-use log were to be modified. The request
required preserving existing work, reviewing tracked text files in full,
excluding secrets and binary assets, proposing cross-module contracts and
stopping for approval. It also prohibited candidate FR-006 scope expansion
and invented numeric thresholds.

The review used HEAD above. The nested repository was clean; the outer
workspace's existing untracked project directory was preserved. The review
reported no modifications or test/lint/schema/API execution before approval.

The review also disclosed an inherited safety deviation: earlier subagents
had reportedly opened two credential-related test files, and a line-count
pass had read raw bytes of two authentication modules. No such contents are
included here. The disclosed record cannot claim that all prior activity
obeyed a path-existence-only boundary. Those contents were excluded from the
implementation plan's evidence; subsequent work must not access them.

## Plan presented and human approval

The plan proposed:

- a shared per-run usage/budget ledger and provider callback normalization;
- explicit unavailable/partial observations and no estimated token counts;
- optional/required-call classification with controlled non-tradeable failure;
- retained parallelism, per-run identity, and later durable resume accounting;
- independent budget and `completed`/`failed` lifecycle status;
- no-budget compatibility, preserved tool cap and unchanged FR-006 scope;
- final-report reserve and quantitative calibration remaining TBD;
- S1 foundations/observation, S2 enforcement, S3 configuration/reporting/resume;
- full Ruff and offline pytest after each stage, then another human gate.

The plan's D1–D10 recommendations are recorded in ADR-003. No files were to
be changed until this approval arrived.

### Human message (verbatim)

> 采用全部推荐方案，批准本计划及 **S1** 实施

### Agent acknowledgement (verbatim)

> 收到，D1–D10 按推荐方案执行，本轮只实施 S1：共享 usage/budget 账本、provider usage 归一化、观察数据接线、基础离线测试，以及已批准接口的架构记录。完成后会运行约定检查并停下，等待你批准 S2。

## Authorized S1 work

S1 covers ADR/interface registration, the shared accounting/context
foundation, usage normalization, observation-only CLI/graph integration,
completeness propagation and deterministic offline tests. The pure atomic
admission operation may be implemented and tested as a foundation but is not
connected to production graph dispatch in this stage.

S2 invocation/routing enforcement and S3 public budget configuration,
durable checkpoint accounting and budget-report metadata are not authorized
for implementation by this message. No real paid experiment is authorized.

Documentation work in this stage creates ADR-003, the FR-002 trace record,
this intervention record, and the FR-002 integration-contract entry in
AGENTS.md section 6. The root agent records actual implementation files and
actual check outcomes in the stage report and AI-use log, preserving prior
entries. No model version, session identifier, test count, execution outcome
or later human approval is invented by this document.

## S1 implementation and actual verification

The shared ledger, public run context, pure atomic admission foundation and
provider usage callback adapter were implemented. CLI and direct graph runs
share observations, preserve call identities and distinguish complete,
partial, unavailable and conflicting usage. Genuine reported zero remains
distinct from missing usage. The QR-004 lifecycle remains `completed`/`failed`.
Legacy resumed history is labelled incomplete; S1 does not persist a durable
budget ledger. In-graph reflections use their triggering analysis's context;
standalone/backtest-tail settlement has a separate observation context. The
CLI footer labels its current-invocation counter `Tokens (observed)`.

Provider regression fixtures cover canonical and native fields, Anthropic
cache components, Google tool/thought components, raw missing fields versus
SDK-filled zero, standard usage wrappers with provider hints, aggregate/message
deduplication and per-call provider attribution. No prompt or live model
experiment was changed or run. Routing and public budget flags remain deferred.

The actual verification history included:

- Initial focused collection exposed an import-path conflict; relative imports
  fixed it. A following focused run had 110 passes and two Rich capture failures;
  the capture assertions were corrected.
- The first full run had 1714 passes and six failures caused by existing report
  tests reading UTF-8 files with Windows's default GBK decoder. The verification
  runner then enabled Python UTF-8 mode; those test files were not modified.
- A later full run had 1745 passes and two failures in a new provenance test:
  it compared a pre-refusal snapshot with the restored post-refusal ledger.
  The assertion was fixed to compare the same lifecycle point.
- A full run then passed 1747 tests. Subsequent review fixed standard
  `usage_metadata` wrappers with provider hints and added six regression cases.
- The **final code** passed `ruff check .` and full `pytest -q`: **1753 passed,
  6 skipped, 1 deselected, 24 warnings, 100 subtests passed in 47.95s**.
  Five skips reflect Windows/POSIX compatibility and one the unavailable optional
  `langchain_aws` package. The integration test was excluded by existing config.
- Test execution used a temporary runner/working directory, a clean environment,
  disabled dotenv discovery and Python UTF-8 mode, preserving repository
  configuration and fixtures. No local credential file was read by that runner.
- Registry/schema validation initially could not import `jsonschema` in the
  project/bundled Python. The existing system Python ran the unchanged validator
  successfully on the registry and template; no dependency was installed.

The actual file set is recorded in `docs/ai-use-log.yaml`. The AI-use-log
validator passed with 13 well-formed entries, and `git diff --check` passed.
New-file whitespace is checked separately before stage close.
The work remains uncommitted and unpushed. Under `Prompt.md`
Step 4, the agent stops after S1 and waits for human approval of S2; no such
approval has been supplied in this conversation.

## Further human instructions and S2

The human requested an independent feature branch using existing naming.
The repository listed `origin/feat/FR-002` but no local branch of that name.
The agent created local `feat/FR-002` from the verified HEAD, associated it
with the existing remote branch and verified that all 15 S1 working files,
the index/worktree status, HEAD baseline and integration ref were unchanged.
No commit or push was performed.

The human then instructed, verbatim:

> 继续实现s2和s3

This explicitly authorizes S2 and S3 in the previously approved plan, each
implemented and verified separately. The agent's initial acknowledgement
incorrectly said it would ask again before S3; it immediately clarified that
the human's instruction already authorizes both stages.

S2 connected the approved invocation boundary, callback logical identity,
optional debate/risk/reflection refusal, existing-context analyst wrap-up and
controlled failed/REVIEW results. Ordinary provider exceptions cannot turn a
budget refusal into another fallback. No-budget invocation shapes and existing
routing maps remain compatible. Diagnostic REVIEW states are not stored as
normal decisions in memory, and failed runs are not cleared as successful
checkpoints. CLI completion indicators respect controlled failure.

The first full run had 1825 passes and three new-test failures. Preserving
nested skip fields in the synthesis nodes and correcting a provider test
double resolved them. Review then found explicit-context callback ownership
and CLI completion display issues; both were corrected with regressions.
The final S2 `pytest -q` run passed **1829 tests**, with **6 skipped,
1 deselected, 24 warnings and 100 subtests passed in 49.27s**. Whole-repository
Ruff and registry/schema validation passed. Tests used the isolated temporary
runner with dotenv discovery disabled and UTF-8 mode; no live experiment ran.
AI-use-log and diff checks follow this record before S3 implementation begins.

## S3 implementation and acceptance (2026-11-18)

The S2 AI-use-log validator passed with 14 entries and tracked diff checks
passed before S3 started. The human's existing instruction authorizes S3;
no further approval or invented human decision was required. The agent
rechecked `git status --short`, preserved all existing S1/S2 work, and verified
branch `feat/FR-002` and unchanged HEAD
`889cc33cf60bc89573159438ff98191e17adba77`.

S3 implemented the previously approved public `token_budget` configuration,
environment and CLI flag; direct graph/stream/checkpoint contexts; versioned
durable usage ledgers; cumulative restore and lost-inflight uncertainty;
schema-2 budget metadata and Markdown/HTML explanations; and independent
backtest-cell/standalone-settlement accounting. It preserves QR-004's
`completed`/`failed` lifecycle and legacy flat fields. Explicit checkpoint
clearing also removes that thread's budget history so a new run is deliberate.

Review led to fixes within the approved recovery and compatibility scope:

- A restored node's repeated first attempt is an optional retry when its
  phase has already dispatched. Analyst contextual wrap-up has its own phase.
- Public `stream_run` and paired `begin_checkpoint`/`end_checkpoint` callers
  receive the same budget context and durable identity as `propagate`/CLI.
- Setup failures unwind contexts and SQLite resources, including CLI paths.
- Missing, corrupt or incompatible usage history produces controlled
  `failed`/`REVIEW`, with explicit reasons and no normal decision-memory write.
- A late/persistence error cannot be swallowed into another structured or
  reflection attempt. Old callbacks cannot recreate cleared ledgers.
- Cleanup errors after a valid synthesis preserve that valid completed
  result, record the cleanup reason as a budget warning (exhaustion has
  precedence), and keep report/JSON status consistent without an unhandled
  cleanup exception. No fictitious REVIEW recommendation is introduced.
- Legacy unbudgeted resumed history remains incomplete in both the canonical
  usage summary and the independent budget usage-state presentation.

Initial full verification had 17 failures and 1880 passes: newly added CLI
priority fixtures stopped at the existing unattended-input guard, minimal
memory/graph doubles lacked newly observed fields, and the historical
signature reference was incorrectly given the newly introduced None key.
The fixtures/reference and compatibility handling were corrected. A later
run had one old dataflow double returning None instead of Settlement; the
observational adapter now handles that legacy shape. A focused recovery test
was corrected to expect controlled refusal of a historical failed request
with unknown usage rather than another mandatory retry.

The final implementation passed full `pytest -q`: **1945 passed, 6 skipped,
1 deselected, 24 warnings, 100 subtests passed in 60.72s**. A separate full
run with a temporary collection hook and fixed shuffle seed **20261118**
passed the same counts in **62.21s**. This includes the explicit fresh-run
clear test and the final checkpoint error/memory persistence regressions.
Both runs used temporary working/profile/cache directories, clean environment,
disabled dotenv discovery, Python UTF-8 mode and the existing offline network
guard. No repository fixture, dependency or CI setting was added for shuffling.
Five skips reflect Windows/POSIX limitations; one is the absent optional
`langchain_aws`; the integration test remains deselected by existing settings.
Registry and template schema validation passed using the existing system
Python. Final log/scope/whitespace validation follows this actual record.

The reserve ratio and quantitative calibration remain TBD. No live request,
paid phase-token-share experiment, FR-006 implementation, commit, push or
merge occurred. The implementation awaits final human review.

Final handoff checks passed: whole-repository `ruff check .`, registry and
template schema validation, the AI-use-log validator with **15 well-formed
entries**, and `git diff --check`. The explicit scope/new-file check found
EOF whitespace in four generated tests; normalizing EOF whitespace changed
no executable statement. The repeated check passed for **33 tracked changes
and 23 new files**, verified the unchanged HEAD/feature branch and empty
staging area, and found no changes to excluded/frozen configuration,
credentials, requirement registry/schema, rules, CI or dependency files.
The final full/default and randomized test evidence above applies to the
same executable statements. Work remains uncommitted and unpushed.

## Human publication authorization (2026-11-18)

After the final implementation and verification report, the human instructed:

> 推送到远端仓库的 feat/FR-002 分支上面吧

This authorizes committing the verified S1–S3 FR-002 changes and pushing them
to `origin/feat/FR-002`. Pre-publication status matched the final 33 tracked
changes and 23 new files, on local `feat/FR-002` with an empty index and HEAD
`889cc33cf60bc89573159438ff98191e17adba77`. `git diff --check` passed. This
step adds only the true authorization record; the final 1945-test default
and fixed-seed randomized evidence above remains the executable acceptance
result. Remote identity and normal-push eligibility are checked through Git
before publication; the actual push outcome is reported after it completes.

## CI ANSI assertion repair and publication authorization (2026-11-18)

The human supplied the full Python 3.11 CI output: four failed assertions,
2002 passed, one skipped and one deselected. The failing cases were the three
invalid-budget parameter cases and the help-text case in
`test/offline/test_budget_configuration.py`. Invalid parameters already exited
with code 2 and help exited with code 0. Rich inserted ANSI styles inside
`--token-budget`, preventing the raw string assertions from finding it.
A controlled in-memory reproduction confirmed that decoding ANSI with
`rich.text.Text.from_ansi(...).plain` restores the contiguous option name.

The human then instructed, verbatim:

> 我已经把那个PR关掉了,那针对这个bug你先帮我在本地修改，然后再推送到远端仓库的Fr002分支

This authorizes the local test repair, verification, commit and normal push
to `origin/feat/FR-002`. It does not authorize test-plan approval, the
`test-approved` label, or creating, reopening or merging a PR.

The initial local worktree was clean on `feat/FR-002` at `500e236`.
The remote feature branch contained the human's integration conflict-resolution
merge. After fetching, local `feat/FR-002` was fast-forwarded to
`43f730b54efac6b59f08d24086ff645f00261abf`, matching the remote feature tip.
Git network access used the existing Windows web proxy for the individual
command; no persistent proxy configuration or credential content was changed.

The repair changes only the two affected test functions and adds a local
parametrized fixture. Each function exercises real Typer/Rich rendering in
both plain and forced-ANSI modes using StringIO. It verifies that the requested
mode actually emits or omits ANSI styles, then decodes the output before
checking the option/help text. The invalid-input guard still fails if analysis
starts, and the exit/help semantic assertions remain. Read-only delegated
review found no blockers. No production implementation, dependency, workflow,
requirement, interface or budget policy changed. The only other edited files
are this record and `docs/ai-use-log.yaml`, with all prior entries preserved.

Actual verification:

- Focused configuration module: **42 passed in 5.38s**, including both modes.
- Whole-repository `ruff check .`: **passed**.
- Registry and template schema validation: **passed** using system Python.
- The first full isolated run had **2004 passed and one failed**. Its temporary
  pre-collection socket guard incorrectly blocked the existing offline
  localhost callback test. The runner was corrected to allow only numeric
  `127.0.0.1`; the repository test was unchanged. That focused callback test
  then passed, and the full suite was rerun.
- Final full `pytest -q`, Windows/Python **3.12.10**: **2005 passed, 6 skipped,
  1 deselected, 24 warnings, 100 subtests passed in 65.79s**. Five skips are
  existing Windows/POSIX limitations; one is absent optional `langchain_aws`.
  Existing configuration excludes the integration test.
- Verification used temporary work/profile/cache directories, a clean
  environment, disabled dotenv discovery, external-network refusal and UTF-8
  mode. No live provider or paid experiment ran. No repository isolation
  fixture or CI configuration was changed.

Log validation, preservation of the prior 20 entries, three-file scope and
`git diff --check` are checked before commit. Push success and local/remote SHA
equality are verified after the network operation; they are not presumed here.
The local results do not claim that remote Python 3.11-3.14 CI has passed.

## Backtest isolation assertion repair (2026-11-18)

The human supplied a later Python 3.13 CI log with **1 failed, 2009 passed,
1 skipped and 1 deselected**. The remaining failure was
`test_fr002_backtest_budget_is_per_cell_and_controlled_failures_are_not_successes[MissedSynthesis-0]`:
two cells recorded 3 and 7 LLM calls, failing an equality assertion between
their snapshots. The ANSI configuration tests passed in that log.

Read-only review identified an invalid scheduling assumption. MissedSynthesis
returns no parsed structured result, so the Sentiment Analyst's optional
retry is refused at a zero budget. Concurrent tool analysts may have made
different progress when the graph ends with controlled failure. Independent
run accounting does not require their total call counts to match. Initial
local repetition of the unchanged module passed 60 tests across 20 module
collections, so the remote failure was not presented as locally reproduced
or as proof of Python 3.13 incompatibility or production ledger contamination.

The agent proposed a revised three-file scope: verify each cell's actual model
call increment and reported tokens against its own snapshot, preserve the
existing identity/budget/failure checks, update the two session records,
verify, then push under the prior publication authorization. The agent stopped
before changing files because this involved a different test file from the
ANSI repair. The human explicitly approved the revision:

> 确认

Work began from a clean `feat/FR-002` at
`4ad1530fa5559d0f6403b4d105e9c2cbcd881e17`; fetching the remote feature branch
confirmed the same tip. The repair changes only
`test/offline/test_budget_backtest.py` and appends these two records.
The test compares every snapshot with the model's call increment for that
cell and the fixture's reported 3 input, 2 output and 5 total tokens per call.
A local DateVaryingUsageModel returns a direct report on the first date and
uses the existing tool path on the second, making unequal successful-cell
call counts deterministic. It retains the existing usage callback behavior.
The MissedSynthesis case, independent run IDs, budget/blocked-call checks,
successful/failed cell counts and tail settlement checks remain. Product
routing, concurrency, accounting, interfaces, dependencies and CI are unchanged.
Delegated read-only review found no blockers.

Actual final verification on Windows/Python **3.12.10**:

- Focused backtest module: **3 passed in 2.17s**.
- Twenty repeated module collections: **60 passed in 13.16s**.
- A temporary in-memory mutation deliberately made the second snapshot
  cumulative. The repaired test rejected it with **17 ledger calls versus
  10 actual calls**. This is an expected negative-control result, not a
  failure of the normal suite; no mutation helper was written to the repository.
- Full `pytest -q`: **2005 passed, 6 skipped, 1 deselected, 24 warnings,
  100 subtests passed in 45.22s**. Existing Windows/POSIX and optional
  langchain_aws skips, and the integration deselection, remain unchanged.
- Whole-repository Ruff and registry/template schema validation: **passed**.
- Runs used temporary profile/work/cache directories, disabled dotenv
  discovery, UTF-8 mode and external-network refusal. No live provider ran.

Final AI-use-log validation, preservation of all prior 21 entries, append-only
records, exact three-file scope and whitespace checks precede commit.
Publication and local/remote SHA equality are verified after the normal push.
No teammate test-plan approval, test-approved label, PR approval or merge is
claimed. Python 3.13 CI must be assessed from the new remote run.
