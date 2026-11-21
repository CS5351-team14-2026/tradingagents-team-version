import sys
from enum import StrEnum
from typing import Annotated

import typer
from rich.markup import escape

from cli.display import console
from cli.models import AnalystType, AssetType
from cli.prompts import filter_analysts_for_asset_type, parse_analysts
from cli.run import run_analysis
from tradingagents.backtest import iter_grid, run_backtest, summarize
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.openai_client import SIGNED_IN_PROVIDERS
from tradingagents.portfolio import load_portfolio
from tradingagents.redaction import redact_text

# prompt_toolkit's win32 output module is importable only on Windows (it asserts
# the platform at import time), so gate on the platform rather than catching the
# failure — that way a genuinely broken prompt_toolkit on Windows still surfaces
# instead of silently disabling the handler below. Off Windows this stays an
# empty tuple, which `except` accepts and never matches (#1138).
if sys.platform == "win32":  # pragma: no cover - platform dependent
    from prompt_toolkit.output.win32 import NoConsoleScreenBufferError

    _NO_CONSOLE_ERRORS: tuple[type[BaseException], ...] = (NoConsoleScreenBufferError,)
else:
    _NO_CONSOLE_ERRORS = ()

app = typer.Typer(
    name="TradingAgents",
    help="TradingAgents CLI: Multi-Agents LLM Financial Trading Framework",
    add_completion=True,  # Enable shell completion
)


@app.callback(invoke_without_command=True)
def analyze(
    ctx: typer.Context,
    checkpoint: bool | None = typer.Option(
        None,
        "--checkpoint/--no-checkpoint",
        help="Enable/disable checkpoint-resume (save state after each node so a "
        "crashed run can resume). Omit to honor TRADINGAGENTS_CHECKPOINT_ENABLED.",
    ),
    clear_checkpoints: bool = typer.Option(
        False,
        "--clear-checkpoints",
        help="Delete all saved checkpoints before running (force fresh start).",
    ),
    portfolio: str = typer.Option(
        None,
        "--portfolio",
        help="JSON file with current holdings and cash, so the trader, risk and "
        "portfolio agents size against your actual position.",
    ),
    ticker: str = typer.Option(None, "--ticker", help="Ticker to analyze, e.g. NVDA or 0700.HK; skips the prompt"),
    date: str = typer.Option(None, "--date", help="Analysis date, YYYY-MM-DD; skips the prompt"),
    analysts: str = typer.Option(
        None, "--analysts", help="Comma-separated analysts, e.g. market,news; skips the prompt"
    ),
    profile: str = typer.Option(
        None, "--profile",
        help="Analysis profile: quick, standard or deep; sets the analysts and round "
        "budgets (overrides TRADINGAGENTS_PROFILE). Explicit --analysts and "
        "TRADINGAGENTS_MAX_* still override individual fields.",
    ),
    token_budget: int | None = typer.Option(
        None, "--token-budget", min=0,
        help="Maximum tokens for one run (REQ-TA-FR-002): once recorded usage reaches "
        "it, no further optional LLM calls start. Omit to honor "
        "TRADINGAGENTS_TOKEN_BUDGET; both unset disables enforcement.",
    ),
    save: bool | None = typer.Option(
        None, "--save/--no-save", help="Save the report under results_dir without asking"
    ),
    show: bool | None = typer.Option(
        None, "--show/--no-show", help="Show the full report at the end without asking"
    ),
    html: bool | None = typer.Option(
        None, "--html/--no-html",
        help="Save the report as one HTML page too, complete_report.html, without asking (default: yes)",
    ),
    from_settings: str = typer.Option(
        None, "--from-settings",
        help="Re-run using the allowlisted settings recorded for a prior run "
        "(a run_record_*.json or a full_states_log_*.json). Needs --ticker and "
        "--date; cannot be combined with profile/analyst/model/provider/round/"
        "temperature/effort/language/vendor overrides (REQ-TA-FR-008). "
        "--token-budget (REQ-TA-FR-002) may be combined: it is an execution-time "
        "safety control, not replayable configuration.",
    ),
):
    """Run an analysis. This is what a bare `tradingagents` does.

    Flags answer their questions; with provider, models, depth and language also
    set through TRADINGAGENTS_* variables, the run asks nothing.
    """
    if ctx.invoked_subcommand is not None:
        return
    if clear_checkpoints:
        from tradingagents.graph.checkpointer import clear_all_checkpoints
        n = clear_all_checkpoints(DEFAULT_CONFIG["data_cache_dir"])
        console.print(f"[yellow]Cleared {n} checkpoint(s).[/yellow]")
    portfolio_context = None
    if portfolio:
        try:
            portfolio_context = load_portfolio(portfolio)
        except ValueError as exc:
            console.print(f"[red]{redact_text(str(exc))}[/red]")
            raise typer.Exit(code=1) from None

    try:
        if from_settings:
            # REQ-TA-FR-008: the record is the single source of configuration, so
            # any explicit configuration-override flag is a conflict and is
            # rejected. --token-budget (REQ-TA-FR-002) is an execution-time safety
            # control, not replayed configuration, so it may be combined.
            conflicts = [
                name for name, value in (
                    ("--profile", profile),
                    ("--analysts", analysts),
                ) if value is not None
            ]
            if conflicts:
                console.print(
                    "[red]--from-settings cannot be combined with "
                    + ", ".join(conflicts)
                    + "; the run record supplies the configuration.[/red]"
                )
                raise typer.Exit(code=1)
        flags = {"ticker": ticker, "date": date, "analysts": analysts, "save": save, "show": show, "html": html}
        # Only carry the replay key when set, so a normal run's flags dict is
        # byte-for-byte what it was before FR-008 (REQ-TA-FR-008).
        if from_settings:
            flags["from_settings"] = from_settings
        run_analysis(checkpoint=checkpoint, portfolio=portfolio_context, flags=flags, profile=profile,
                     token_budget=token_budget)
    except _NO_CONSOLE_ERRORS:
        # A terminal with no console buffer cannot host the interactive prompts.
        # Emit one actionable line on stderr instead of a prompt_toolkit
        # traceback; plain text, since rich may not render here either (#1138).
        typer.echo(
            "Error: no Windows console available. The interactive CLI needs a real "
            "console buffer — run it from Windows Terminal, PowerShell, or cmd.exe "
            "rather than a piped or embedded terminal.",
            err=True,
        )
        raise typer.Exit(code=1) from None


@app.command()
def backtest(
    tickers: str = typer.Argument(..., help="Comma-separated tickers, e.g. NVDA,AAPL"),
    start: str = typer.Option(..., "--start", help="First analysis date, YYYY-MM-DD"),
    end: str = typer.Option(..., "--end", help="Last analysis date, YYYY-MM-DD"),
    every: int = typer.Option(7, "--every", help="Days between analysis dates"),
    analysts: str = typer.Option(
        None, "--analysts", help="Comma-separated analysts to run: market, sentiment, news, fundamentals; omit for all the asset type allows"
    ),
    asset_type: str = typer.Option("stock", "--asset-type", help="stock or crypto"),
    portfolio: str = typer.Option(
        None, "--portfolio", help="JSON file with holdings and cash, held constant across the grid"
    ),
    run_id: str = typer.Option(
        None, "--run-id", help="Continue an earlier sweep: its cells are skipped and its log reused"
    ),
):
    """Score past decisions over a grid of tickers and dates."""

    try:
        dates = iter_grid(start, end, every)
        book = load_portfolio(portfolio) if portfolio else None
        kind = AssetType(asset_type.strip().lower())
        # The analysts are named and checked as for an analysis; without a
        # choice, every analyst the asset type allows runs.
        chosen = (parse_analysts(analysts, kind) if analysts
                  else filter_analysts_for_asset_type(list(AnalystType), kind))
    except ValueError as exc:
        console.print(f"[red]{redact_text(str(exc))}[/red]")
        raise typer.Exit(code=1) from None

    names = [t.strip() for t in tickers.split(",") if t.strip()]
    if not names:
        console.print("[red]No ticker to analyze; pass them comma-separated, e.g. NVDA,AAPL[/red]")
        raise typer.Exit(code=1)

    def show_progress(done, total, ticker, date):
        console.print(f"[dim][{done}/{total}] {ticker} {date}[/dim]")

    kwargs = {"asset_type": kind.value, "portfolio": book, "run_id": run_id, "progress": show_progress,
              "selected_analysts": [a.value for a in chosen]}

    try:
        result = run_backtest(names, dates, DEFAULT_CONFIG, **kwargs)
    except Exception as exc:  # a missing key or an unknown analyst is a setup error
        console.print(f"[red]{redact_text(str(exc))}[/red]")
        raise typer.Exit(code=1) from None
    console.print(summarize(result).render())
    console.print(f"\nRan {result.cells_run} cells, skipped {result.skipped}. Log: {result.log_path}")
    console.print(f"Continue or settle this sweep: --run-id {result.run_id}")
    for ticker, date, reason in result.failures:
        console.print(f"[yellow]failed:[/yellow] {ticker} {date}: {reason}")
    for ticker, reason in result.settlement_failures:
        console.print(f"[yellow]unsettled:[/yellow] {ticker}: {reason}")


@app.command()
def compare(
    cases: str = typer.Option(..., help="JSON list of ticker/analysis_date objects"),
    baseline: str = typer.Option(..., help="JSON baseline configuration overrides"),
    enhanced: str = typer.Option(..., help="JSON enhanced configuration overrides"),
    output: str = typer.Option(..., help="New output directory (must not exist)"),
    repetitions: int = typer.Option(3, min=1),
    live: bool = typer.Option(False, "--live", help="Confirm real provider calls and costs"),
    smoke: bool = typer.Option(False, "--smoke", help="One case, one pair; diagnostic only"),
    resume: bool = typer.Option(False, "--resume", help="Resume only an identical recorded experiment"),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="With --resume, retry failed runs; retain every attempt"),
    input_price: float | None = typer.Option(None, min=0, help="USD per million input tokens"),
    output_price: float | None = typer.Option(None, min=0, help="USD per million output tokens"),
):
    """REQ-TA-FR-007 / PERF-001: run paired configurations and export measurements."""
    import json
    from pathlib import Path

    from tradingagents.evaluation import EvaluationCase, TokenPricing, export_comparison
    from tradingagents.evaluation_runner import prepare_configs, run_comparison

    if not live:
        typer.echo("No calls made. Pass --live to acknowledge provider calls and costs.")
        raise typer.Exit(1)
    try:
        case_data = json.loads(Path(cases).read_text(encoding="utf-8"))
        if not isinstance(case_data, list) or len(case_data) < (1 if smoke else 3):
            raise ValueError("provide at least three cases, or one with --smoke")
        if smoke and len(case_data) != 1:
            raise ValueError("smoke requires exactly one case")
        chosen = [EvaluationCase(**item) for item in case_data]
        before, after = prepare_configs(
            DEFAULT_CONFIG, json.loads(Path(baseline).read_text(encoding="utf-8")),
            json.loads(Path(enhanced).read_text(encoding="utf-8")))
        if (input_price is None) != (output_price is None):
            raise ValueError("provide both input-price and output-price or neither")
        pricing = TokenPricing(input_price, output_price) if input_price is not None else None
        destination = Path(output)
        if destination.exists() and not resume:
            raise ValueError("output directory must not already exist")
        result = run_comparison(chosen, before, after, destination, 1 if smoke else repetitions,
                                pricing=pricing, progress=lambda event: typer.echo(json.dumps(event)),
                                resume=resume, retry_failed=retry_failed)
        if resume:
            history = destination / "export-history"
            history.mkdir(exist_ok=True)
            for name in ("comparison.json", "comparison.csv"):
                existing = destination / name
                if existing.exists():
                    archived = history / f"{len(list(history.iterdir())):06d}-{name}"
                    existing.rename(archived)
        export_comparison(result, destination / "comparison.json")
        export_comparison(result, destination / "comparison.csv", "csv")
        typer.echo(json.dumps(result.summary(), indent=2))
        (destination / "experiment.json").write_text(json.dumps({
            "mode": "smoke" if smoke else "repeated_comparison",
            "planned_runs": len(chosen) * (1 if smoke else repetitions) * 2,
            "performance_acceptance": "not_assessed",
        }, indent=2) + "\n", encoding="utf-8")
        typer.echo("Saved comparison.json and comparison.csv. Performance target remains TBD.")
        if smoke:
            typer.echo("Smoke diagnostics only: one pair cannot establish a performance result.")
        if any(r.status == "failed" for r in result.runs):
            raise typer.Exit(2)
    except (ValueError, TypeError, OSError):
        typer.echo("Invalid input or export failure; check case/config schema and output location.", err=True)
        raise typer.Exit(1) from None


# The plans `login` and `logout` take: the providers signed in to, not keyed.
Plan = StrEnum("Plan", {name: name for name in SIGNED_IN_PROVIDERS})


@app.command()
def login(plan: Annotated[Plan, typer.Argument(help="The plan to sign in with")]):
    """Sign in with your ChatGPT Plus or Pro plan, for the chatgpt provider."""
    from tradingagents.llm_clients import chatgpt_auth

    try:
        # One unwrapped line, so the sign-in address can be copied whole.
        email = chatgpt_auth.sign_in(
            say=lambda line: console.print(line, soft_wrap=True, markup=False, highlight=False))
    except chatgpt_auth.ChatGPTAuthError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"[green]Signed in to ChatGPT as {escape(email)}.[/green]")


@app.command()
def logout(plan: Annotated[Plan, typer.Argument(help="The plan to sign out of")]):
    """Sign out of your ChatGPT plan: revoke this machine's access and forget it."""
    from tradingagents.llm_clients import chatgpt_auth

    outcome = chatgpt_auth.sign_out()
    if outcome == "revoked":
        console.print("Signed out of ChatGPT.")
    elif outcome == "forgotten":
        console.print("[yellow]Signed out here, but OpenAI could not be reached to revoke the sign-in; "
                      "it stays valid at OpenAI until it expires.[/yellow]")
    else:
        console.print("Not signed in to ChatGPT.")


if __name__ == "__main__":
    app()
