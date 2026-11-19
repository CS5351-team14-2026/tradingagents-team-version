import hashlib
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import tradingagents
from tradingagents import run_record as record
from tradingagents.agents.context import build_instrument_context, resolve_instrument_identity
from tradingagents.agents.rating import RATING_REVIEW, is_review, run_rating
from tradingagents.dataflows.config import run_config, run_config_context, set_config
from tradingagents.dataflows.date_window import get_current_date, is_historical
from tradingagents.dataflows.symbols import safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG, _coerce, resolve_profile
from tradingagents.llm_clients import create_tier_client, tier_provider
from tradingagents.memory import TradingMemoryLog, settlement
from tradingagents.memory.reflection import Reflector
from tradingagents.reporting import (
    audit_material_claims,
    evaluate_claim_acceptance,
    write_report_tree,
)
from tradingagents.run_budget import (
    RunBudgetContext,
    RunBudgetTracker,
)

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .propagation import Propagator
from .setup import GraphSetup

logger = logging.getLogger(__name__)


def _bind_budget_context(tracker) -> None:
    """Bind ``tracker`` as the current run's budget context inside a copied Context.

    Used by ``stream_run``: it runs in a copied ``contextvars.Context`` so each
    streamed step resolves this run's ledger rather than the caller's. This is
    the public ``bind_context`` helper from ``run_budget`` (ADR-004), not a
    private cross-module read.
    """
    from tradingagents.run_budget import bind_context

    bind_context(tracker)


def _validate_trade_date(trade_date) -> str:
    """The run date as a canonical ``YYYY-MM-DD`` string no later than today."""
    value = str(trade_date)
    try:
        canonical = datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") == value
    except ValueError:
        canonical = False
    if not canonical:
        raise ValueError(f"trade_date must be a date in YYYY-MM-DD format, got {trade_date!r}")
    if value > get_current_date():
        raise ValueError(f"trade_date cannot be in the future: {value}")
    return value


# Config keys that do not change what a run writes: where it keeps its files,
# whether it checkpoints, and how often it retries a provider. This is the
# signature of a default (no-profile) run. It also excludes ``claim_enforcement``
# — see below — which is exactly what the pre-PR#27 baseline (03e7d48) stored,
# that version's config having no such key at all (Implements: ADR-002;
# REQ-TA-FR-001).
_NOT_IN_SIGNATURE = frozenset({
    "results_dir", "data_cache_dir", "memory_log_path", "checkpoint_enabled", "llm_max_retries",
    # Settled after the graph run (ADR-001 claim acceptance), so it cannot change
    # the graph shape. Excluding it keeps a legacy config (no such key) and a
    # config carrying the reserved key on the same signature, matching the
    # pre-PR#27 baseline byte-for-byte, so an existing checkpoint still resumes
    # (Implements: ADR-002; REQ-TA-FR-001).
    "claim_enforcement",
})

# The baseline per-analyst tool-round cap. The checkpoint signature omits its own
# tools segment at this value so a run that did not change the cap keeps the
# pre-change signature (Implements: REQ-TA-FR-001).
_BASELINE_MAX_TOOL_ROUNDS = 20

# PR #27's material-claim slice added ``claim_enforcement: False`` to the default
# config but did *not* exclude it from the settings digest, so a checkpoint saved
# by integration right after that merge (fba0315) was keyed by a digest that
# includes the key with its then-default value ``False``. This build's default is
# now ``True``, so recomputing the digest from the live config would *not* match
# that stored run. To resume such a run we rebuild the fba0315 digest with the
# historical value (``_HISTORICAL_CLAIM_ENFORCEMENT = False``) folded in, but only
# when the effective run inputs otherwise match (Implements: ADR-002;
# REQ-TA-FR-001).
_POST_PR27_NOT_IN_SIGNATURE = frozenset(set(_NOT_IN_SIGNATURE) - {"claim_enforcement"})
_HISTORICAL_CLAIM_ENFORCEMENT = False


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=None,
        debug=False,
        config: dict[str, Any] = None,
        callbacks: list | None = None,
        profile: str | None = None,
        explicit_overrides: dict | None = None,
        base_analysts=None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: Analyst types the caller explicitly chose. A list
                here is a user override of the analyst set and is recorded in
                ``profile_overrides`` (REQ-TA-FR-001). ``None`` lets the profile —
                or the baseline four-analyst set when no profile is given —
                choose. ``explicit_overrides["analysts"]`` wins if both are given.
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
            profile: Analysis profile (``quick`` / ``standard`` / ``deep``); an
                unknown value is rejected before any model client is built
                (Implements: ADR-002; REQ-TA-FR-001).
            explicit_overrides: Per-field settings that override the profile for
                that field only, keyed like the profile's settings
                (``analysts``, ``max_debate_rounds``, ``max_risk_discuss_rounds``,
                ``max_tool_rounds``). A ``TRADINGAGENTS_PROFILE`` env value is
                used only when ``profile`` is not passed, so an explicit Python
                profile wins over the environment.
            base_analysts: The starting analyst set the CLI auto-selected (the
                menu's choice, or the profile mapping filtered for the asset
                type). It shapes the resolved analysts but is **not** recorded as
                an override — only inputs the user named are. Internal to the CLI
                entry point; programmatic callers use ``selected_analysts``.
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []

        # Resolve the profile before any model client is built: an unknown
        # profile must fail here, naming the legal values, rather than after a
        # provider client and its key checks have happened (#FR-001).
        resolved = self._resolve_run_profile(
            profile, selected_analysts, explicit_overrides or {}, base_analysts)
        self.profile_resolution = resolved
        # A cap below 1 breaks the "at most this many tool rounds before the
        # report" contract. The analyst graph always runs the model once, and the
        # wrap-up router only fires once a tool round has run (``rounds >= cap``):
        # with a cap of 0 or any negative value the first tool call therefore
        # exceeds the limit, and only after that call does the run reach the
        # wrap-up check — so the analyst is never stopped before it makes a tool
        # call the cap was meant to forbid. Reject it here, before any model
        # client is built, naming the offending value
        # (Implements: ADR-002; REQ-TA-FR-001; REQ-TA-INV-003).
        if resolved.max_tool_rounds < 1:
            raise ValueError(
                f"max_tool_rounds must be at least 1, got {resolved.max_tool_rounds}"
            )

        set_config(self.config)

        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        extra = {"callbacks": self.callbacks} if self.callbacks else {}
        # REQ-TA-QR-001 (ADR-005 D-B): a missing/invalid provider key raises a
        # typed MissingApiKeyError (a ValueError subclass), which the CLI turns
        # into a controlled failure record. The key value is never included.
        self.deep_thinking_llm = create_tier_client(self.config, "deep", **extra).get_llm()
        self.quick_thinking_llm = create_tier_client(self.config, "quick", **extra).get_llm()

        # A controlled failure recorded for this run (REQ-TA-QR-001; ADR-005).
        # None until a run ends in one; carried into run_settings()["run_metadata"].
        self._run_failure = None

        self.memory_log = TradingMemoryLog(self.config)

        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=resolved.max_debate_rounds,
            max_risk_discuss_rounds=resolved.max_risk_discuss_rounds,
        )
        # An analyst takes two graph steps per tool round, plus its first turn
        # and its wrap-up; a limit past the recursion limit would end the run
        # there instead.
        max_tool_rounds, max_recur_limit = resolved.max_tool_rounds, self.config["max_recur_limit"]
        if 2 * max_tool_rounds + 2 >= max_recur_limit:
            raise ValueError(
                f"max_tool_rounds={max_tool_rounds} needs max_recur_limit above {2 * max_tool_rounds + 2}"
            )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.conditional_logic,
            max_tool_rounds,
        )

        self.propagator = Propagator(
            max_recur_limit=max_recur_limit,
        )
        self.reflector = Reflector(self.quick_thinking_llm)

        # Graph-shape-affecting run choices, kept for the checkpoint signature.
        self.selected_analysts = tuple(resolved.analysts)

        # Set up the graph: keep the workflow for recompilation with a checkpointer.
        self.workflow = self.graph_setup.setup_graph(self.selected_analysts, memory_node=self._memory_step)
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None
        self._resuming = False
        self._thread_id = None
        self._resume_signature = None

    def _resolve_run_profile(self, profile, selected_analysts, explicit_overrides, base_analysts=None):
        """Resolve the run's four settings from the profile, explicit inputs and env.

        Implements: ADR-002; REQ-TA-FR-001.

        Source precedence, per field: an explicit input beats the profile beats
        the baseline default. Explicit analyst inputs are a caller-passed
        ``selected_analysts`` and ``explicit_overrides["analysts"]`` (the latter
        wins if both are given); either is recorded in ``overrides``.
        ``base_analysts`` is the set the CLI auto-selected (menu choice, or the
        profile mapping filtered for the asset type): it shapes the resolved
        analysts but is **not** recorded as an override. When a profile is
        selected, the three round-count / tool-cap environment variables are also
        explicit per-field sources. The ``profile`` argument wins over
        ``TRADINGAGENTS_PROFILE``: the env profile is honoured only when none is
        passed.

        With no profile at all the old call is preserved exactly: the four
        settings come from the caller's config (the round caps from the config the
        caller passed, the analyst set from the base/default), the environment is
        not re-read per field, and the checkpoint signature is unchanged.
        """
        explicit = dict(explicit_overrides)
        # A caller-passed analyst set is an explicit override; an explicit
        # explicit_overrides["analysts"] already present wins over it.
        if selected_analysts is not None:
            explicit.setdefault("analysts", selected_analysts)

        chosen = profile if profile is not None else (os.environ.get("TRADINGAGENTS_PROFILE") or None)

        # Env-as-field-override is part of selecting a profile: with no profile the
        # old config values stay authoritative, so a legacy caller that passes a
        # config is never surprised by the environment re-applying on top of it.
        if chosen is not None:
            env_fields = (
                ("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "max_debate_rounds"),
                ("TRADINGAGENTS_MAX_RISK_ROUNDS", "max_risk_discuss_rounds"),
                ("TRADINGAGENTS_MAX_TOOL_ROUNDS", "max_tool_rounds"),
            )
            for env_var, key in env_fields:
                raw = os.environ.get(env_var)
                if raw:
                    explicit.setdefault(key, _coerce(raw, self.config.get(key, DEFAULT_CONFIG[key])))

        # The base set applies only when no explicit analyst override was named.
        base = base_analysts if "analysts" not in explicit else None
        return resolve_profile(chosen, explicit=explicit, defaults=self.config,
                               base_analysts=base)


    def resolve_instrument_context(self, ticker: str, asset_type: str = "stock",
                                   trade_date: str | None = None) -> str:
        """Resolve ticker identity once and return the full instrument context.

        Deterministic yfinance lookup (cached, fail-open) injected into a
        context string so every agent anchors to the real company instead of
        hallucinating one from the price chart (#814). Both the propagate()
        path and the CLI call this so the resolved identity reaches the whole
        graph regardless of entry point.
        """
        identity = resolve_instrument_identity(ticker)
        return build_instrument_context(ticker, asset_type, identity, trade_date)

    def _memory_as_of(self, trade_date) -> str | None:
        """Point-in-time cutoff for past-context lessons (#1251).

        A historical/backtest run (trade date before today) filters lessons to
        those already resolved by the trade date. A current-date run returns
        None, disabling the filter so live behavior and pre-migration entries
        (which have no stored resolution date) are unaffected.
        """
        return str(trade_date) if is_historical(trade_date) else None

    def _run_signature(self, asset_type: str, portfolio=None) -> str:
        """Run inputs that must invalidate a checkpoint if changed.

        Keyed into the checkpoint thread ID so a resume under a different analyst
        selection, debate/risk depth, or asset mode starts fresh instead of
        silently continuing the previous graph (#1089). The rest of the config
        counts too (provider, models, endpoint, language, vendors, limits): a
        resume must not carry reports that other settings produced. Only where
        the run keeps its files and how it retries are left out.

        The analysts and round caps come from the resolved settings (which equal
        the config values when no profile is given). The per-analyst tool cap is
        folded in only when the resolution moved it away from the caller's config
        value, so a legacy/omitted-profile call — whatever its tool cap — keeps the
        pre-change signature byte-for-byte, while a run whose effective cap differs
        (profile or explicit override) still gets its own signature
        (Implements: ADR-002; REQ-TA-FR-001).
        """
        return self._signature_from(
            asset_type, portfolio, in_signature_exclusions=_NOT_IN_SIGNATURE)

    def _integration_run_signature(self, asset_type: str, portfolio=None) -> str:
        """The signature integration stores right after PR #27 (fba0315; ADR-002).

        PR #27 added ``claim_enforcement: False`` to the default config but kept
        it *in* the settings digest, so a run on integration was keyed by the
        digest with ``claim_enforcement`` (then ``False``) included. This build's
        default is now ``True``, so the digest recomputed from the live config
        would not match; instead the historical value is folded in explicitly.
        Resume tries this build's own (pre-PR#27) signature first — which drops
        the key — and then this one, so an interrupted run from either side of
        the merge still resumes. Only the settings digest differs: the analysts,
        round caps, asset mode, portfolio and layout markers are identical, so
        the two signatures agree exactly when the effective run inputs do — which
        is what "resume only on a real settings match" requires.
        """
        return self._signature_from(
            asset_type, portfolio, in_signature_exclusions=_POST_PR27_NOT_IN_SIGNATURE,
            claim_enforcement=_HISTORICAL_CLAIM_ENFORCEMENT)

    def _signature_from(self, asset_type: str, portfolio, *, in_signature_exclusions,
                        claim_enforcement=_HISTORICAL_CLAIM_ENFORCEMENT) -> str:
        """Build the checkpoint signature with the given config exclusions.

        ``claim_enforcement`` is only folded in when it is *not* excluded (the
        post-PR#27 integration signature); its historical value is written in
        explicitly so a current ``True`` default still matches a run stored when
        the key defaulted to ``False`` (Implements: ADR-002; REQ-TA-FR-001).
        """
        settings = {
            k: v for k, v in self.config.items()
            if k not in in_signature_exclusions and k != "claim_enforcement"
            # A no-budget run (token_budget None) must keep the pre-change
            # signature byte-for-byte, so the absent-key default is excluded;
            # an enabled budget is a real run input and stays in the digest
            # (Implements: ADR-004; REQ-TA-FR-002).
            and not (k == "token_budget" and v is None)
        }
        if "claim_enforcement" not in in_signature_exclusions:
            settings["claim_enforcement"] = claim_enforcement
        digest = hashlib.sha256(json.dumps(settings, sort_keys=True, default=str).encode()).hexdigest()[:12]
        # A fully built graph carries its profile resolution; a bare instance
        # (constructed in tests to exercise this helper alone) has none, so fall
        # back to the config values, which is the no-profile baseline.
        resolved = getattr(self, "profile_resolution", None)
        debate = resolved.max_debate_rounds if resolved else self.config["max_debate_rounds"]
        risk = resolved.max_risk_discuss_rounds if resolved else self.config["max_risk_discuss_rounds"]
        config_tools = self.config.get("max_tool_rounds", _BASELINE_MAX_TOOL_ROUNDS)
        tools = resolved.max_tool_rounds if resolved else config_tools
        parts = [
            "analysts=" + ",".join(self.selected_analysts),
            f"debate={debate}",
            f"risk={risk}",
        ]
        # Fold the effective tool cap in only when it differs from the caller's
        # config value. The pre-change signature had no tools segment, so a legacy
        # call (resolved == config) stays byte-for-byte identical for any cap;
        # when a profile or an explicit override changes the cap it gets a
        # distinct signature so a stale checkpoint is not reused.
        if tools != config_tools:
            parts.append(f"tools={tools}")
        parts += [
            f"asset={asset_type}",
            # None, an empty book and a changed book are three different runs.
            f"portfolio={portfolio.fingerprint() if portfolio is not None else 'none'}",
            # The layout itself: a checkpoint saved when analysts ran one after
            # another has pending nodes this graph no longer has, and one saved
            # before the Memory Log step would resume without the lessons.
            "analysts=parallel",
            "memory=parallel",
            f"settings={digest}",
        ]
        return "|".join(parts)

    @contextmanager
    def observation_scope(self):
        """Bind this run's usage ledger for the length of an execution (ADR-004).

        Yields a :class:`~tradingagents.run_budget.RunBudgetTracker` built from
        ``config["token_budget"]`` and activates its context, so callbacks and
        the invocation boundary attribute usage to this run. A
        ``token_budget`` of ``None`` disables enforcement and reproduces the
        baseline, while usage is still observed honestly (ADR-004 D6).

        Direct ``propagate()``/``stream_run()`` callers traverse this scope so
        the budget is enforced in the graph, not only in the CLI. A caller that
        already activated a compatible context (the CLI activating its
        ``StatsCallbackHandler`` tracker) keeps that tracker instead of
        re-binding a second ledger.
        """
        from tradingagents.run_budget import current_run_context

        active = current_run_context()
        limit = self.config.get("token_budget")
        if active is not None and active.tracker.limit == limit:
            self._run_budget_tracker = active.tracker
            yield active.tracker
            return
        tracker = RunBudgetTracker(limit)
        self._run_budget_tracker = tracker
        with RunBudgetContext(tracker).activate():
            yield tracker

    def propagate(self, company_name, trade_date, asset_type: str = "stock", portfolio=None):
        """Run the trading agents graph for a company on a specific date.

        ``asset_type`` selects between the stock pipeline (default) and the
        crypto pipeline (``"crypto"``) shipped in #567 — the CLI auto-detects
        from the ticker; programmatic callers pass it explicitly. When
        ``checkpoint_enabled`` is set in config, the graph is recompiled with
        a per-ticker SqliteSaver so a crashed run can resume from the last
        successful node on a subsequent invocation with the same ticker+date.

        The run executes inside :meth:`observation_scope`, so a configured
        ``token_budget`` is enforced for direct API callers too (ADR-004;
        REQ-TA-FR-002).

        Returns ``(final_state, signal)`` where ``signal`` is one of the 5-tier
        ratings (Buy / Overweight / Hold / Underweight / Sell) or ``"REVIEW"``
        when the decision had no parseable rating (#1170); guard with
        ``tradingagents.agents.rating.is_review`` before mapping it to the
        PortfolioRating enum.
        """
        trade_date = _validate_trade_date(trade_date)

        with self.observation_scope(), run_config(self.config), \
                self.checkpoint_scope(company_name, trade_date, asset_type, portfolio) as thread_id_value:
            result = self._run_graph(
                company_name, trade_date, asset_type=asset_type,
                checkpoint_thread_id=thread_id_value, portfolio=portfolio,
            )
            self._attach_budget_observation()
            return result

    def begin_checkpoint(self, company_name, trade_date, asset_type: str = "stock", portfolio=None) -> str | None:
        """Recompile the graph with a per-ticker checkpointer and return the
        ``thread_id`` to inject into the stream/invoke ``config`` (or ``None``
        when checkpointing is disabled).

        Pair every call with :meth:`end_checkpoint` in a ``finally``. Both
        ``propagate`` (via :meth:`checkpoint_scope`) and the CLI stream path use
        this so ``--checkpoint`` actually resumes (#1249); previously the setup
        lived only inside ``propagate`` and the CLI streamed the checkpointer-less
        graph, making the flag a no-op.
        """
        self._resuming = False
        if not self.config.get("checkpoint_enabled"):
            return None
        signature = self._run_signature(asset_type, portfolio)
        self._integration_signature = self._integration_run_signature(asset_type, portfolio)
        self._checkpointer_ctx = get_checkpointer(self.config["data_cache_dir"], company_name)
        saver = self._checkpointer_ctx.__enter__()
        self.graph = self.workflow.compile(checkpointer=saver)

        # Prefer this build's own (pre-PR#27, ``claim_enforcement`` dropped)
        # signature. If it has no checkpoint, fall back to the one a post-PR#27
        # integration run stored (its settings digest includes
        # ``claim_enforcement`` at the historical ``False``), so an interrupted
        # run from either side of the merge resumes. Both match only when the
        # effective run inputs do.
        data_dir, date = self.config["data_cache_dir"], str(trade_date)
        chosen = None
        for candidate in (signature, self._integration_signature):
            step = checkpoint_step(data_dir, company_name, date, candidate)
            if step is not None:
                chosen = (candidate, step)
                break
        self._resuming = chosen is not None
        if chosen is not None:
            self._resume_signature, step = chosen
            logger.info("Resuming from step %d for %s on %s", step, company_name, trade_date)
        else:
            self._resume_signature = signature
            logger.info("Starting fresh for %s on %s", company_name, trade_date)
        self._thread_id = thread_id(company_name, date, self._resume_signature)
        return self._thread_id

    def checkpoint_input(self, init_state):
        """The value to stream/invoke: ``None`` to resume an existing checkpoint,
        else the initial state for a fresh run.

        LangGraph resumes an interrupted thread when invoked with ``None``;
        re-passing the initial state instead appends it through the message
        reducer, duplicating messages in the resumed state (#1249).
        """
        return None if self._resuming else init_state

    def end_checkpoint(self):
        """Restore the plain uncheckpointed graph after a checkpointed run."""
        if self._checkpointer_ctx is not None:
            self._checkpointer_ctx.__exit__(None, None, None)
            self._checkpointer_ctx = None
            self.graph = self.workflow.compile()
        self._resuming = False
        self._thread_id = None
        self._resume_signature = None

    @contextmanager
    def checkpoint_scope(self, company_name, trade_date, asset_type: str = "stock", portfolio=None):
        """Context-manager form of begin/end_checkpoint for the propagate path."""
        try:
            yield self.begin_checkpoint(company_name, trade_date, asset_type, portfolio)
        finally:
            self.end_checkpoint()

    def clear_checkpoint_on_success(self, company_name, trade_date, asset_type: str = "stock", portfolio=None):
        """Drop a completed run's checkpoint so a later run starts fresh (#1249).

        Clear both thread IDs this run could have used: this build's own
        (pre-PR#27) signature and the post-PR#27 integration one. A run that
        resumed either checkpoint must not leave it behind to be re-resumed
        (ADR-002; REQ-TA-FR-001).
        """
        if not self.config.get("checkpoint_enabled"):
            return
        data_dir, date = self.config["data_cache_dir"], str(trade_date)
        for signature in {self._run_signature(asset_type, portfolio),
                          self._integration_run_signature(asset_type, portfolio)}:
            clear_checkpoint(data_dir, company_name, date, signature)

    def set_run_observations(self, *, usage=None, status: str | None = None,
                             started_at: str | None = None,
                             completed_at: str | None = None,
                             failure: dict | None = None) -> None:
        """Attach observational data for the current run (REQ-TA-QR-004).

        ``usage`` is a :class:`tradingagents.run_record.UsageSummary` (or any
        object exposing the same fields). These values are observational: they
        appear in ``run_settings()["run_metadata"]`` and are reprised in the
        flattened legacy keys, but they are never part of ``replayable_settings``
        (REQ-TA-FR-008 loads only those). A caller that does not attach usage (a
        bare instance, or a caller with no token accounting) leaves the record's
        usage fields null with ``usage_complete`` false.

        ``failure`` (REQ-TA-QR-001; ADR-005) is an optional allowlisted
        ``{code, phase, diagnostic, exception_type?}`` block recorded under
        ``run_metadata.failure``; it never changes the lifecycle ``status``.
        """
        self._run_usage = usage
        self._run_status = status
        self._run_started_at = started_at
        self._run_completed_at = completed_at
        self._run_failure = failure

    def write_run_record(self, ticker: str, trade_date: str) -> Path:
        """Write this run's structured record to a metadata file on disk.

        REQ-TA-QR-004: every terminal run path must record structured metadata,
        including a failed run whose ``final_state`` is incomplete. The full
        state log (``_log_state``) indexes required state keys and so cannot be
        written for a partial run; this writer records only the canonical run
        record (``run_settings()``), which needs no state. It writes under the
        same per-ticker results directory as the state log, so a run that ended
        in a controlled failure or an exception still leaves a record whose
        ``run_metadata.status`` is ``failed``.

        It never records endpoints, keys, or local paths (the record's allowlist
        guarantees this). Returns the path written.
        """
        safe_ticker = safe_ticker_component(ticker)
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / f"run_record_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.run_settings(), f, indent=4, ensure_ascii=False)
        return log_path

    def run_settings(self) -> dict:
        """The run's canonical structured record, for the report and state log.

        Implements REQ-TA-QR-004: the record is the single canonical
        representation, with ``schema_version``, a ``replayable_settings`` section
        (safe settings, no endpoints/keys/local paths) and a ``run_metadata``
        section (version, timestamps, completion status, token totals, call
        counts). Legacy flat keys are retained for one schema version so existing
        report and state-log consumers keep working (migration strategy C).

        The four run-shaping settings (analysts and the three round caps) are the
        resolved values the graph actually ran with, so a profile or an explicit
        override is reflected here. A run that requested a profile also records
        what was asked for (``profile_requested``), which fields an explicit input
        overrode (``profile_overrides``) and the resolved settings as one block
        (``profile_resolved``) (Implements: ADR-002; REQ-TA-FR-001).

        An allowlist: endpoints (a backend_url can carry credentials), keys and
        local paths are never recorded.
        """
        cfg = self.config
        resolved = getattr(self, "profile_resolution", None)
        if resolved is not None:
            analysts = list(resolved.analysts)
            max_debate_rounds = resolved.max_debate_rounds
            max_risk_discuss_rounds = resolved.max_risk_discuss_rounds
            max_tool_rounds = resolved.max_tool_rounds
            profile_requested = resolved.requested_profile
            profile_overrides = dict(resolved.overrides)
            profile_resolved = resolved.resolved_settings()
        else:  # a bare instance built in a test: fall back to the config values
            analysts = list(self.selected_analysts)
            max_debate_rounds = cfg.get("max_debate_rounds")
            max_risk_discuss_rounds = cfg.get("max_risk_discuss_rounds")
            max_tool_rounds = cfg.get("max_tool_rounds")
            profile_requested = None
            profile_overrides = {}
            profile_resolved = {
                "analysts": analysts,
                "max_debate_rounds": max_debate_rounds,
                "max_risk_discuss_rounds": max_risk_discuss_rounds,
                "max_tool_rounds": max_tool_rounds,
            }

        llm_provider = cfg.get("llm_provider")
        replayable_settings = {
            "profile": profile_requested,
            "analysts": analysts,
            "llm_provider": llm_provider,
            "deep_think_provider": tier_provider(cfg, "deep") if llm_provider else None,
            "deep_think_llm": cfg.get("deep_think_llm"),
            "quick_think_provider": tier_provider(cfg, "quick") if llm_provider else None,
            "quick_think_llm": cfg.get("quick_think_llm"),
            "max_debate_rounds": max_debate_rounds,
            "max_risk_discuss_rounds": max_risk_discuss_rounds,
            "max_tool_rounds": max_tool_rounds,
            "temperature": cfg.get("temperature"),
            "openai_reasoning_effort": cfg.get("openai_reasoning_effort"),
            "google_thinking_level": cfg.get("google_thinking_level"),
            "anthropic_effort": cfg.get("anthropic_effort"),
            "output_language": cfg.get("output_language"),
            "data_vendors": dict(cfg.get("data_vendors") or {}),
            "tool_vendors": dict(cfg.get("tool_vendors") or {}),
            # Per-run token budget is a run input, so it belongs to replayable
            # settings (REQ-TA-FR-002; ADR-004). None = no budget (baseline).
            "token_budget": cfg.get("token_budget"),
        }

        usage = getattr(self, "_run_usage", None)
        status = getattr(self, "_run_status", None) or record.STATUS_COMPLETED

        # Legacy flat keys (migration strategy C): the shape existing report and
        # state-log consumers read. Derived observational keys reflect the
        # resolved settings so requested-versus-resolved stays available.
        legacy = {
            "version": tradingagents.__version__,
            "llm_provider": llm_provider,
            "deep_think_provider": replayable_settings["deep_think_provider"],
            "deep_think_llm": replayable_settings["deep_think_llm"],
            "quick_think_provider": replayable_settings["quick_think_provider"],
            "quick_think_llm": replayable_settings["quick_think_llm"],
            "analysts": analysts,
            "max_debate_rounds": max_debate_rounds,
            "max_risk_discuss_rounds": max_risk_discuss_rounds,
            "max_tool_rounds": max_tool_rounds,
            "profile_requested": profile_requested,
            "profile_overrides": profile_overrides,
            "profile_resolved": profile_resolved,
            "output_language": replayable_settings["output_language"],
            "data_vendors": replayable_settings["data_vendors"],
            "tool_vendors": replayable_settings["tool_vendors"],
        }

        record_obj = record.build_run_record(
            replayable_settings=replayable_settings,
            usage=usage if usage is not None else record.UsageSummary(),
            status=status,
            started_at=getattr(self, "_run_started_at", None),
            completed_at=getattr(self, "_run_completed_at", None),
            version=tradingagents.__version__,
            legacy=legacy,
            budget=self._budget_block(),
            failure=getattr(self, "_run_failure", None),
        )
        return record_obj.to_dict()

    def _budget_block(self) -> dict | None:
        """The run's budget result for ``run_metadata.budget`` (REQ-TA-FR-002).

        Present only when this graph owns a ledger (an observation scope ran);
        a bare instance built in a test has none, so no block is added and the
        record stays byte-compatible with QR-004.
        """
        tracker = getattr(self, "_run_budget_tracker", None)
        if tracker is None:
            return None
        return tracker.snapshot().to_metadata()

    def _attach_budget_observation(self) -> None:
        """Copy the ledger's usage into the run observations (REQ-TA-QR-004 bridge).

        Called after a run completes or fails so the persisted record carries
        the budget ledger's own usage and completeness, never a fabricated
        total. It leaves a caller-supplied usage summary in place when the
        graph owns no ledger.
        """
        tracker = getattr(self, "_run_budget_tracker", None)
        if tracker is None:
            return
        self._run_usage = tracker.to_usage_summary()

    def save_reports(self, final_state, ticker, save_path=None, html=True) -> Path:
        """Write the report tree for a completed run, like the CLI does.

        Programmatic callers get the same on-disk reports the CLI produces. Pass
        an explicit ``save_path`` or let it default under ``results_dir``; the
        report is also written as one HTML page unless ``html`` is False.
        """
        if save_path is None:
            save_path = self.default_report_path(ticker)
        return write_report_tree(final_state, ticker, save_path, settings=self.run_settings(), html=html)

    def default_report_path(self, ticker) -> Path:
        """Where a run's reports go unless told otherwise: under results_dir, stamped now."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return Path(self.config["results_dir"]) / "reports" / f"{safe_ticker_component(ticker)}_{stamp}"

    def create_run_state(self, company_name, trade_date, asset_type: str = "stock", portfolio=None):
        """Build a run's initial state; propagate() and the CLI both start here.

        Injects the resolved instrument identity for every agent (#814). The
        memory log's lessons are not here: the graph's Memory Log step settles
        and loads them alongside the analysts (see ``_memory_step``).
        """
        trade_date = _validate_trade_date(trade_date)
        return self.propagator.create_initial_state(
            company_name,
            trade_date,
            asset_type=asset_type,
            instrument_context=self.resolve_instrument_context(company_name, asset_type, trade_date),
            portfolio_context=portfolio.render(company_name) if portfolio is not None else "",
        )

    def _memory_step(self, state):
        """The graph's Memory Log step, alongside the analysts (#1428): settle every
        ticker's due decisions (#1445), then return the lessons known by the
        trade date for the Portfolio Manager (#1251).

        Settling fetches prices and asks the model for a reflection per decision,
        so it runs beside the analysts instead of before them. A failure here
        does not end the run: the analysts' work is kept, the lessons already in
        the log are used, and the report says what could not be settled.
        """
        note = ""
        try:
            # Another run settling the same log does the work; this one goes on.
            done = self.settle_all_pending(wait=False)
            if done.failed:
                note = (f"{len(done.failed)} past decision(s) could not be settled this run "
                        "and stay pending.")
        except Exception as exc:
            logger.warning("Settling past decisions failed: %s", exc)
            note = f"Past decisions could not be settled this run ({type(exc).__name__}); they stay pending."
        try:
            past_context = self.memory_log.get_past_context(
                state["company_of_interest"], as_of=self._memory_as_of(state["trade_date"]))
        except Exception as exc:
            logger.warning("Reading the memory log failed: %s", exc)
            past_context = ""
            note = note or f"The memory log could not be read this run ({type(exc).__name__})."
        return {"past_context": past_context, "memory_note": note}

    def settle_pending(self, company_name) -> settlement.Settlement:
        """Settle this ticker's decisions whose holding window has now traded.

        A run settles every due decision alongside its analysts, so its own
        decision stays pending until a later run. A caller that is done
        analyzing a ticker (a backtest sweep, a scheduled job) calls this to
        settle it now. Returns what was settled and what failed.
        """
        with run_config(self.config):
            return settlement.settle_pending(company_name, self.memory_log, self.reflector, self.config)

    def settle_all_pending(self, wait: bool = True) -> settlement.Settlement:
        """Settle every ticker's decisions whose holding window has now traded (#1445).

        For a scheduler whose tickers rotate: a ticker it stops analysing would
        otherwise keep its decisions pending, and their lessons out of later runs.
        With ``wait=False`` a pass already running on the same log is not waited for.
        """
        with run_config(self.config):
            return settlement.settle_all_pending(self.memory_log, self.reflector, self.config, wait=wait)

    def record_decision(self, company_name, trade_date, final_state):
        """Record a finished run: its state log, and its decision in the memory log
        for reflection on the next same-ticker run. propagate() and the CLI both end here.

        The run's claim-traceability verdict is settled here too, before the
        state log is written (ADR-001; REQ-TA-QR-002, REQ-TA-INV-005): a
        recommendation whose material claims do not all resolve is not accepted.
        Acceptance is a report property: the rating (REQ-TA-INV-001) and the
        memory-log entry are left as they are.
        """
        audit = audit_material_claims(final_state)
        final_state["claim_audit"] = audit
        final_state["claim_acceptance"] = evaluate_claim_acceptance(
            final_state, enforced=bool(self.config.get("claim_enforcement", False)))
        self._log_state(trade_date, final_state)
        decision = final_state.get("final_trade_decision")
        if not decision:
            logger.warning("No final decision for %s on %s; nothing added to the memory log",
                           company_name, trade_date)
            return
        self.memory_log.store_decision(
            ticker=company_name, trade_date=trade_date, final_trade_decision=decision,
            rating=run_rating(final_state),
        )

    def _run_graph(self, company_name, trade_date, asset_type: str = "stock",
                   checkpoint_thread_id: str | None = None, portfolio=None):
        """Execute the graph and write the resulting state to disk and memory log."""
        init_agent_state = self.create_run_state(company_name, trade_date, asset_type, portfolio)
        args = self.propagator.get_graph_args()

        # Inject the checkpoint thread_id (from checkpoint_scope) so the same
        # ticker+date+graph-shape resumes; a different one starts fresh (#1089).
        if checkpoint_thread_id is not None:
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = checkpoint_thread_id

        # None resumes an existing checkpoint; init_agent_state starts fresh (#1249).
        graph_input = self.checkpoint_input(init_agent_state)
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            if self.debug:
                # A state repeats the messages before it, so each prints once (#1027).
                final_state, printed = {}, set()
                for messages, state in self.stream_run(graph_input, **args):
                    for msg in messages:
                        key = getattr(msg, "id", None) or (type(msg).__name__, getattr(msg, "content", None))
                        if key not in printed:
                            printed.add(key)
                            msg.pretty_print()
                    if state is not None:
                        final_state.update(state)
            else:
                final_state = self.graph.invoke(graph_input, **args)
        except BaseException as exc:
            # REQ-TA-QR-001 (ADR-005 D-A): a provider timeout or an exhausted
            # structured path is a *controlled* failure. Record it and return a
            # non-tradeable REVIEW result rather than letting the exception
            # escape. Any other exception keeps the existing re-raise behaviour
            # (a genuine bug must stay visible, not be silently masked).
            from tradingagents import failure as failure_mod

            code = failure_mod.classify_exception(exc)
            if code is not None:
                failure = failure_mod.build_failure(
                    code, phase="run", exception_type=type(exc).__name__)
                self.set_run_observations(
                    usage=getattr(self, "_run_usage", None),
                    status=record.STATUS_FAILED,
                    started_at=getattr(self, "_run_started_at", None) or started_at,
                    completed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                    failure=failure,
                )
                try:
                    self.write_run_record(company_name, trade_date)
                except OSError:  # never mask the controlled result with a write error
                    logger.warning("Could not write the run record for a failed run", exc_info=True)
                logger.warning("Run for %s on %s ended in a controlled failure: %s (%s)",
                               company_name, trade_date, failure["code"], type(exc).__name__)
                controlled_state = {
                    "company_of_interest": company_name,
                    "trade_date": str(trade_date),
                    "final_trade_decision": (
                        f"No tradeable recommendation could be produced: {failure['diagnostic']}"
                    ),
                    "final_rating": RATING_REVIEW,
                    "run_failure": failure,
                }
                return controlled_state, RATING_REVIEW

            # REQ-TA-QR-004: an unclassified exception still records structured
            # metadata with status=failed, and is re-raised as before.
            self.set_run_observations(
                usage=getattr(self, "_run_usage", None),
                status=record.STATUS_FAILED,
                started_at=getattr(self, "_run_started_at", None) or started_at,
                completed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            )
            try:
                self.write_run_record(company_name, trade_date)
            except OSError:  # never mask the original failure with a write error
                logger.warning("Could not write the run record for a failed run", exc_info=True)
            raise

        # REQ-TA-QR-004: stamp completed status and timestamps before the state
        # log is written, so the persisted record carries the final observations
        # rather than the pre-observation defaults.
        # REQ-TA-QR-001 (ADR-005): a run that completed but produced only a
        # non-tradeable REVIEW because the token budget was exhausted records a
        # TOKEN_BUDGET_EXHAUSTED failure mirror. The lifecycle status stays
        # ``completed`` (D-D); the budget block already carries its own status.
        rating = run_rating(final_state)
        failure = None
        tracker = getattr(self, "_run_budget_tracker", None)
        if is_review(rating) and tracker is not None and tracker.snapshot().status == "BUDGET_EXHAUSTED":
            from tradingagents import failure as failure_mod

            failure = failure_mod.build_failure(
                failure_mod.FailureCode.TOKEN_BUDGET_EXHAUSTED, phase="synthesis")
        self.set_run_observations(
            usage=getattr(self, "_run_usage", None),
            status=record.STATUS_COMPLETED,
            started_at=getattr(self, "_run_started_at", None) or started_at,
            completed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            failure=failure,
        )
        self.record_decision(company_name, trade_date, final_state)

        # Clear checkpoint on successful completion to avoid stale state.
        self.clear_checkpoint_on_success(company_name, trade_date, asset_type, portfolio)

        return final_state, run_rating(final_state)

    def stream_run(self, graph_input, **args):
        """Stream a run as ``(messages, state)`` pairs.

        ``messages`` are the agents' messages, the analysts' included. ``state``
        is the run's state after a top-level step; for a step inside an analyst's
        graph it is that analyst's report once filed, else None.

        Each analyst works in a graph of its own, and the run's state takes the
        analysts' reports only when the slowest has finished, so their messages
        and reports come from their own finished steps ("tasks") as they happen.
        """
        args = {**args, "stream_mode": ["values", "tasks"]}
        # The graph's own config serves every tool call, as in propagate(), even
        # when the process-wide config has changed since. Each step runs in the
        # run's context, so the caller keeps its own between steps.
        context = run_config_context(self.config)
        # Bind this run's budget ledger into the same step context so callbacks
        # raised while streaming attribute usage to this run (ADR-004; FR-002).
        # A caller-supplied StatsCallbackHandler tracker is reused when present.
        tracker = getattr(self, "_run_budget_tracker", None)
        if tracker is None:
            tracker = RunBudgetTracker(self.config.get("token_budget"))
            self._run_budget_tracker = tracker
        context.run(_bind_budget_context, tracker)
        stream = context.run(self.graph.stream, graph_input, subgraphs=True, **args)
        try:
            while (step := context.run(next, stream, None)) is not None:
                namespace, mode, chunk = step
                if namespace:
                    result = chunk.get("result") if mode == "tasks" else None
                    if isinstance(result, dict):
                        report = {k: v for k, v in result.items() if k != "messages" and v}
                        if result.get("messages") or report:
                            yield result.get("messages", []), report or None
                elif mode == "values":
                    yield chunk.get("messages", []), chunk
        finally:
            context.run(stream.close)

    def _log_state(self, trade_date, final_state):
        """Write a run's final state to JSON under the run's own ticker."""
        entry = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
            },
            "trader_investment_plan": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "aggressive_history": final_state["risk_debate_state"]["aggressive_history"],
                "conservative_history": final_state["risk_debate_state"]["conservative_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
            "final_rating": run_rating(final_state),
            "claim_audit": final_state.get("claim_audit"),
            "claim_acceptance": final_state.get("claim_acceptance"),
            "material_claims": final_state.get("material_claims", []),
            "claim_fallback": final_state.get("claim_fallback"),
            "run_settings": self.run_settings(),
        }

        # A ticker that would escape the results directory is rejected.
        safe_ticker = safe_ticker_component(final_state["company_of_interest"])
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            # Reports can be in any language and this file is read by a person.
            json.dump(entry, f, indent=4, ensure_ascii=False)
