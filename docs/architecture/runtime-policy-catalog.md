# Runtime policy catalog

> Deliverable D2.7: for every degradation or failure path, what the system
> does. Statuses and codes below are the ones implemented in code; ADR
> references identify the decision that fixed each contract.

## 1. LLM and agent failures

| Trigger | System response | Status / code | ADR |
| --- | --- | --- | --- |
| Provider call times out | Controlled return: no escaping exception; run ends with a failure record and a non-actionable rating | `run_metadata.status=failed`, `failure.code=PROVIDER_TIMEOUT`, `final_rating=REVIEW` | ADR-005 |
| Agent returns invalid JSON | One structured retry (json-mode), then a controlled failure or free-text fallback depending on the agent | `INVALID_AGENT_JSON` when no valid decision is produced; PM free text sets `claim_fallback=free_text` | ADR-005, ADR-001 |
| Missing API key at construction | Fail before any LLM call with a safe diagnostic | `MISSING_API_KEY` | ADR-005 |
| Structured output unsupported by provider | Free-text fallback; the rating is parsed from text; claims become unauditable | `claim_audit=NOT_ASSESSED` → `claim_acceptance=REJECTED` under enforcement | ADR-001 |

## 2. Data failures

| Trigger | System response | Signal |
| --- | --- | --- |
| Vendor unreachable / vendor chain exhausted | Report unavailability, never fabricate | `DATA_UNAVAILABLE` message to the agent |
| Symbol has no data | Distinguish absence from outage | `NO_DATA_AVAILABLE … do not fabricate` |
| Optional category (macro, prediction markets) unavailable | Degrade to an explicit sentinel | category-specific sentinel, never silently empty |
| Requested date after the run date | Clamp to the run date; withhold live-only data | point-in-time notice (INV-002) |
| Stock data unavailable for the run | Controlled failure | `STOCK_DATA_UNAVAILABLE`, `REVIEW` |

## 3. Budget (ADR-004)

| Trigger | System response |
| --- | --- |
| No budget configured | `BUDGET_OK` + `NOT_CONFIGURED`; usage still observed |
| Recorded usage below the limit | `BUDGET_OK` + `WITHIN_RECORDED_BUDGET`; optional calls allowed |
| Recorded usage reaches the limit | `BUDGET_EXHAUSTED` + `RECORDED_USAGE_REACHED_LIMIT`; **no new optional call starts** |
| Recorded usage exceeds the limit (in-flight calls) | `BUDGET_EXHAUSTED` + `RECORDED_USAGE_EXCEEDED_LIMIT`; no cancellation claimed |
| Usage not reported by the provider | Usage recorded as unavailable — never estimated, never treated as zero |
| Budget exhausted before synthesis | Controlled failure, not an uncaught error: `TOKEN_BUDGET_EXHAUSTED`, `REVIEW` | 
| Ledger history missing/corrupt after resume | Controlled failure — history is never reset to zero |

## 4. Decision and claim acceptance (ADR-001, ADR-003)

| Trigger | System response |
| --- | --- |
| Rating invalid/ambiguous/contradictory | `final_rating=REVIEW` (INV-001), never a tradeable call |
| Price fields not finite numbers | Decision rejected as non-actionable (`REVIEW`) |
| Claim cites an unknown source / empty claim text | `claim_audit=DOWNGRADED`, reason `UNKNOWN_SOURCE` / `UNTRACEABLE_CLAIM`; claim labelled `UNSUPPORTED` |
| Observation date missing for market data, unparsable, or after the run date | `DOWNGRADED` with `UNDATED_MARKET_DATA` / `INVALID_OBSERVATION_DATE` |
| No analyst report among attributed claims | `DOWNGRADED` with `NO_ANALYST_REFERENCE` |
| No dated observation among attributed claims | `DOWNGRADED` with `NO_DATED_OBSERVATION` |
| More than three claims per side | `DOWNGRADED` with `CLAIM_LIMIT_EXCEEDED` |
| No claim metadata at all | `NOT_ASSESSED` (`NO_CLAIM_METADATA`, optionally `PM_FREETEXT_FALLBACK`) — never `ACCEPTED` |
| Audit not accepted | `claim_acceptance=REJECTED` (downgraded report, rating unchanged, memory entry kept) |
| Enforcement explicitly disabled | `claim_acceptance=NOT_ENFORCED` with `CLAIM_ENFORCEMENT_DISABLED` — never reads as acceptance |

## 5. Secrets (ADR-006)

| Trigger | System response |
| --- | --- |
| HTTP error carrying a key query parameter | Re-raised with the parameter masked, no exception chain carrying the URL |
| A PR introduces a possible secret | CI secret scan fails, merge blocked |
| A PR changes `.secrets.baseline` | Requires the `secret-baseline-approved` label; the scan compares against the **base** branch baseline so a re-baselined secret is still reported |

## 6. Interruption and resume

| Trigger | System response |
| --- | --- |
| Checkpoint enabled, run interrupted | Resume from the last node; input fed as `None` to avoid duplicated state |
| Configuration changed since the checkpoint | Run signature mismatch → fresh start, old checkpoint ignored |
| Successful completion | Checkpoint cleared |

## 7. Degradation ordering

Deterministic code always outranks model text: point-in-time clamps and vendor
withholding run before data reaches an agent; budget admission runs before an
optional call; the claim audit and rating validation run after generation and
before acceptance; redaction runs at every output boundary. A model statement
can never upgrade a deterministic verdict.
