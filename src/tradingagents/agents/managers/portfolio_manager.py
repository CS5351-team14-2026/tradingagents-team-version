"""Portfolio Manager: synthesises the risk-analyst debate into the final decision.

Uses LangChain's ``with_structured_output`` so the LLM produces a typed
``PortfolioDecision`` directly, in a single call. Its rating is the run's
``final_rating``, and the decision is rendered to markdown as
``final_trade_decision`` for the memory log, CLI display and saved reports.
The node also returns ``material_claims``: the structured supporting and
opposing factors, each linked to a report artifact (ADR-001).
When a provider does not expose structured output, the agent falls back to
free-text generation and the rating is read from that text.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from tradingagents.agents.context import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_portfolio_context_from_state,
    report_or_absent,
)
from tradingagents.agents.rating import (
    parse_rating,
    validate_final_decision,
)
from tradingagents.agents.schemas import (
    CLAIM_SOURCE_IDS,
    PortfolioDecision,
    StrictJSONDecodeError,
    build_decision,
    decision_raw_mapping,
    decode_strict_json,
    raw_model_text,
    render_pm_decision,
)
from tradingagents.agents.structured import NO_EXTERNAL_TOOLS, bind_structured
from tradingagents.llm_clients.invocation import admit_optional

logger = logging.getLogger(__name__)

# The four analyst reports the recommendation must rest on, at least in part
# (ADR-001; REQ-TA-QR-002): the analyst's name, the word an absent-report marker
# uses, and the source_id a claim cites. The audit's NO_ANALYST_REFERENCE
# downgrade is what enforces the requirement; this table only labels the prompt.
PRIMARY_ANALYST_REPORTS = (
    ("Market Analyst", "market", "market_report"),
    ("Sentiment Analyst", "sentiment", "sentiment_report"),
    ("News Analyst", "news", "news_report"),
    ("Fundamentals Analyst", "fundamentals", "fundamentals_report"),
)
PRIMARY_ANALYST_SOURCES = tuple(source for _analyst, _short, source in PRIMARY_ANALYST_REPORTS)


def primary_analyst_evidence(state) -> str:
    """The analysts' own reports, each labelled with the source_id a claim may cite.

    The risk debate quotes these reports; reading them here lets a claim rest on
    the primary evidence rather than on a paraphrase of it (REQ-TA-QR-002). A
    report the run never produced is marked absent, not blank, so the model does
    not read an omission as a finding.
    """
    return "\n".join(
        f"- **{analyst}** (`{source}`): " + report_or_absent(state.get(source), short)
        for analyst, short, source in PRIMARY_ANALYST_REPORTS
    )


def _structured_with_raw(structured_llm, prompt, agent_name):
    """Run the structured call keeping the raw payload, retrying once; ``None`` on a miss.

    Mirrors :func:`tradingagents.agents.structured.invoke_structured` — the same
    one retry, the same budget gate on the retry — but returns the raw mapping the
    model produced alongside the decision, so the final-decision validator can
    read ``entry_price``/``stop_loss`` as written rather than as coerced
    (Implements: REQ-TA-FR-004). An unparsable body is a miss, exactly as before.
    """
    if structured_llm is None:
        return None
    for attempt in range(2):
        if attempt and not admit_optional("retry").allowed:
            logger.warning("%s: budget refused the structured retry; not retrying", agent_name)
            return None
        try:
            result = structured_llm.invoke(prompt)
            if result is None:
                raise ValueError("structured output returned no parsed result")
            raw = decision_raw_mapping(result)
            if raw is None:
                raise ValueError("structured output was not a decision")
            decision = result if isinstance(result, PortfolioDecision) else build_decision(raw)
            return decision, raw
        except Exception as exc:
            if attempt == 0:
                logger.warning(
                    "%s: structured-output invocation failed (%s); retrying the "
                    "structured call once", agent_name, exc)
                continue
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc)
            return None
    return None


def _invoke_json_mode(llm, prompt) -> tuple[PortfolioDecision, dict] | None:
    """Retry the decision as JSON before free text (deepseek-flash misses tool calls).

    Returns the decision plus the raw mapping it decoded from, so the same price
    validation runs on a JSON-mode answer as on a schema answer
    (Implements: REQ-TA-FR-004). A bare ``NaN``/``Infinity`` token is a strict
    decode failure and becomes a miss, following the existing fallback path.

    The bare-token check happens at the *raw-response* layer: the binding is made
    with ``include_raw=True`` so the untouched ``AIMessage`` is available. The
    provider's own parser (``json.loads``) would turn a bare ``NaN`` into a
    ``PortfolioDecision`` with ``float('nan')`` and hide the decode failure, so the
    raw text is strict-decoded first (ADR-003 §6). A body that *does* decode — even
    one carrying a rejected price — is not re-decoded here; its prices go to the
    normal validator, which returns ``invalid_*`` and does not retry (ADR-003 §5).
    """
    try:
        structured_json = llm.with_structured_output(
            PortfolioDecision, method="json_mode", include_raw=True)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning("PM: json_mode retry failed (binding: %s)", exc)
        return None
    try:
        result = structured_json.invoke(prompt)
        if result is None:
            raise ValueError("json_mode returned no result")
        result, raw = _json_mode_payload(result)
        if result is None:
            raise ValueError("json_mode returned no decision")
        return result, raw
    except StrictJSONDecodeError as exc:
        logger.warning("PM: json_mode retry failed (strict decode: %s)", exc)
        return None
    except Exception as exc:
        logger.warning("PM: json_mode retry failed (%s)", exc)
        return None


def _json_mode_payload(result) -> tuple[PortfolioDecision | None, dict]:
    """Normalise a JSON-mode result to ``(decision, raw_mapping)``; miss on failure.

    Two shapes reach here. The real binding (``include_raw=True``) returns a dict
    of ``raw`` / ``parsed`` / ``parsing_error``; the raw text is strict-decoded so a
    bare non-finite token is a decode miss before the parser's value is trusted.
    A test double (or an older binding) returns the decision directly; that is the
    already-decoded case, validated on its own prices (a decoded non-finite float
    is an ``invalid_*`` price, not a decode miss).
    """
    if isinstance(result, dict) and ("raw" in result or "parsed" in result):
        parsed = result.get("parsed")
        parsing_error = result.get("parsing_error")
        raw_text = raw_model_text(result.get("raw"))
        if raw_text is not None:
            # Judge the raw body first: a bare NaN/Infinity/-Infinity (or any
            # non-strict body) is a decode miss, not a supplied price.
            decoded = decode_strict_json(raw_text)
            if parsed is None or parsing_error is not None:
                raise StrictJSONDecodeError(str(parsing_error or "unparsable body"))
            if not isinstance(decoded, Mapping):
                raise StrictJSONDecodeError("a decision body must be a JSON object")
            return build_decision(decoded), dict(decoded)
        # No raw body to judge (empty content): defer to the parser's result.
        if parsed is None:
            return None, {}
        raw = decision_raw_mapping(parsed)
        if raw is None:
            raise ValueError("json_mode returned no decision")
        return (parsed if isinstance(parsed, PortfolioDecision) else build_decision(raw)), raw

    raw = decision_raw_mapping(result)
    if raw is None:
        raise ValueError("json_mode returned no decision")
    decision = result if isinstance(result, PortfolioDecision) else build_decision(raw)
    return decision, raw


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)
        portfolio_context = get_portfolio_context_from_state(state)

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]
        analyst_evidence = primary_analyst_evidence(state)
        primary_sources = ", ".join(PRIMARY_ANALYST_SOURCES)

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions and outcomes:\n{past_context}\n"
            if past_context
            else ""
        )

        prompt = f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.

{instrument_context}

{portfolio_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction to enter or add to position
- **Overweight**: Favorable outlook, gradually increase exposure
- **Hold**: Maintain current position, no action needed
- **Underweight**: Reduce exposure, take partial profits
- **Sell**: Exit position or avoid entry

**Context:**
- Research Manager's investment plan: **{research_plan}**
- Trader's transaction proposal: **{trader_plan}**
{lessons_line}
**Primary analyst evidence:**
{analyst_evidence}

**Risk Analysts Debate History:**
{history}

---

Ground every conclusion in specific evidence from the analysts. The risk debate always contains conflicting stances; deciding which is stronger is the job, so conflict alone is not a reason to Hold. Commit to the stronger case, sized by how decisively it wins. Choose Hold only when the evidence is still balanced after that weighing, or too thin to support a call; do not force a direction to appear decisive. Weigh the analysts on their merits, independent of speaking order.

## Output

Write these sections, in this order, starting with the rating on its own line:

- **Rating**: exactly one of Buy / Overweight / Hold / Underweight / Sell
- **Confidence**: exactly one of low / medium / high
- **Executive Summary**: the call and how to act on it
- **Investment Thesis**: the evidence that decided it, and what would change it
- **Supporting Factors**: exactly three material claims that support the rating
- **Opposing Factors**: exactly three material claims that argue against it

Set **Confidence** from the evidence and the analysts' disagreement:
- **low**: the evidence is thin, or the analysts strongly disagree.
- **medium**: the evidence is adequate but mixed, or disagreement is material.
- **high**: the evidence is strong and consistent across analysts, with only
  minor disagreement.

For every factor, give one `source_id` naming the report it came from, chosen
from: {CLAIM_SOURCE_IDS}. Give `observation_date` as YYYY-MM-DD whenever the
claim asserts market data (a price or indicator); omit it for qualitative
claims. Do not name the producing agent: it is derived from the source.

At least one of the six material claims must cite a primary analyst report,
chosen from: {primary_sources}. Take the figure or finding from that report
itself, not from the debate's paraphrase of it. A recommendation whose claims
cite only the research, trader or risk sections is downgraded by the
traceability check.

{NO_EXTERNAL_TOOLS}{get_language_instruction()}"""

        # The typed rating is the decision; the rendered text only carries it.
        # Read back from text, a rating the thesis quotes could replace it.
        # The structured call (with its own gated retry) is the required
        # synthesis; the JSON-mode retry and free-text fallback are optional and
        # stop once the budget refuses (Implements: ADR-004; REQ-TA-FR-002).
        # Each answer keeps the raw payload it came from, so the final-decision
        # validator reads the prices as written (Implements: REQ-TA-FR-004).
        result = _structured_with_raw(structured_llm, prompt, "Portfolio Manager")
        if result is None and admit_optional("pm_json_retry").allowed:
            result = _invoke_json_mode(llm, prompt)

        decision = None
        raw_prices: dict = {}
        decision_review_reasons: list[str] = []
        claims = []
        if result is not None:
            decision, raw = result
            # A decoded decision is validated as a whole (REQ-TA-FR-004): its
            # rating must resolve, and every supplied price must be a finite,
            # strictly positive number (both required for Buy/Overweight). An
            # invalid price is terminal REVIEW — never a retry that borrows a
            # price from somewhere else.
            final_rating, decision_review_reasons, raw_prices = validate_final_decision(
                decision.rating.value, raw)
            final_trade_decision = render_pm_decision(decision)
            # ADR-001: a material claim is exactly an item in these two lists.
            claims = [
                {
                    "kind": kind,
                    "text": claim.text,
                    "source_id": claim.source_id,
                    "observation_date": claim.observation_date,
                }
                for kind, factors in (
                    ("supporting", decision.supporting_factors),
                    ("opposing", decision.opposing_factors),
                )
                for claim in factors
            ]
        else:
            # The free-text fallback is optional; if the budget refuses it, the
            # run still ends with a controlled, non-tradeable REVIEW rather than
            # an uncaught error or a fabricated recommendation (ADR-004 D4).
            if admit_optional("pm_fallback").allowed:
                final_trade_decision = llm.invoke(prompt).content
            else:
                final_trade_decision = (
                    "No recommendation could be produced within the token budget; "
                    "the run ended with REVIEW for human review."
                )
            # The prose carries no price levels, so its rating is run through the
            # same price policy the decoded paths use: a free-text Buy/Overweight
            # (which requires prices) becomes REVIEW with the two missing-price
            # reasons; Hold/Underweight/Sell need none and pass unchanged. This
            # reuses the validator rather than inventing a second rule
            # (REQ-TA-FR-004; ADR-003 §6).
            prose_rating = parse_rating(final_trade_decision)
            final_rating, decision_review_reasons, _ = validate_final_decision(
                prose_rating, {})

        new_risk_debate_state = {
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
            "final_rating": final_rating,
            # REQ-TA-FR-004: why a decoded decision was not actionable; empty
            # when it was accepted. At least one reason means final_rating=REVIEW.
            "decision_review_reasons": decision_review_reasons,
            "material_claims": claims,
            # ADR-001: makes a structured-output miss visible to the audit,
            # which otherwise cannot tell it from a model that emitted no claims.
            "claim_fallback": None if decision is not None else "free_text",
        }

    return portfolio_manager_node
