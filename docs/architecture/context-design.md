# Context design — what the AI component receives each turn

> Deliverable D2.2, AI-component section: the layered context structure, the
> assembly pipeline, the token budget, and the constraint re-injection stance.
> This document describes the **implemented** context path with file
> references. Where a mechanism does not exist, it says so explicitly; nothing
> here is aspirational unless marked "not implemented".

## 1. Layered context structure

Every agent turn is assembled from up to six layers. The layers are fixed by
the prompt builders in `src/tradingagents/agents/**`; there is no dynamic layer
injection.

| Layer | Contents | Source | Agents that receive it |
| --- | --- | --- | --- |
| 1. Identity | Resolved instrument identity (ticker, company name, exchange, asset type) | `agents/context.py` `build_instrument_context`, `resolve_instrument_identity`; `REQ-TA-INV-007` makes this deterministic | every agent |
| 2. Standing constraints | Role definition, output contract (rating scale, confidence scale, claim rules), `NO_EXTERNAL_TOOLS`, language instruction | inline system messages; `agents/structured.py` `NO_EXTERNAL_TOOLS`; `agents/context.py` `get_language_instruction` | every agent |
| 3. Retrieved knowledge | Tool observations (market data, indicators, news, fundamentals, social posts), the four analyst reports, memory lessons | tool layer (`agents/tools.py`), analyst reports in state, `memory/log.py` `get_past_context(n_same=5, n_cross=3)` | analysts (tools); researchers/managers/trader (reports); portfolio manager (lessons) |
| 4. Conversation history | Per-analyst message history (thought → tool call → observation, accumulated); Bull/Bear debate history; three-way risk debate history; research plan; trader plan | LangGraph state (`agents/state.py`), per-analyst subgraph message list (`graph/setup.py`) | the agent that owns the thread; downstream agents receive the rendered histories |
| 5. Resumable state | Checkpointed graph state + run signature; optional and off by default | `graph/checkpointer.py`, `graph/trading_graph.py` begin/end checkpoint | restored run |
| 6. Current task | The turn-specific instruction: analyst task + asset-type wording, opponent's last argument, wrap-up message, or the decision request | agent factories; `agents/context.py` `opponent_argument_or_opening`; `agents/analysts/turn.py` `WRAP_UP` | the agent being called |

## 2. Assembly pipeline

Implemented order (portfolio manager, the richest case —
`agents/managers/portfolio_manager.py`):

```
identity (instrument context)
  → portfolio context (caller's standing book, if any)
  → standing constraints (rating scale, context block)
  → memory lessons (past decisions + outcomes, point-in-time filtered)
  → primary analyst evidence (the four analyst reports, each labelled with
    its source_id; absent reports are marked)
  → debate history (risk analysts)
  → instruction (evidence discipline, output contract, claim rules)
  → tool policy + language instruction
```

Other agents follow the same pattern with a subset of layers: analysts get
identity + standing constraints + their own tool loop; researchers get identity
+ the four analyst reports + debate history; the trader gets identity + research
plan + market report + portfolio context.

What each pipeline stage does **today**:

| Stage (course vocabulary) | Implemented as | Notes |
| --- | --- | --- |
| Retrieve | reading state fields and the memory log | memory read is point-in-time filtered (`as_of`) |
| De-duplicate | not a separate step; duplication is prevented structurally | fixed claim counts (3+3), one report per analyst, `report_or_absent` marks a missing report instead of repeating history |
| Prioritise | fixed layer order | standing constraints and identity always precede retrieved content |
| Budget | list caps + per-call output cap + per-run optional-call budget | see §3 |
| Compact | **not implemented** | no summarisation or truncation of conversation history |
| Assemble | f-string / `ChatPromptTemplate` | single prompt per call |

## 3. Token budget

Three independent mechanisms bound context size:

1. **Structural caps** (by construction, always active):

| Cap | Default | Where |
| --- | --- | --- |
| Ticker news articles | 20 | `default_config.py` `news_article_limit` |
| Global/macro news | 10, 7-day lookback | `global_news_article_limit`, `global_news_lookback_days` |
| Memory lessons | 5 same-ticker + 3 cross-ticker | `memory/log.py` `get_past_context` |
| Material claims | exactly 3 supporting + 3 opposing | ADR-001, `agents/schemas.py` |
| Analyst tool rounds | 20 per analyst | `max_tool_rounds` |
| Debate rounds | 1 (2 turns per round) | `max_debate_rounds` |
| Risk discussion rounds | 1 (3 turns per round) | `max_risk_discuss_rounds` |
| Graph recursion | 100 | `max_recur_limit` |

2. **Per-call output cap**: optional `max_tokens`, forwarded to every provider
   client (`default_config.py`, `llm_clients/factory.py`).

3. **Per-run optional-call budget**: a recorded-usage ceiling that stops
   *subsequent optional* calls (ADR-004, `run_budget.py`). It bounds total
   spend, not a single prompt's size.

There is **no context-window percentage threshold and no compaction trigger**:
the architecture keeps prompts bounded by construction (fixed list sizes and
round caps) rather than by summarising history.

## 4. Constraint re-injection

**Not implemented.** No layer is re-injected after compaction because no
compaction exists. The standing constraints (layer 2) are re-sent verbatim on
every call — they are part of every prompt, not a periodic reminder. The
nearest analogue is the analyst wrap-up turn (`agents/analysts/turn.py`
`WRAP_UP`), which re-states the reporting duty when the tool-round cap is hit.

If a future change introduces long histories that need compaction, the design
constraint is: layer 2 (standing constraints) and layer 1 (identity) must be
excluded from any summarisation and re-sent verbatim after each compaction;
compaction must be driven by the assembly pipeline, not by a user command.

## 5. Known limits (honest list)

- Conversation history grows with tool rounds and debate rounds; only the
  round caps bound it. A run configured with high caps can produce large
  prompts.
- There is no summarisation of earlier debate turns; every turn sees the full
  rendered history.
- Memory lessons are inserted without semantic ranking; selection is by recency
  and ticker scope.
- The per-run budget stops *new* optional calls; it does not shrink the prompt
  of a call already admitted.

These are recorded in `docs/debt-register.md` (DEBT-005).
