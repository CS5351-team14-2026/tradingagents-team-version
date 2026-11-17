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

from tradingagents.agents.context import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_portfolio_context_from_state,
    report_or_absent,
)
from tradingagents.agents.rating import parse_rating
from tradingagents.agents.schemas import (
    CLAIM_SOURCE_IDS,
    PortfolioDecision,
    render_pm_decision,
)
from tradingagents.agents.structured import NO_EXTERNAL_TOOLS, bind_structured, invoke_structured

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


def _invoke_json_mode(llm, prompt) -> PortfolioDecision | None:
    """Retry the decision as JSON before free text (deepseek-flash misses tool calls).

    A json_mode result is still a structured decision, so the claims/rating path
    is unchanged and ``claim_fallback`` stays ``None`` (ADR-001).
    """
    try:
        structured_json = llm.with_structured_output(PortfolioDecision, method="json_mode")
    except (NotImplementedError, AttributeError) as exc:
        logger.warning("PM: json_mode retry failed (binding: %s)", exc)
        return None
    try:
        result = structured_json.invoke(prompt)
        if result is None:
            raise ValueError("json_mode returned no result")
        if isinstance(result, PortfolioDecision):
            return result
        return PortfolioDecision.model_validate_json(result)
    except Exception as exc:
        logger.warning("PM: json_mode retry failed (%s)", exc)
        return None


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
        decision = invoke_structured(structured_llm, prompt, "Portfolio Manager")
        if decision is None:
            decision = _invoke_json_mode(llm, prompt)
        claims = []
        if decision is not None:
            final_trade_decision = render_pm_decision(decision)
            final_rating = decision.rating.value
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
            final_trade_decision = llm.invoke(prompt).content
            final_rating = parse_rating(final_trade_decision)

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
            "material_claims": claims,
            # ADR-001: makes a structured-output miss visible to the audit,
            # which otherwise cannot tell it from a model that emitted no claims.
            "claim_fallback": None if decision is not None else "free_text",
        }

    return portfolio_manager_node
