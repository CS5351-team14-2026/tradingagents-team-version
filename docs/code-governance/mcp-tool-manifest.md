# MCP/tool manifest — what the coding agent may call (deliverable D3)

## MCP servers

**None configured.** This is the recorded baseline. Adding any MCP server is a
governance decision: it requires a PR touching this file, a human reviewer,
and an entry here before first use.

## Built-in tools by role

Roles come from `.opencode/permissions.jsonc` (planner / coder / verifier /
reviewer). File access is bounded by that permission model; this manifest
covers the tool surface on top of it.

| Tool | planner | coder | verifier | reviewer | Notes |
|---|---|---|---|---|---|
| file read (whitelisted paths) | ✅ | ✅ | ✅ | ✅ | secrets/`.env` never |
| file write (whitelisted paths) | ❌ | ✅ `src/ test/ prompts/` | ✅ `test/` | ✅ memos/debt/bug files only | per role whitelist |
| shell: read-only inspection (`ls`, `cat`, `git status/diff/log`) | ✅ | ✅ | ✅ | ✅ | |
| shell: `pytest` | ❌ | ✅ | ✅ | ✅ | offline suite by default |
| shell: `ruff check` / `ruff format` | ❌ | ✅ | ✅ | ✅ | format only on touched files |
| shell: `python tools/ci/*.py` validators | ✅ | ✅ | ✅ | ✅ | schema + log validation |
| shell: mutating `git` (`commit`, `push`) | ❌ | ✅ per branch model | ❌ | ❌ | direct push allowed to `integration`/feature branches only; `main` is PR-only (AGENTS.md §9) |
| `gh` read (`pr view`, `api` reads) | ✅ | ✅ | ✅ | ✅ | |
| `gh` mutating (`pr create`, label edits) | ❌ | ✅ with human review | ❌ | ❌ | PR creation is fine; approvals are human-only |
| network calls beyond package registries | ❌ | ❌ | ❌ | ❌ | live API access belongs to `test/live`, never the agent session |

## Rules

1. A role may only call tools listed for it; anything unlisted is denied
   (default-deny mirrors `.opencode/permissions.jsonc`).
2. Human-only actions: PR approval/merge, label `test-approved`, branch
   protection changes, `.opencode/rules.md` authorship.
3. Every tool call that changes the repository happens inside an agent session
   that is logged (AI-use log, gate 6, once the log exists at kickoff).
