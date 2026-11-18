"""Reusable report-tree writer shared by the CLI and the programmatic API.

Writes a run's per-section markdown (analysts, research, trading, risk,
portfolio) plus a consolidated ``complete_report.md`` under ``save_path``. The
CLI and ``TradingAgentsGraph.save_reports`` both call this, so a headless / API
run produces the same on-disk report tree a CLI run does.
"""

from datetime import datetime
from pathlib import Path

from tradingagents.agents.rating import run_rating


def analyst_names(keys) -> list[str]:
    """The analysts as users select them: the sentiment analyst's key is "social"."""
    return ["sentiment" if key == "social" else key for key in keys or []]


def _override_value(value):
    """Render one explicit-override value for the report header.

    An overridden analyst set reads as a comma list of the names users know; any
    other value (a round count) prints as-is.
    """
    if isinstance(value, (list, tuple)):
        return ", ".join(analyst_names(value))
    return value


def _token_usage_line(meta: dict, get) -> str | None:
    """The report's token-usage line (Implements: REQ-TA-QR-004).

    Renders complete usage as in/out/total counts; incomplete usage is shown as
    ``Tokens: unavailable`` so a partial total is never mistaken for a complete
    one. Presentation text only — the record keeps null values with
    ``usage_complete=false``.
    """
    complete = meta.get("usage_complete", get("usage_complete"))
    if complete:
        tokens_in = meta.get("tokens_in", get("tokens_in"))
        tokens_out = meta.get("tokens_out", get("tokens_out"))
        total = meta.get("total_tokens", get("total_tokens"))
        if isinstance(total, int) and total >= 0:
            return (f"- Tokens: {tokens_in} in, {tokens_out} out, {total} total")
    return "- Tokens: unavailable"


def _budget_line(budget: dict) -> str | None:
    """The run's budget result as one report line (Implements: REQ-TA-FR-002).

    Status and the aggregate usage state, plus a reason code. Unavailable
    totals are not printed; the token line already renders "unavailable".
    """
    status = budget.get("status")
    if not status:
        return None
    limit = budget.get("limit")
    state = budget.get("usage_state")
    reasons = budget.get("reason_codes") or []
    parts = [status]
    if limit is not None:
        parts.append(f"limit {limit}")
    if state:
        parts.append(f"usage {state}")
    if reasons:
        parts.append("reasons: " + ", ".join(reasons))
    return "- Budget: " + "; ".join(parts)


def _header(ticker: str, final_state: dict, settings: dict | None) -> str:
    """The report's title and what produced it: analysis date, version, models, analysts, vendors."""
    lines = [f"# Trading Analysis Report: {ticker}", ""]
    if final_state.get("trade_date"):
        lines.append(f"- Analysis date: {final_state['trade_date']}")
    if final_state.get("final_trade_decision"):
        lines.append(f"- Rating: {run_rating(final_state)}")
    traceability = _traceability_header(final_state)
    if traceability:
        lines.append(traceability)
    acceptance = _acceptance_header(final_state)
    if acceptance:
        lines.append(acceptance)
    lines.append(f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if settings:
        s = settings.get
        deep_provider = s("deep_think_provider") or s("llm_provider", "?")
        quick_provider = s("quick_think_provider") or s("llm_provider", "?")
        if deep_provider == quick_provider:
            models = f"{deep_provider}, deep {s('deep_think_llm', '?')}, quick {s('quick_think_llm', '?')}"
        else:   # each tier on its own provider (#1440)
            models = (f"deep {deep_provider} {s('deep_think_llm', '?')}, "
                      f"quick {quick_provider} {s('quick_think_llm', '?')}")
        lines.append(f"- TradingAgents {s('version', '?')}: {models}")
        lines.append(f"- Analysts: {', '.join(analyst_names(s('analysts')))}; "
                     f"research debate rounds {s('max_debate_rounds', '?')}, "
                     f"risk debate rounds {s('max_risk_discuss_rounds', '?')}, "
                     f"tool rounds per analyst {s('max_tool_rounds', '?')}")
        # What was asked for versus what took effect (Implements: REQ-TA-FR-001).
        if s("profile_requested"):
            lines.append(f"- Analysis profile: {s('profile_requested')} (requested)")
        overrides = s("profile_overrides") or {}
        if overrides:
            lines.append("- Explicit overrides: " + ", ".join(
                f"{key}={_override_value(value)}" for key, value in overrides.items()))
        vendors = {**(s("data_vendors") or {}), **(s("tool_vendors") or {})}
        if vendors:
            lines.append("- Data vendors: " + ", ".join(f"{k} {v}" for k, v in vendors.items()))
        # Observational run metadata (Implements: REQ-TA-QR-004): completion
        # status and token totals. The canonical fields live in run_metadata;
        # the flat run_settings() view carries them too, so read whichever is
        # present. Unavailable usage is shown as "unavailable", never as 0.
        meta = s("run_metadata") or {}
        status = meta.get("status") or s("status")
        if status:
            lines.append(f"- Run status: {status}")
        usage_complete = meta.get("usage_complete", s("usage_complete"))
        if usage_complete is not None:
            token_line = _token_usage_line(meta, s)
            if token_line:
                lines.append(token_line)
        # The run's budget result, a dimension separate from lifecycle status
        # (REQ-TA-FR-002; ADR-004). Shown only when a budget block was recorded.
        budget = meta.get("budget") or s("budget")
        if isinstance(budget, dict) and budget.get("status"):
            budget_line = _budget_line(budget)
            if budget_line:
                lines.append(budget_line)
    if final_state.get("memory_note"):
        lines.append(f"- Memory log: {final_state['memory_note']}")
    return "\n".join(lines) + "\n\n"


# The material-claim contract fixed by ADR-001: the final recommendation's
# supporting and opposing factor lists, this many per side.
CLAIMS_PER_SIDE = 3

# The report's own artifacts are the closed source vocabulary. ``source_id``
# resolves to (producing agent, state path); the model never names the agent.
_ANALYST_SOURCES = frozenset({
    "market_report", "sentiment_report", "news_report", "fundamentals_report",
})
# Claims that assert market data must carry the observation's date.
_MARKET_DATA_SOURCES = frozenset({"market_report"})
_NOT_A_SOURCE = frozenset({"final_trade_decision"})

# REQ-TA-FR-005: every report ends with this notice, in text and HTML alike.
NOT_INVESTMENT_ADVICE = (
    "Not investment advice. This report is for research and information purposes "
    "only and is not investment, financial, or trading advice."
)

# ADR-001 fail-closed activation (REQ-TA-QR-002, REQ-TA-INV-005): the acceptance
# verdict a run carries. A closed vocabulary of its own: it is neither a rating
# (REQ-TA-INV-001) nor a run status (REQ-TA-FR-006).
CLAIM_ACCEPTANCE_STATUSES = frozenset({"ACCEPTED", "REJECTED", "NOT_ENFORCED"})

CLAIM_NOT_ACCEPTED_NOTICE = (
    "This report is not accepted as an evidence-linked recommendation: at least one "
    "material claim could not be traced to a source report. Treat the "
    "recommendation as unsupported, not as a tradeable call."
)

# The verdict's own sentence when enforcement was off: the audit ran, but the
# run was never gated on it, so acceptance is not claimed either way.
CLAIM_NOT_CERTIFIED_NOTICE = (
    "Claim traceability is not enforced for this run, so this report is not "
    "certified as an evidence-linked recommendation."
)


def source_vocabulary() -> dict[str, tuple[str, tuple[str, ...]]]:
    """The artifacts a material claim may cite: source_id -> (agent, state path)."""
    vocabulary = {}
    for _heading, _folder, agents in _SECTIONS:
        for agent, _filename, path in agents:
            if ".".join(path) in _NOT_A_SOURCE:
                continue
            vocabulary[".".join(path)] = (agent, path)
    return vocabulary


def _artifact_value(final_state: dict, path: tuple[str, ...]):
    value = final_state
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _iso_date(value) -> str | None:
    """A canonical ``YYYY-MM-DD`` date, or None for anything else."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value if parsed.strftime("%Y-%m-%d") == value else None


def _claim_items(final_state: dict) -> list[dict]:
    """The run's claims in stable order, with deterministic ids (s1..., o1...)."""
    raw = final_state.get("material_claims")
    if not isinstance(raw, list):
        return []
    counts = {"supporting": 0, "opposing": 0}
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        declared = entry.get("kind")
        kind = declared if declared in counts else "supporting"
        counts[kind] += 1
        items.append({
            "id": f"{kind[0]}{counts[kind]}",
            "kind": kind,
            "declared_kind": declared,
            "text": entry.get("text"),
            "source_id": entry.get("source_id"),
            "observation_date": entry.get("observation_date"),
        })
    return items


def audit_material_claims(final_state: dict) -> dict:
    """Check that every material claim resolves to a report artifact (ADR-001).

    Pure: no I/O and no LLM. Implements REQ-TA-FR-005, REQ-TA-QR-002 and
    REQ-TA-INV-005. A run with no claim metadata is ``NOT_ASSESSED``, never
    ``ACCEPTED``; this slice does not downgrade the run itself.
    """
    items = _claim_items(final_state)
    if not items:
        reasons = ["NO_CLAIM_METADATA"]
        if final_state.get("claim_fallback") == "free_text":
            reasons.append("PM_FREETEXT_FALLBACK")
        return {
            "status": "NOT_ASSESSED",
            "reasons": reasons,
            "claims_total": 0,
            "claims_attributed": 0,
            "unsupported_claim_ids": [],
            "claims": [],
        }

    vocabulary = source_vocabulary()
    trade_date = _iso_date(final_state.get("trade_date"))
    reasons: list[str] = []
    unsupported: list[str] = []
    details: list[dict] = []

    def note(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    for item in items:
        claim_reasons: list[str] = []
        if item["declared_kind"] not in ("supporting", "opposing"):
            claim_reasons.append("INVALID_CLAIM")
        if not isinstance(item["text"], str) or not item["text"].strip():
            claim_reasons.append("UNTRACEABLE_CLAIM")

        source_id = item["source_id"]
        producer = None
        if not isinstance(source_id, str) or source_id not in vocabulary:
            claim_reasons.append("UNKNOWN_SOURCE")
        else:
            producer, path = vocabulary[source_id]
            if not _artifact_value(final_state, path):
                producer = None
                claim_reasons.append("UNKNOWN_SOURCE")

        raw_date = item["observation_date"]
        observed = _iso_date(raw_date)
        if raw_date not in (None, ""):
            if observed is None or (trade_date is not None and observed > trade_date):
                claim_reasons.append("INVALID_OBSERVATION_DATE")
        elif source_id in _MARKET_DATA_SOURCES:
            claim_reasons.append("UNDATED_MARKET_DATA")

        claim_reasons = list(dict.fromkeys(claim_reasons))
        attributed = not claim_reasons
        if not attributed:
            unsupported.append(item["id"])
            for reason in claim_reasons:
                note(reason)
        details.append({
            "id": item["id"],
            "kind": item["kind"],
            "text": item["text"],
            "source_id": source_id,
            "producer": producer,
            "observation_date": observed if observed else None,
            "attributed": attributed,
            "reasons": claim_reasons,
        })

    for kind in ("supporting", "opposing"):
        if sum(1 for item in items if item["kind"] == kind) > CLAIMS_PER_SIDE:
            note("CLAIM_LIMIT_EXCEEDED")

    attributed_details = [detail for detail in details if detail["attributed"]]
    if attributed_details:
        if not any(detail["source_id"] in _ANALYST_SOURCES for detail in attributed_details):
            note("NO_ANALYST_REFERENCE")
        if not any(detail["observation_date"] for detail in attributed_details):
            note("NO_DATED_OBSERVATION")

    return {
        "status": "DOWNGRADED" if reasons else "ACCEPTED",
        "reasons": reasons,
        "claims_total": len(items),
        "claims_attributed": len(attributed_details),
        "unsupported_claim_ids": unsupported,
        "claims": details,
    }


def evaluate_claim_acceptance(final_state: dict, *, enforced: bool) -> dict:
    """Derive the run's acceptance verdict from its claim audit (ADR-001).

    Pure: no I/O and no LLM. Implements REQ-TA-QR-002 and REQ-TA-INV-005: an
    untraceable material claim — or no claim metadata at all — prevents
    acceptance. With enforcement off the verdict says so instead of claiming
    acceptance. It never reads or writes the rating (REQ-TA-INV-001).
    """
    audit = audit_material_claims(final_state)
    reasons = list(audit["reasons"])
    if not enforced:
        status, notice = "NOT_ENFORCED", None
        if "CLAIM_ENFORCEMENT_DISABLED" not in reasons:
            reasons.append("CLAIM_ENFORCEMENT_DISABLED")
    elif audit["status"] == "ACCEPTED":
        status, notice = "ACCEPTED", None
    else:
        status, notice = "REJECTED", CLAIM_NOT_ACCEPTED_NOTICE
    return {
        "status": status,
        "audit_status": audit["status"],
        "enforced": enforced,
        "reasons": reasons,
        "notice": notice,
    }


def claim_acceptance_of(final_state: dict) -> dict:
    """The verdict recorded for this run, or the one this state would get.

    A state that never went through ``record_decision`` (a hand-built state, a
    partial run) is judged with enforcement on, so a report cannot render as
    accepted by omission.
    """
    recorded = final_state.get("claim_acceptance")
    if isinstance(recorded, dict) and recorded.get("status") in CLAIM_ACCEPTANCE_STATUSES:
        return recorded
    return evaluate_claim_acceptance(final_state, enforced=True)


def acceptance_notice_text(verdict: dict) -> str | None:
    """The sentence a rendering shows for a verdict that is not ``ACCEPTED``."""
    if verdict.get("status") == "ACCEPTED":
        return None
    return verdict.get("notice") or CLAIM_NOT_CERTIFIED_NOTICE


def render_claim_ledger(final_state: dict) -> str:
    """The markdown claim ledger: each factor with its source, date or UNSUPPORTED label."""
    items = _claim_items(final_state)
    if not items:
        return ""
    audit = audit_material_claims(final_state)
    details = {detail["id"]: detail for detail in audit["claims"]}
    status = (f"**Traceability: {audit['status']}** — "
              f"{audit['claims_attributed']} of {audit['claims_total']} material claims attributed.")
    if audit["reasons"]:
        status += " Reasons: " + ", ".join(audit["reasons"]) + "."

    lines = ["## Evidence Linkage", "", status]
    for label, kind in (("Supporting factors", "supporting"), ("Opposing factors", "opposing")):
        group = [item for item in items if item["kind"] == kind]
        if not group:
            continue
        lines.extend(["", f"### {label}"])
        for item in group:
            detail = details[item["id"]]
            line = f'- **{item["id"]}** "{item["text"]}" — '
            if detail["attributed"]:
                line += f"source: `{item['source_id']}` ({detail['producer']})"
                if detail["observation_date"]:
                    line += f" @ {detail['observation_date']}"
            else:
                line += f"UNSUPPORTED ({', '.join(detail['reasons'])})"
            lines.append(line)
    return "\n".join(lines)


def _traceability_header(final_state: dict) -> str | None:
    """The header line for a report that carries material claims."""
    if not final_state.get("material_claims"):
        return None
    audit = audit_material_claims(final_state)
    line = (f"- Traceability: {audit['status']} "
            f"({audit['claims_attributed']}/{audit['claims_total']} material claims attributed)")
    if audit["reasons"]:
        line += f"; {', '.join(audit['reasons'])}"
    return line


def _acceptance_header(final_state: dict) -> str | None:
    """The header line for a recommendation that is not accepted, and only then."""
    if not final_state.get("final_trade_decision"):
        return None
    verdict = claim_acceptance_of(final_state)
    if verdict["status"] == "ACCEPTED":
        return None
    line = f"- Acceptance: {verdict['status']}"
    if verdict["reasons"]:
        line += f" — {', '.join(verdict['reasons'])}"
    return line


def _acceptance_section(final_state: dict) -> str:
    """The ``## Acceptance`` block for a recommendation that is not accepted.

    It follows the header and precedes the sections, so a reader meets the
    verdict before the recommendation itself (REQ-TA-QR-002, REQ-TA-INV-005).
    A run with no claim metadata has no ledger, so this block is the only place
    the non-acceptance would otherwise be invisible.
    """
    if not final_state.get("final_trade_decision"):
        return ""
    verdict = claim_acceptance_of(final_state)
    if verdict["status"] == "ACCEPTED":
        return ""
    notice = acceptance_notice_text(verdict)
    reasons = (f" Reasons: {', '.join(verdict['reasons'])}." if verdict["reasons"] else "")
    return f"## Acceptance\n\n**{verdict['status']}** — {notice}{reasons}\n\n"


# The report's sections in order: (heading, folder, [(agent, file, state path)]).
_SECTIONS = (
    ("I. Analyst Team Reports", "1_analysts", (
        ("Market Analyst", "market.md", ("market_report",)),
        ("Sentiment Analyst", "sentiment.md", ("sentiment_report",)),
        ("News Analyst", "news.md", ("news_report",)),
        ("Fundamentals Analyst", "fundamentals.md", ("fundamentals_report",)),
    )),
    ("II. Research Team Decision", "2_research", (
        ("Bull Researcher", "bull.md", ("investment_debate_state", "bull_history")),
        ("Bear Researcher", "bear.md", ("investment_debate_state", "bear_history")),
        ("Research Manager", "manager.md", ("investment_plan",)),
    )),
    ("III. Trading Team Plan", "3_trading", (
        ("Trader", "trader.md", ("trader_investment_plan",)),
    )),
    ("IV. Risk Management Team Decision", "4_risk", (
        ("Aggressive Analyst", "aggressive.md", ("risk_debate_state", "aggressive_history")),
        ("Conservative Analyst", "conservative.md", ("risk_debate_state", "conservative_history")),
        ("Neutral Analyst", "neutral.md", ("risk_debate_state", "neutral_history")),
    )),
    ("V. Portfolio Manager Decision", "5_portfolio", (
        ("Portfolio Manager", "decision.md", ("final_trade_decision",)),
    )),
)


def _report_parts(final_state: dict) -> list[tuple[str, str, list[tuple[str, str, str]]]]:
    """The sections with something to say: (heading, folder, [(agent, file, text)])."""
    parts = []
    for heading, folder, agents in _SECTIONS:
        written = []
        for agent, filename, path in agents:
            value = final_state
            for key in path:
                value = (value or {}).get(key)
            if value:
                written.append((agent, filename, value))
        if written:
            parts.append((heading, folder, written))
    return parts


def _report_document(ticker: str, final_state: dict, settings: dict | None,
                     sections: list[str]) -> str:
    """The complete markdown report: header, acceptance verdict, sections, claim ledger, disclaimer."""
    body = _header(ticker, final_state, settings) + _acceptance_section(final_state)
    body += "\n\n".join(sections)
    ledger = render_claim_ledger(final_state)
    if ledger:
        body += "\n\n" + ledger
    return body + "\n\n---\n\n" + NOT_INVESTMENT_ADVICE + "\n"


def write_report_tree(final_state: dict, ticker: str, save_path, settings: dict | None = None,
                      html: bool = True) -> Path:
    """Save a completed run's reports to ``save_path``; return the complete-report path.

    ``settings`` (``TradingAgentsGraph.run_settings()``) adds what produced the run
    to the report's header. ``html`` also writes ``complete_report.html``, one
    self-contained page of the same report (#1419).
    Reusing a directory replaces the generated report files, removing sections
    absent from this run and disabled HTML. Other files and directories are kept.
    """
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)
    parts = _report_parts(final_state)
    sections = []
    for heading, folder, written in parts:
        (save_path / folder).mkdir(exist_ok=True)
        for _agent, filename, text in written:
            (save_path / folder / filename).write_text(text, encoding="utf-8")
        content = "\n\n".join(f"### {agent}\n{text}" for agent, _filename, text in written)
        sections.append(f"## {heading}\n\n{content}")

    (save_path / "complete_report.md").write_text(
        _report_document(ticker, final_state, settings, sections), encoding="utf-8"
    )
    if html:
        from tradingagents.report_html import render_report

        (save_path / "complete_report.html").write_text(
            render_report(ticker, final_state, settings, parts), encoding="utf-8"
        )
    else:
        (save_path / "complete_report.html").unlink(missing_ok=True)

    # Reconcile only the filenames owned by this writer; never clear the tree,
    # since callers may keep notes or other artifacts alongside the reports.
    current_files = {
        (folder, filename)
        for _heading, folder, written in parts
        for _agent, filename, _text in written
    }
    for _heading, folder, agents in _SECTIONS:
        for _agent, filename, _path in agents:
            if (folder, filename) not in current_files:
                (save_path / folder / filename).unlink(missing_ok=True)
    return save_path / "complete_report.md"
