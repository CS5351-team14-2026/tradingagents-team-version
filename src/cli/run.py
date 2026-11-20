"""Running one analysis from the CLI: build the graph, stream it into the live view, save the report."""

import os
import sys
import time
import webbrowser
from contextlib import suppress
from datetime import datetime
from functools import wraps
from pathlib import Path

import typer
from rich.live import Live

from cli.display import (
    ANALYST_ORDER,
    AnalystWallTimeTracker,
    classify_message_type,
    console,
    create_layout,
    display_complete_report,
    message_buffer,
    update_analyst_statuses,
    update_display,
    update_research_team_status,
)
from cli.selections import depth_from_env, get_user_selections, requested_profile, unattended_gaps
from cli.stats_handler import StatsCallbackHandler
from tradingagents import __version__ as ta_version, run_record as record
from tradingagents.agents.rating import RATING_REVIEW, is_review, run_rating
from tradingagents.dataflows.symbols import safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.failure import MissingApiKeyError
from tradingagents.graph.analyst_execution import (
    build_analyst_execution_plan,
)
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import decision_display_text
from tradingagents.run_budget import RunBudgetContext, RunBudgetTracker
from tradingagents.run_record import build_usage_summary


def _iso_timestamp(epoch_seconds: float) -> str:
    """A local-timezone ISO-8601 timestamp for a run's start/finish (REQ-TA-QR-004)."""
    return datetime.fromtimestamp(epoch_seconds).astimezone().isoformat(timespec="seconds")


def _run_directory(config: dict, ticker: str, trade_date: str) -> Path:
    """Where this run writes, with the ticker validated as a path component.

    Every other path that interpolates a ticker checks it first; a value of
    ".." here would place the run outside the results directory.
    """
    return Path(config["results_dir"]) / safe_ticker_component(ticker) / trade_date


def _terminal_failure(final_state: dict, tracker) -> dict | None:
    """The CLI's terminal controlled-failure block, mirroring ``_run_graph`` (ADR-005).

    Implements REQ-TA-QR-001 for the CLI stream path (which does not go through
    ``_run_graph``): if core market data was unavailable, force the result to
    REVIEW (D-D1) and record ``STOCK_DATA_UNAVAILABLE``; else, a REVIEW produced
    only because the token budget was exhausted records ``TOKEN_BUDGET_EXHAUSTED``.
    Returns ``None`` when neither applies.
    """
    from tradingagents import data_signal, failure as failure_mod

    if data_signal.core_data_unavailable():
        final_state["final_rating"] = RATING_REVIEW
        return failure_mod.build_failure(
            failure_mod.FailureCode.STOCK_DATA_UNAVAILABLE, phase="analysis")
    if is_review(run_rating(final_state)) and tracker is not None \
            and tracker.snapshot().status == "BUDGET_EXHAUSTED":
        return failure_mod.build_failure(
            failure_mod.FailureCode.TOKEN_BUDGET_EXHAUSTED, phase="synthesis")
    return None


def _record_startup_failure(config: dict, selections: dict, exc: MissingApiKeyError) -> None:
    """Write a controlled failure record when a run cannot even be constructed.

    REQ-TA-QR-001 (ADR-005 D-B): a missing API key surfaces before any graph or
    run exists, so this writes the standalone run record directly to disk with
    ``status=failed`` and ``run_metadata.failure.code=MISSING_API_KEY``. It never
    records the key value, an endpoint, or a local path (the run-record allowlist
    holds). A write failure is swallowed so the CLI diagnostic is still shown.
    """
    import json

    try:
        settings = record.build_run_record(
            replayable_settings={},
            status=record.STATUS_FAILED,
            version=ta_version,
            failure=exc.to_failure(),
        ).to_dict()
        directory = (Path(config["results_dir"])
                     / safe_ticker_component(selections["ticker"])
                     / "TradingAgentsStrategy_logs")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"run_record_{selections['analysis_date']}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception:  # never mask the CLI diagnostic with a record-write error
        pass


def _announce_checkpoint_state(graph, ticker: str, trade_date: str) -> None:
    """Say whether this run resumed a saved one, where the user can see it.

    The graph logs this, but nothing in the CLI configures logging and the live
    view owns the screen, so a resume was invisible.
    """
    if getattr(graph, "_resuming", False):
        message_buffer.add_message(
            "System", f"Resuming the saved run for {ticker} on {trade_date}"
        )
    else:
        message_buffer.add_message("System", f"Starting fresh for {ticker} on {trade_date}")


def _build_run_config(selections: dict, checkpoint: bool | None, profile: str | None = None,
                      token_budget: int | None = None) -> dict:
    """Assemble the run config from interactive selections, honoring env precedence.

    Round counts and checkpoint follow "explicit env/flag wins": an env-applied
    value on DEFAULT_CONFIG is preserved unless the user overrode it on the CLI.

    With a profile selected, the profile (resolved later by the graph) owns the
    round budgets; the interactive research-depth answer is not written into the
    config, so a stale depth can never fight the profile. The analyst and round
    environment variables still reach the graph as per-field overrides
    (Implements: REQ-TA-FR-001).

    ``token_budget`` (REQ-TA-FR-002): an explicit ``--token-budget`` wins over the
    environment; when neither is given the value is ``None`` (enforcement off),
    so a run without a budget reproduces the baseline.
    """
    config = DEFAULT_CONFIG.copy()
    if token_budget is not None:
        config["token_budget"] = token_budget
    if profile is None:
        # Research depth sets both round counts, but an explicit env override
        # (TRADINGAGENTS_MAX_DEBATE_ROUNDS / _MAX_RISK_ROUNDS) wins over the
        # interactive selection — leave the env-applied value in place (#977).
        rounds = (("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "max_debate_rounds"),
                  ("TRADINGAGENTS_MAX_RISK_ROUNDS", "max_risk_discuss_rounds"))
        depth_was_asked = not depth_from_env()
        for env_var, key in rounds:
            if not os.environ.get(env_var):
                config[key] = selections["research_depth"]
            elif depth_was_asked:
                # The depth question appeared (it is skipped only when both are
                # set), so say which half of the answer the environment overrode.
                console.print(
                    f"[green]✓ {key} from environment:[/green] {config[key]} "
                    f"(set by {env_var}, so the research depth you chose does not apply to it)"
                )
    config["quick_think_llm"] = selections["quick_think_llm"]
    config["deep_think_llm"] = selections["deep_think_llm"]
    config["backend_url"] = selections["backend_url"]
    config["llm_provider"] = selections["llm_provider"].lower()
    # Provider-specific thinking configuration. Only the main provider's is
    # asked; a tier on another provider keeps its configured value (#1440).
    for key in ("google_thinking_level", "openai_reasoning_effort", "anthropic_effort"):
        if selections.get(key) is not None:
            config[key] = selections[key]
    config["output_language"] = selections.get("output_language", "English")
    # --checkpoint/--no-checkpoint overrides only when explicitly given; omitting
    # the flag preserves TRADINGAGENTS_CHECKPOINT_ENABLED / the default (#976).
    if checkpoint is not None:
        config["checkpoint_enabled"] = checkpoint
    return config


def _selections_from_replay(record_path: str, flags: dict) -> dict:
    """Build run selections from a replay record plus a supplied ticker/date.

    Implements REQ-TA-FR-008. Replays configuration only: the record supplies the
    allowlisted settings, while the ticker and analysis date are always supplied
    by this invocation (never replayed). Output paths, credentials and
    observational metadata are never read. Validation happens here, before any
    tracker or provider/client is constructed.
    """
    from cli.models import AnalystType
    from cli.prompts import detect_asset_type, parse_analysis_date, parse_ticker
    from tradingagents.settings_replay import load_replayable_settings

    if flags.get("ticker") is None or flags.get("date") is None:
        raise ValueError("--from-settings also needs --ticker and --date (they are not replayed)")

    try:
        replayed = load_replayable_settings(record_path)
    except ValueError as exc:  # ReplayError is a ValueError
        raise ValueError(str(exc)) from None

    ticker = parse_ticker(flags["ticker"])
    analysis_date = parse_analysis_date(flags["date"])
    asset_type = detect_asset_type(ticker)

    return {
        "ticker": ticker,
        "asset_type": asset_type.value,
        "analysis_date": analysis_date,
        "analysts": [AnalystType(name) for name in replayed.analysts],
        "research_depth": "Medium",
        "llm_provider": replayed.llm_provider,
        "backend_url": None,
        "quick_think_llm": replayed.quick_think_llm,
        "deep_think_llm": replayed.deep_think_llm,
        "google_thinking_level": replayed.google_thinking_level,
        "openai_reasoning_effort": replayed.openai_reasoning_effort,
        "anthropic_effort": replayed.anthropic_effort,
        "output_language": replayed.output_language,
        "_replayed": replayed,
    }


def run_analysis(checkpoint: bool | None = None, portfolio=None, flags=None, profile: str | None = None,
                 token_budget: int | None = None):
    flags = dict(flags or {})
    if flags.get("from_settings"):
        # REQ-TA-FR-008: replay a prior run's allowlisted settings. Ticker and
        # date are supplied by this invocation; the record supplies the rest.
        # Validation finishes here, before any tracker or provider/client is
        # constructed (fail-closed, before provider execution).
        try:
            selections = _selections_from_replay(flags["from_settings"], flags)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from None
        replayed = selections.pop("_replayed")
        profile_name = None  # do not re-apply the recorded profile mapping
        config = DEFAULT_CONFIG.copy()
        config["llm_provider"] = replayed.llm_provider
        config["deep_think_llm"] = replayed.deep_think_llm
        config["quick_think_llm"] = replayed.quick_think_llm
        if replayed.deep_think_provider:
            config["deep_think_provider"] = replayed.deep_think_provider
        if replayed.quick_think_provider:
            config["quick_think_provider"] = replayed.quick_think_provider
        config["temperature"] = replayed.temperature
        for key in ("google_thinking_level", "openai_reasoning_effort", "anthropic_effort"):
            if getattr(replayed, key) is not None:
                config[key] = getattr(replayed, key)
        config["output_language"] = replayed.output_language
        config["data_vendors"] = dict(replayed.data_vendors)
        config["tool_vendors"] = dict(replayed.tool_vendors)
        if checkpoint is not None:
            config["checkpoint_enabled"] = checkpoint
        # REQ-TA-FR-008 / REQ-TA-FR-002: token_budget is an execution-time safety
        # control, NOT replayed. It comes only from this invocation's FR-002
        # argument, never from the prior record's run_metadata.budget.
        if token_budget is not None:
            config["token_budget"] = token_budget
        replay_overrides = {
            "analysts": list(replayed.analysts),
            "max_debate_rounds": replayed.max_debate_rounds,
            "max_risk_discuss_rounds": replayed.max_risk_discuss_rounds,
            "max_tool_rounds": replayed.max_tool_rounds,
        }
    else:
        # A profile is recognised and validated first — before the unattended-gap
        # check, the interactive questions and any model client — so an unknown
        # profile fails fast naming the legal values (Implements: REQ-TA-FR-001).
        flags["profile"] = profile
        try:
            profile_name = requested_profile(flags)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from None

        # With no terminal nothing can answer a prompt: name every question still
        # open before any model is called, rather than stopping at the first one.
        if not (sys.stdin and sys.stdin.isatty()):
            gaps = unattended_gaps(flags)
            if gaps:
                console.print("[red]No terminal to answer the setup questions. Set:[/red]")
                for gap in gaps:
                    console.print(f"  {gap}")
                raise typer.Exit(code=1)

        selections = get_user_selections(flags)

        if token_budget is not None:
            config = _build_run_config(selections, checkpoint, profile=profile_name, token_budget=token_budget)
        else:
            config = _build_run_config(selections, checkpoint, profile=profile_name)
        replay_overrides = None

    # One accounting source for the whole run (REQ-TA-FR-002; ADR-004): the CLI
    # builds the tracker from the resolved token_budget and shares it with the
    # graph's observation scope, so the CLI and the graph read one ledger. The
    # replay path sets config["token_budget"] above and flows through this same
    # line, so there is exactly one tracker and no duplicate accounting.
    stats_handler = StatsCallbackHandler(RunBudgetTracker(config.get("token_budget")))

    # Normalize analyst selection to predefined order (selection is a 'set', order is fixed)
    selected_set = {analyst.value for analyst in selections["analysts"]}
    selected_analyst_keys = [a for a in ANALYST_ORDER if a in selected_set]

    # One resolved config feeds the graph, the execution plan and the display.
    # The menu/profile selection is already filtered for the asset type (crypto
    # drops fundamentals); it is the base analyst set, so it shapes the resolved
    # analysts but is not recorded as an override. Only an explicit --analysts is
    # a user override (Implements: REQ-TA-FR-001). In replay mode the recorded
    # resolved analysts/rounds are the explicit overrides (REQ-TA-FR-008).
    if replay_overrides is not None:
        explicit_overrides = replay_overrides
        base_analysts = None
    else:
        explicit_overrides = {}
        if flags.get("analysts") is not None:
            explicit_overrides["analysts"] = selected_analyst_keys
        base_analysts = (None if flags.get("analysts") is not None
                         else selected_analyst_keys)
    try:
        graph = TradingAgentsGraph(
            config=config,
            debug=True,
            callbacks=[stats_handler],
            profile=profile_name,
            explicit_overrides=explicit_overrides or None,
            base_analysts=base_analysts,
        )
    except MissingApiKeyError as exc:
        # REQ-TA-QR-001 (ADR-005 D-B): a missing key at construction is a
        # controlled failure. Write a standalone run record and stop with a safe
        # diagnostic; the exception never escapes the CLI.
        _record_startup_failure(config, selections, exc)
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    # The analysts the graph actually runs with, from the same resolved config.
    effective_analysts = [a for a in ANALYST_ORDER if a in set(graph.selected_analysts)]
    analyst_execution_plan = build_analyst_execution_plan(effective_analysts)
    analyst_wall_time_tracker = AnalystWallTimeTracker(analyst_execution_plan)

    message_buffer.init_for_analysis(effective_analysts)

    # Track start time for elapsed display
    start_time = time.time()

    results_dir = _run_directory(config, selections["ticker"], selections["analysis_date"])
    results_dir.mkdir(parents=True, exist_ok=True)
    report_dir = results_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    log_file = results_dir / "message_tool.log"
    log_file.touch(exist_ok=True)

    def save_message_decorator(obj, func_name):
        func = getattr(obj, func_name)

        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, message_type, content = obj.messages[-1]
            content = content.replace("\n", " ")  # Replace newlines with spaces
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [{message_type}] {content}\n")
        return wrapper

    def save_tool_call_decorator(obj, func_name):
        func = getattr(obj, func_name)

        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, tool_name, args = obj.tool_calls[-1]
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [Tool Call] {tool_name}({args_str})\n")
        return wrapper

    def save_report_section_decorator(obj, func_name):
        func = getattr(obj, func_name)

        @wraps(func)
        def wrapper(section_name, content):
            func(section_name, content)
            if section_name in obj.report_sections and obj.report_sections[section_name] is not None:
                content = obj.report_sections[section_name]
                if content:
                    file_name = f"{section_name}.md"
                    text = "\n".join(str(item) for item in content) if isinstance(content, list) else content
                    with open(report_dir / file_name, "w", encoding="utf-8") as f:
                        f.write(text)
        return wrapper

    message_buffer.add_message = save_message_decorator(message_buffer, "add_message")
    message_buffer.add_tool_call = save_tool_call_decorator(message_buffer, "add_tool_call")
    message_buffer.update_report_section = save_report_section_decorator(message_buffer, "update_report_section")

    layout = create_layout()

    # The alternate screen keeps a layout taller than the window from redrawing
    # by scrolling; the final report prints after this block, on the normal screen.
    with Live(layout, refresh_per_second=4, screen=True):
        # Initial display
        update_display(layout, stats_handler=stats_handler, start_time=start_time)

        message_buffer.add_message("System", f"Selected ticker: {selections['ticker']}")
        if selections["asset_type"] != "stock":
            message_buffer.add_message("System", f"Detected asset type: {selections['asset_type']}")
        message_buffer.add_message(
            "System", f"Analysis date: {selections['analysis_date']}"
        )
        message_buffer.add_message(
            "System",
            f"Selected analysts: {', '.join(analyst.value for analyst in selections['analysts'])}",
        )
        # The effective configuration the run will use, from the same resolved
        # settings the graph and the report use (Implements: REQ-TA-FR-001).
        settings = graph.run_settings()
        profile_note = ""
        if settings.get("profile_requested"):
            profile_note = f" (profile {settings['profile_requested']})"
        message_buffer.add_message(
            "System",
            f"Effective configuration{profile_note}: "
            f"analysts {', '.join(settings['analysts'])}; "
            f"debate {settings['max_debate_rounds']}, "
            f"risk {settings['max_risk_discuss_rounds']}, "
            f"tool rounds per analyst {settings['max_tool_rounds']}",
        )
        update_display(layout, stats_handler=stats_handler, start_time=start_time)

        # The analysts start together.
        for spec in analyst_execution_plan.specs:
            message_buffer.update_agent_status(spec.agent_node, "in_progress")
            analyst_wall_time_tracker.mark_started(spec.key)
        update_display(layout, stats_handler=stats_handler, start_time=start_time)

        spinner_text = (
            f"Analyzing {selections['ticker']} on {selections['analysis_date']}..."
        )
        update_display(layout, spinner_text, stats_handler=stats_handler, start_time=start_time)

        # The same initial state propagate() builds, with the resolved
        # instrument identity; the graph's Memory Log step settles past
        # decisions and loads their lessons alongside the analysts.
        init_agent_state = graph.create_run_state(
            selections["ticker"], selections["analysis_date"], selections["asset_type"], portfolio
        )
        # Pass callbacks to graph config for tool execution tracking
        # (LLM tracking is handled separately via LLM constructor)
        args = graph.propagator.get_graph_args(callbacks=[stats_handler])

        # Recompile with a checkpointer and inject the thread_id so --checkpoint
        # actually saves and resumes on the CLI path (#1249); a no-op when
        # checkpointing is disabled. Torn down in the finally below.
        checkpoint_tid = graph.begin_checkpoint(
            selections["ticker"], selections["analysis_date"], selections["asset_type"], portfolio
        )
        if checkpoint_tid is not None:
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = checkpoint_tid
            _announce_checkpoint_state(graph, selections["ticker"], selections["analysis_date"])

        # Share the CLI's tracker with the graph so both read one ledger
        # (REQ-TA-FR-002; ADR-004). Held for the whole streamed run via the
        # context's enter/exit so the per-message loop keeps its indentation.
        graph._run_budget_tracker = stats_handler.tracker
        _budget_scope = RunBudgetContext(stats_handler.tracker).activate()
        _budget_scope.__enter__()

        # Bind a fresh data-availability holder for this run (REQ-TA-QR-001;
        # ADR-005). LangGraph step contexts copy from here, so the tool nodes
        # mutate this holder and _terminal_failure() below reads it.
        from tradingagents import data_signal

        data_signal.bind()

        # Stream the analysis. On resume, feed None so LangGraph continues the
        # interrupted run instead of re-appending the initial state (#1249); the
        # try/finally tears the checkpointer down even if the stream raises.
        trace = []
        try:
            for messages, chunk in graph.stream_run(graph.checkpoint_input(init_agent_state), **args):
                for message in messages:
                    msg_id = getattr(message, "id", None)
                    if msg_id is not None:
                        if msg_id in message_buffer._processed_message_ids:
                            continue
                        message_buffer._processed_message_ids.add(msg_id)

                    msg_type, content = classify_message_type(message)
                    if content and content.strip():
                        message_buffer.add_message(msg_type, content)

                    if hasattr(message, "tool_calls") and message.tool_calls:
                        for tool_call in message.tool_calls:
                            if isinstance(tool_call, dict):
                                message_buffer.add_tool_call(tool_call["name"], tool_call["args"])
                            else:
                                message_buffer.add_tool_call(tool_call.name, tool_call.args)

                if chunk is None:   # a step inside an analyst's graph: messages only
                    update_display(layout, stats_handler=stats_handler, start_time=start_time)
                    continue

                update_analyst_statuses(
                    message_buffer,
                    chunk,
                    wall_time_tracker=analyst_wall_time_tracker,
                )

                # Research Team - Handle Investment Debate State
                if chunk.get("investment_debate_state"):
                    debate_state = chunk["investment_debate_state"]
                    bull_hist = debate_state.get("bull_history", "").strip()
                    bear_hist = debate_state.get("bear_history", "").strip()
                    judge = (chunk.get("investment_plan") or "").strip()

                    # Only update status when there's actual content
                    if bull_hist or bear_hist:
                        update_research_team_status("in_progress")
                    if bull_hist:
                        message_buffer.update_report_section(
                            "investment_plan", f"### Bull Researcher Analysis\n{bull_hist}"
                        )
                    if bear_hist:
                        message_buffer.update_report_section(
                            "investment_plan", f"### Bear Researcher Analysis\n{bear_hist}"
                        )
                    if judge:
                        message_buffer.update_report_section(
                            "investment_plan", f"### Research Manager Decision\n{judge}"
                        )
                        update_research_team_status("completed")
                        message_buffer.update_agent_status("Trader", "in_progress")

                # Trading Team
                if chunk.get("trader_investment_plan"):
                    message_buffer.update_report_section(
                        "trader_investment_plan", chunk["trader_investment_plan"]
                    )
                    if message_buffer.agent_status.get("Trader") != "completed":
                        message_buffer.update_agent_status("Trader", "completed")
                        message_buffer.update_agent_status("Aggressive Analyst", "in_progress")

                # Risk Management Team - Handle Risk Debate State
                if chunk.get("risk_debate_state"):
                    risk_state = chunk["risk_debate_state"]
                    agg_hist = risk_state.get("aggressive_history", "").strip()
                    con_hist = risk_state.get("conservative_history", "").strip()
                    neu_hist = risk_state.get("neutral_history", "").strip()
                    judge = (chunk.get("final_trade_decision") or "").strip()

                    if agg_hist:
                        if message_buffer.agent_status.get("Aggressive Analyst") != "completed":
                            message_buffer.update_agent_status("Aggressive Analyst", "in_progress")
                        message_buffer.update_report_section(
                            "final_trade_decision", f"### Aggressive Analyst Analysis\n{agg_hist}"
                        )
                    if con_hist:
                        if message_buffer.agent_status.get("Conservative Analyst") != "completed":
                            message_buffer.update_agent_status("Conservative Analyst", "in_progress")
                        message_buffer.update_report_section(
                            "final_trade_decision", f"### Conservative Analyst Analysis\n{con_hist}"
                        )
                    if neu_hist:
                        if message_buffer.agent_status.get("Neutral Analyst") != "completed":
                            message_buffer.update_agent_status("Neutral Analyst", "in_progress")
                        message_buffer.update_report_section(
                            "final_trade_decision", f"### Neutral Analyst Analysis\n{neu_hist}"
                        )
                    if judge and message_buffer.agent_status.get("Portfolio Manager") != "completed":
                        message_buffer.update_agent_status("Portfolio Manager", "in_progress")
                        # The live panel shows the same REVIEW-aware text as the
                        # saved report: a top-level REVIEW names its reasons here
                        # rather than the model's superseded call; an accepted
                        # decision renders unchanged (ADR-003 §8; REQ-TA-FR-004).
                        message_buffer.update_report_section(
                            "final_trade_decision",
                            f"### Portfolio Manager Decision\n{decision_display_text(chunk)}"
                        )
                        message_buffer.update_agent_status("Aggressive Analyst", "completed")
                        message_buffer.update_agent_status("Conservative Analyst", "completed")
                        message_buffer.update_agent_status("Neutral Analyst", "completed")
                        message_buffer.update_agent_status("Portfolio Manager", "completed")

                update_display(layout, stats_handler=stats_handler, start_time=start_time)

                trace.append(chunk)

            # Streamed chunks are per-node deltas, not full state. Merge them
            # so every report field populated across the run is present.
            final_state = {}
            for chunk in trace:
                final_state.update(chunk)

            # REQ-TA-QR-001 (ADR-005): apply the same terminal controlled-failure
            # rules the graph path uses (core data unavailable -> REVIEW +
            # STOCK_DATA_UNAVAILABLE; budget-only REVIEW -> TOKEN_BUDGET_EXHAUSTED).
            terminal_failure = _terminal_failure(final_state, stats_handler.tracker)

            # Record this run's observational metadata BEFORE the decision is
            # logged, so the persisted record carries the final observations
            # (Implements: REQ-TA-QR-004). Token totals and call counts come from
            # the same stats handler the display uses (the single usage source).
            # A graph-like object without the setter (a test double) records
            # nothing rather than failing the run.
            if hasattr(graph, "set_run_observations"):
                graph.set_run_observations(
                    usage=build_usage_summary(stats_handler.get_stats()),
                    status=record.STATUS_COMPLETED,
                    started_at=_iso_timestamp(start_time),
                    completed_at=_iso_timestamp(time.time()),
                    failure=terminal_failure,
                )

            # Clean run: log the decision (which persists the record written
            # above), then drop this run's checkpoint so a later run starts fresh.
            graph.record_decision(selections["ticker"], selections["analysis_date"], final_state)
            graph.clear_checkpoint_on_success(
                selections["ticker"], selections["analysis_date"], selections["asset_type"], portfolio
            )
        except BaseException as exc:
            # REQ-TA-QR-001 (ADR-005; D-CLI): a *classified* controlled failure
            # (provider timeout/transport, invalid agent JSON) is handled here —
            # record it, print a safe diagnostic, and exit without a traceback.
            # An *unclassified* exception keeps the existing behaviour: record
            # status=failed and re-raise so a genuine bug stays visible.
            from tradingagents.failure import classify_exception

            code = classify_exception(exc)
            if hasattr(graph, "set_run_observations"):
                if code is not None:
                    from tradingagents import failure as failure_mod

                    failure = failure_mod.build_failure(
                        code, phase="run", exception_type=type(exc).__name__)
                    graph.set_run_observations(
                        usage=build_usage_summary(stats_handler.get_stats()),
                        status=record.STATUS_FAILED,
                        started_at=_iso_timestamp(start_time),
                        completed_at=_iso_timestamp(time.time()),
                        failure=failure,
                    )
                    with suppress(OSError):
                        graph.write_run_record(selections["ticker"], selections["analysis_date"])
                    console.print(f"[red]{failure['diagnostic']}[/red]")
                    raise typer.Exit(code=1) from None
                # Unclassified: record status=failed, then re-raise as before.
                graph.set_run_observations(
                    usage=build_usage_summary(stats_handler.get_stats()),
                    status=record.STATUS_FAILED,
                    started_at=_iso_timestamp(start_time),
                    completed_at=_iso_timestamp(time.time()),
                )
                with suppress(OSError):  # never mask the original failure with a write error
                    graph.write_run_record(selections["ticker"], selections["analysis_date"])
            raise
        finally:
            # Leave the run's budget context, then restore the plain
            # uncheckpointed graph, even on failure.
            with suppress(Exception):
                _budget_scope.__exit__(None, None, None)
            graph.end_checkpoint()

        for agent in message_buffer.agent_status:
            message_buffer.update_agent_status(agent, "completed")

        message_buffer.add_message(
            "System", f"Completed analysis for {selections['analysis_date']}"
        )
        message_buffer.add_message("System", analyst_wall_time_tracker.format_summary())

        for section in message_buffer.report_sections:
            if section in final_state:
                # The final refresh is the same REVIEW-aware view as the report:
                # a REVIEW section shows its summary, not the model's superseded
                # call (ADR-003 §8; REQ-TA-FR-004).
                content = (decision_display_text(final_state)
                           if section == "final_trade_decision"
                           else final_state[section])
                message_buffer.update_report_section(section, content)

        update_display(layout, stats_handler=stats_handler, start_time=start_time)

    # Post-analysis prompts (outside Live context for clean interaction)
    console.print("\n[bold cyan]Analysis Complete![/bold cyan]\n")

    # A decision nobody can read, or one whose prices do not validate, is not a
    # position. Say so here rather than leaving the run to look like a normal
    # result, and name the reason when the final-decision gate recorded one
    # (Implements: REQ-TA-FR-004).
    if is_review(run_rating(final_state)):
        reasons = final_state.get("decision_review_reasons") or []
        detail = f" ({', '.join(reasons)})" if reasons else ""
        console.print(
            f"[yellow]The final decision is recorded for review rather than as a "
            f"position{detail}: no tradeable call is presented. Re-run, or read the "
            "decision text below and judge it yourself.[/yellow]\n"
        )
    console.print(f"[dim]{analyst_wall_time_tracker.format_summary()}[/dim]")

    _offer_reports(final_state, graph, selections["ticker"],
                   save=flags.get("save"), show=flags.get("show"), html=flags.get("html"))


def _yes(question: str) -> bool:
    return typer.prompt(question, default="Y").strip().upper() in ("Y", "YES", "")


def _graphical_browser():
    """A browser that opens a page in its own window on this machine, or None.

    Over SSH the page sits on the remote machine, and a terminal browser (lynx,
    w3m, elinks) would take over the terminal, so neither is offered.
    """
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return None
    try:
        browser = webbrowser.get()
    except webbrowser.Error:
        return None
    if type(browser) is webbrowser.GenericBrowser or isinstance(browser, webbrowser.Elinks):
        return None
    return browser


def _open_page(page: Path) -> None:
    """Offer to open the saved page in a browser window, and say where it is if opening fails."""
    browser = _graphical_browser()
    if browser is None or not _yes("Open it in your browser?"):
        return
    try:
        opened = browser.open(page.as_uri())
    except (webbrowser.Error, OSError):
        opened = False
    if not opened:
        console.print(f"  [dim]Could not open a browser; the page is at:[/dim] {page}")


def _offer_reports(final_state, graph, ticker, save=None, show=None, html=None):
    """Save the report tree and show it; ``save``/``show``/``html`` answer the questions when given.

    A saved report includes the HTML page unless ``html`` is False. Someone
    answering the save question at the prompt is also asked about the page and
    offered to open it; a run whose flags answer the save question asks neither.
    """
    asked = save is None
    if asked:
        save = typer.prompt("Save report?", default="Y").strip().upper() in ("Y", "YES", "")
    if save:
        # Under results_dir, not the working directory: in Docker the working
        # directory is inside the container and the report goes with it, while
        # results_dir is the mounted volume the rest of the run already writes to.
        save_path = graph.default_report_path(ticker)
        if asked:   # someone at the prompt may pick another folder
            save_path = Path(typer.prompt(
                "Save path (press Enter for default)", default=str(save_path)
            ).strip())
        if html is None:
            html = _yes("Also save it as an HTML page?") if asked else True
        saved = False
        try:
            report_file = graph.save_reports(final_state, ticker, save_path, html=html)
            saved = True
            console.print(f"\n[green]✓ Report saved to:[/green] {save_path.resolve()}")
            console.print(f"  [dim]Complete report:[/dim] {report_file.name}")
        except Exception as e:
            console.print(f"[red]Error saving report: {e}[/red]")
        if saved and html:
            page = (save_path / "complete_report.html").resolve()
            console.print(f"  [dim]HTML report:[/dim] {page.name}")
            if asked:
                _open_page(page)

    if show is None:
        show = typer.prompt("\nDisplay full report on screen?", default="Y").strip().upper() in ("Y", "YES", "")
    if show:
        display_complete_report(final_state)
