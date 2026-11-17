import os
from dataclasses import dataclass, field

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_DEEP_THINK_PROVIDER":       "deep_think_provider",
    "TRADINGAGENTS_QUICK_THINK_PROVIDER":      "quick_think_provider",
    "TRADINGAGENTS_DEEP_THINK_BACKEND_URL":    "deep_think_backend_url",
    "TRADINGAGENTS_QUICK_THINK_BACKEND_URL":   "quick_think_backend_url",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_MAX_TOOL_ROUNDS":      "max_tool_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_CLAIM_ENFORCEMENT":    "claim_enforcement",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_TEMPERATURE":          "temperature",
    "TRADINGAGENTS_LLM_MAX_RETRIES":      "llm_max_retries",
    "TRADINGAGENTS_MAX_TOKENS":           "max_tokens",
    "TRADINGAGENTS_TOKEN_BUDGET":         "token_budget",
    # Provider-specific reasoning/thinking knobs (None = each provider's own
    # default). Settable here for non-interactive runs; the CLI also offers an
    # interactive choice, which is skipped when the matching var is set.
    "TRADINGAGENTS_GOOGLE_THINKING_LEVEL":   "google_thinking_level",
    "TRADINGAGENTS_OPENAI_REASONING_EFFORT": "openai_reasoning_effort",
    "TRADINGAGENTS_ANTHROPIC_EFFORT":        "anthropic_effort",
}


_BOOL_TRUE = ("true", "1", "yes", "on")
_BOOL_FALSE = ("false", "0", "no", "off")


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value.

    Invalid values raise ``ValueError`` rather than silently falling back to a
    default — a misspelled boolean (e.g. ``treu``) or non-numeric int should fail
    loudly at startup, not quietly misconfigure an unattended run.
    """
    if isinstance(reference, bool):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ValueError(
            f"expected a boolean ({'/'.join(_BOOL_TRUE + _BOOL_FALSE)}), got {value!r}"
        )
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        try:
            if key == "token_budget":
                # The optional default is None, so ordinary type-based coercion
                # would leave this as text. Parse an integer directly: float
                # conversion would silently invent an allowed token count.
                budget = int(raw)
                if budget < 0:
                    raise ValueError("expected a non-negative integer")
                config[key] = budget
            else:
                config[key] = _coerce(raw, config.get(key))
        except ValueError as exc:
            raise ValueError(f"Invalid value for {env_var}: {exc}") from exc
    return config


def build_default_config() -> dict:
    """The built-in defaults with the TRADINGAGENTS_* environment folded in.

    Read when the package is imported, as DEFAULT_CONFIG; call it again to see
    the environment as it is now.
    """
    return _apply_env_overrides({
        "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR") or os.path.join(_TRADINGAGENTS_HOME, "logs"),
        "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR") or os.path.join(_TRADINGAGENTS_HOME, "cache"),
        "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH") or os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md"),
        # Optional cap on the number of resolved memory log entries. When set,
        # the oldest resolved entries are pruned once this limit is exceeded.
        # Pending entries are never pruned. None disables rotation entirely.
        "memory_log_max_entries": None,
        # LLM settings
        "llm_provider": "openai",
        "deep_think_llm": "gpt-6-sol",
        "quick_think_llm": "gpt-6-luna",
        # When None, each provider's client falls back to its own default endpoint
        # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
        # The CLI overrides this per provider when the user picks one. Keeping a
        # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
        # being forwarded to Gemini, producing malformed request URLs).
        "backend_url": None,
        # A tier may name its own provider and endpoint (#1440): the quick tier serves
        # the analysts, researchers, debaters and trader, the deep tier the managers.
        # None means the tier uses llm_provider and backend_url.
        "quick_think_provider": None,
        "deep_think_provider": None,
        "quick_think_backend_url": None,
        "deep_think_backend_url": None,
        # Provider-specific thinking configuration
        "google_thinking_level": None,      # "high", "minimal", etc.
        "openai_reasoning_effort": None,    # "medium", "high", "low"
        "anthropic_effort": None,           # "high", "medium", "low"
        # Sampling temperature, forwarded to every provider when set. None leaves
        # each provider at its own default. Lower values reduce run-to-run
        # variation on models that honor it; reasoning models largely ignore it
        # and no setting makes LLM output bit-identical across runs (see README).
        "temperature": None,
        # SDK retry budget forwarded to every provider chat client. None leaves each
        # provider/SDK at its own default (usually 2). Raise it to ride out bursty
        # 429 throttling on rate-limited deployments instead of aborting a run (#1091).
        "llm_max_retries": None,
        # Cap on output tokens forwarded to every provider chat client. None leaves
        # each provider at its own default. Set it to bound a model that emits
        # unbounded reasoning/output and hangs or trips a gateway idle timeout
        # (e.g. some deepseek-v4-flash deployments, #1204).
        "max_tokens": None,
        # Recorded tokens for one analysis run (ADR-003; REQ-TA-FR-002).
        # None disables budget admission; zero enables it immediately. Calls
        # already started and required synthesis can exceed this value.
        "token_budget": None,
        # Checkpoint/resume: when True, LangGraph saves state after each node
        # so a crashed run can resume from the last successful step.
        "checkpoint_enabled": False,
        # ADR-001 fail-closed: on, a recommendation whose material claims do not
        # all resolve to a source report is not accepted (REQ-TA-QR-002,
        # REQ-TA-INV-005). Off, the audit is still recorded and the run reports
        # NOT_ENFORCED, never ACCEPTED. It never changes the rating.
        "claim_enforcement": True,
        # Output language for analyst reports and final decision
        # Internal agent debate stays in English for reasoning quality
        "output_language": "English",
        # Debate and discussion settings
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "max_recur_limit": 100,
        # Rounds of tool calls an analyst may make before it is asked for its report.
        "max_tool_rounds": 20,
        # News / data fetching parameters
        # Increase for longer lookback strategies or to broaden macro coverage;
        # decrease to reduce token usage in agent prompts.
        "news_article_limit": 20,             # max articles per ticker (ticker-news)
        "global_news_article_limit": 10,      # max articles for global/macro news
        "global_news_lookback_days": 7,       # macro news lookback window
        # Search queries used by get_global_news for macro headlines. Extend or
        # replace to broaden geographic / sector coverage.
        "global_news_queries": [
            "Federal Reserve interest rates inflation",
            "S&P 500 earnings GDP economic outlook",
            "geopolitical risk trade war sanctions",
            "ECB Bank of England BOJ central bank policy",
            "oil commodities supply chain energy",
        ],
        # Data vendor configuration
        # Category-level configuration (default for all tools in category).
        # The configured value is the exact vendor chain — requests are NOT silently
        # routed to vendors you didn't choose. For ordered fallback, list several,
        # e.g. "yfinance,alpha_vantage". "default" uses all available vendors.
        "data_vendors": {
            "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
            "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
            # Statements come from SEC EDGAR as filed (US filers), then Yahoo; the
        # overview and insider tools, which SEC EDGAR does not serve, from Yahoo.
        "fundamental_data": "sec_edgar,yfinance",  # Options: sec_edgar, alpha_vantage, yfinance
            "news_data": "yfinance",             # Options: alpha_vantage, yfinance
            "macro_data": "fred",                # Options: fred (needs FRED_API_KEY)
            "prediction_markets": "polymarket",  # Options: polymarket (keyless)
        },
        # Tool-level configuration (takes precedence over category-level)
        "tool_vendors": {
            # Example: "get_stock_data": "alpha_vantage",  # Override category default
        },
        # Benchmark for alpha calculation in the reflection layer.
        # ``benchmark_ticker`` (when set) overrides the suffix map for all
        # tickers; leave it None to use ``benchmark_map`` for auto-detection
        # based on the ticker's exchange suffix. SPY remains the US default
        # so the reflection label keeps reading "Alpha vs SPY" for US tickers
        # while non-US tickers get their regional index automatically.
        # Trading days from the first close after the analysis date over which a
        # decision's outcome is measured, for reflection and for the backtest figures.
        "holding_period_days": 5,
        "benchmark_ticker": None,
        "benchmark_map": {
            ".NS":  "^NSEI",       # NSE India (Nifty 50)
            ".BO":  "^BSESN",      # BSE India (Sensex)
            ".T":   "^N225",       # Tokyo (Nikkei 225)
            ".TW":  "^TWII",       # Taiwan (TAIEX)
            ".TWO": "^TWII",       # Taipei OTC (TPEx has no Yahoo index; TAIEX)
            ".KS":  "^KS11",       # Korea (KOSPI)
            ".KQ":  "^KQ11",       # Korea (KOSDAQ)
            ".HK":  "^HSI",        # Hong Kong (Hang Seng)
            ".SI":  "^STI",        # Singapore (Straits Times)
            ".L":   "^FTSE",       # London (FTSE 100)
            ".DE":  "^GDAXI",      # Germany (DAX)
            ".PA":  "^FCHI",       # Paris (CAC 40)
            ".AS":  "^AEX",        # Amsterdam (AEX)
            ".SW":  "^SSMI",       # Switzerland (SMI)
            ".MI":  "FTSEMIB.MI",  # Milan (FTSE MIB)
            ".TO":  "^GSPTSE",     # Toronto (TSX Composite)
            ".AX":  "^AXJO",       # Australia (ASX 200)
            ".SS":  "000001.SS",   # Shanghai (SSE Composite)
            ".SZ":  "399001.SZ",   # Shenzhen (SZSE Component)
            ".SA":  "^BVSP",       # B3 Brazil (Ibovespa)
            "":     "SPY",         # default for US-listed tickers (no suffix)
        },

    })


DEFAULT_CONFIG = build_default_config()


# Analysis profiles (Implements: ADR-002; REQ-TA-FR-001).
# A profile bundles the four settings that trade cost against depth: the
# analyst set, the Bull/Bear debate budget, the risk-discussion budget and the
# per-analyst tool-round cap. The values are fixed by the approved ADR; the
# profile only chooses among them, it never invents a number.
PROFILE_MAPPING: dict[str, dict] = {
    "quick": {
        "analysts": ("market", "news"),
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "max_tool_rounds": 3,
    },
    "standard": {
        "analysts": ("market", "social", "news", "fundamentals"),
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "max_tool_rounds": 20,
    },
    "deep": {
        "analysts": ("market", "social", "news", "fundamentals"),
        "max_debate_rounds": 3,
        "max_risk_discuss_rounds": 3,
        "max_tool_rounds": 20,
    },
}

# The legal profile names, in the order an error message should list them.
PROFILE_NAMES = tuple(PROFILE_MAPPING)

# The four settings a profile sets, and the config keys an explicit override
# may target. ``analysts`` lives outside the config dict; the other three are
# ordinary config keys.
_PROFILE_KEYS = (
    "analysts",
    "max_debate_rounds",
    "max_risk_discuss_rounds",
    "max_tool_rounds",
)


@dataclass(frozen=True)
class ResolvedProfile:
    """The settings one analysis run will actually use (Implements: ADR-002).

    ``requested_profile`` is what the user asked for (``None`` when no profile
    was given); ``overrides`` records only the fields an explicit input set, so
    a report can show requested-versus-resolved; the four settings are the
    values the graph must run with.
    """

    requested_profile: str | None
    analysts: tuple[str, ...]
    max_debate_rounds: int
    max_risk_discuss_rounds: int
    max_tool_rounds: int
    overrides: dict = field(default_factory=dict)

    def resolved_settings(self) -> dict:
        """The four settings as a plain dict, for run_settings() and reports."""
        return {
            "analysts": list(self.analysts),
            "max_debate_rounds": self.max_debate_rounds,
            "max_risk_discuss_rounds": self.max_risk_discuss_rounds,
            "max_tool_rounds": self.max_tool_rounds,
        }


def resolve_profile(
    profile: str | None,
    *,
    explicit: dict | None = None,
    defaults: dict | None = None,
    base_analysts=None,
) -> ResolvedProfile:
    """Resolve one run's four settings from a profile plus explicit overrides.

    Implements: ADR-002; REQ-TA-FR-001.

    Precedence, per field: an explicit value beats the profile's value beats the
    built-in default. Only fields present in ``explicit`` are overridden, so a
    profile and a few explicit settings combine rather than replace each other
    (deep with an explicit debate of 1 keeps its risk budget of 3).

    An unknown profile raises ``ValueError`` naming the legal values, before any
    model is built. ``profile=None`` applies no mapping: the four settings come
    from ``explicit`` where given and from ``defaults`` otherwise, so the
    baseline v0.7.1 behaviour is reproduced exactly (no profile key written, no
    setting changed).

    ``explicit`` is keyed by the four setting names in ``_PROFILE_KEYS``; an
    explicit ``analysts`` is a sequence of analyst keys. ``defaults`` supplies
    the fallback for the non-analyst settings when no profile is selected; the
    analyst default is the baseline four-analyst set.

    ``base_analysts`` is the analyst set the run starts from when no explicit
    ``analysts`` override is given (for example the menu's choice, or the profile
    mapping filtered for a crypto asset). It shapes the resolved analysts but is
    *not* recorded in ``overrides`` — only inputs the user named are.
    """
    explicit = dict(explicit or {})
    defaults = dict(defaults or {})

    unknown = set(explicit) - set(_PROFILE_KEYS)
    if unknown:
        raise ValueError(
            f"unknown profile override field(s): {', '.join(sorted(unknown))}; "
            f"choose from {', '.join(_PROFILE_KEYS)}"
        )

    if profile is None:
        base = _resolved_from_defaults(defaults)
        requested = None
    else:
        if profile not in PROFILE_MAPPING:
            raise ValueError(
                f"unknown profile {profile!r}; choose from {', '.join(PROFILE_NAMES)}"
            )
        mapping = PROFILE_MAPPING[profile]
        base = {
            "analysts": tuple(mapping["analysts"]),
            "max_debate_rounds": mapping["max_debate_rounds"],
            "max_risk_discuss_rounds": mapping["max_risk_discuss_rounds"],
            "max_tool_rounds": mapping["max_tool_rounds"],
        }
        requested = profile

    # The starting analyst set (asset-filtered menu / profile choice). It changes
    # the resolved analysts but is not a user override, so it is not recorded.
    if base_analysts is not None:
        base["analysts"] = tuple(base_analysts)

    applied = {}
    for key in _PROFILE_KEYS:
        if key in explicit:
            value = explicit[key]
            if key == "analysts":
                value = tuple(value)
            base[key] = value
            applied[key] = list(value) if key == "analysts" else value

    return ResolvedProfile(
        requested_profile=requested,
        analysts=tuple(base["analysts"]),
        max_debate_rounds=base["max_debate_rounds"],
        max_risk_discuss_rounds=base["max_risk_discuss_rounds"],
        max_tool_rounds=base["max_tool_rounds"],
        overrides=applied,
    )


def _resolved_from_defaults(defaults: dict) -> dict:
    """The baseline four settings for the no-profile case (Implements: REQ-TA-FR-001).

    The analyst set is the graph's v0.7.1 default; the round budgets and the
    tool cap come from ``defaults`` (the env-folded DEFAULT_CONFIG) so an
    environmental override still applies when no profile is requested.
    """
    return {
        "analysts": ("market", "social", "news", "fundamentals"),
        "max_debate_rounds": defaults.get("max_debate_rounds", 1),
        "max_risk_discuss_rounds": defaults.get("max_risk_discuss_rounds", 1),
        "max_tool_rounds": defaults.get("max_tool_rounds", 20),
    }
