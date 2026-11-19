"""Strict settings replay for a prior QR-004 run record (Implements: REQ-TA-FR-008).

REQ-TA-FR-008 lets a later analysis start from the safe, allowlisted settings
recorded for a prior run. Reproducibility here is of **configuration only**: it
does not guarantee identical market data, tool or provider responses, sampled
LLM output, timing, token usage, confidence, or final recommendation.

This module is the loader and validator only. It reads a prior run record,
extracts the version-1 ``replayable_settings`` allowlist, rejects everything it
does not explicitly allow, and produces a :class:`ReplaySettings` whose
``effective_settings()`` reproduces the source block for the allowlisted keys.
It never replays ticker, analysis date, output paths, credentials, endpoints, or
observational metadata, and it never merges arbitrary dictionaries into runtime
configuration.

Input formats accepted (deterministic, no recursive search):
- a root-level ``{"schema_version": ..., "replayable_settings": {...}}`` record;
- a ``full_states_log_*.json`` whose ``run_settings`` holds such a record.
Exactly one candidate settings block must be present; zero or more than one is
rejected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS

# The only schema version this loader understands.
SUPPORTED_SCHEMA_VERSION = "1"

# The version-1 replayable_settings allowlist (approved, REQ-TA-FR-008).
ALLOWED_KEYS = frozenset(
    {
        "profile",
        "analysts",
        "llm_provider",
        "deep_think_provider",
        "quick_think_provider",
        "deep_think_llm",
        "quick_think_llm",
        "max_debate_rounds",
        "max_risk_discuss_rounds",
        "max_tool_rounds",
        "temperature",
        "openai_reasoning_effort",
        "google_thinking_level",
        "anthropic_effort",
        "output_language",
        "data_vendors",
        "tool_vendors",
    }
)

# Required version-1 fields: a missing one fails closed (no silent default).
REQUIRED_KEYS = frozenset(
    {
        "profile",
        "analysts",
        "llm_provider",
        "deep_think_llm",
        "quick_think_llm",
        "max_debate_rounds",
        "max_risk_discuss_rounds",
        "max_tool_rounds",
        "output_language",
        "data_vendors",
    }
)

# Optional fields and the documented default used when they are absent.
OPTIONAL_DEFAULTS: dict[str, Any] = {
    "deep_think_provider": None,
    "quick_think_provider": None,
    "temperature": None,
    "openai_reasoning_effort": None,
    "google_thinking_level": None,
    "anthropic_effort": None,
    "tool_vendors": {},
}

# Valid analyst keys (matches the analyst wire values).
VALID_ANALYSTS = frozenset({"market", "social", "news", "fundamentals"})

# Valid providers (the model catalog's provider keys).
VALID_PROVIDERS = frozenset(MODEL_OPTIONS)

# The documented data-vendor categories (must match default_config.data_vendors).
VENDOR_CATEGORIES = frozenset(
    {
        "core_stock_apis",
        "technical_indicators",
        "fundamental_data",
        "news_data",
        "macro_data",
        "prediction_markets",
    }
)

# Known vendor names that may appear in a vendor chain.
VALID_VENDORS = frozenset(
    {"yfinance", "alpha_vantage", "sec_edgar", "fred", "polymarket"}
)

# Values that look like an absolute local path or a credential; never echoed.
_PATH_PREFIXES = ("/", "~", "./", "../", "file://", "C:\\", "\\\\")
_SECRET_MARKERS = ("sk-", "ghp_", "gho_", "github_pat_", "AKIA", "Bearer ", "PRIVATE KEY")


class ReplayError(ValueError):
    """A run record could not be safely replayed (REQ-TA-FR-008).

    The message names the offending field but never echoes a value that could be
    a secret, path, endpoint, or credential.
    """


@dataclass(frozen=True)
class ReplaySettings:
    """Validated, normalized version-1 replayable settings (REQ-TA-FR-008)."""

    profile: str | None
    analysts: tuple[str, ...]
    llm_provider: str
    deep_think_provider: str | None
    quick_think_provider: str | None
    deep_think_llm: str
    quick_think_llm: str
    max_debate_rounds: int
    max_risk_discuss_rounds: int
    max_tool_rounds: int
    temperature: float | None
    openai_reasoning_effort: str | None
    google_thinking_level: str | None
    anthropic_effort: str | None
    output_language: str
    data_vendors: dict[str, str]
    tool_vendors: dict[str, str]

    def effective_settings(self) -> dict[str, Any]:
        """The normalized replayable settings as a plain dict.

        This is exactly the allowlisted key set, so it can be compared directly
        against a source ``replayable_settings`` block for equality.
        """
        return {
            "profile": self.profile,
            "analysts": list(self.analysts),
            "llm_provider": self.llm_provider,
            "deep_think_provider": self.deep_think_provider,
            "quick_think_provider": self.quick_think_provider,
            "deep_think_llm": self.deep_think_llm,
            "quick_think_llm": self.quick_think_llm,
            "max_debate_rounds": self.max_debate_rounds,
            "max_risk_discuss_rounds": self.max_risk_discuss_rounds,
            "max_tool_rounds": self.max_tool_rounds,
            "temperature": self.temperature,
            "openai_reasoning_effort": self.openai_reasoning_effort,
            "google_thinking_level": self.google_thinking_level,
            "anthropic_effort": self.anthropic_effort,
            "output_language": self.output_language,
            "data_vendors": dict(self.data_vendors),
            "tool_vendors": dict(self.tool_vendors),
        }


def load_replayable_settings(path: str | Path) -> ReplaySettings:
    """Read, validate, and normalize a prior run record's replayable settings.

    Fails closed (raises :class:`ReplayError`) on any unsafe or malformed input.
    """
    p = Path(path)
    if not p.is_file():
        raise ReplayError(f"run record not found: {p.name}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ReplayError(f"run record is not valid JSON: {p.name}") from exc
    if not isinstance(data, dict):
        raise ReplayError("run record must be a JSON object")

    block = _extract_replayable_block(data)
    return _validate_and_build(block)


def _extract_replayable_block(data: dict[str, Any]) -> dict[str, Any]:
    """Find exactly one candidate replayable_settings block, or fail closed.

    Accepts a root-level ``{schema_version, replayable_settings}`` record or a
    ``full_states_log`` whose ``run_settings`` holds one. No recursive search.
    """
    candidates: list[dict[str, Any]] = []

    # Form 1: this object is itself a run record.
    if "schema_version" in data or "replayable_settings" in data:
        candidates.append(data)

    # Form 2: a full state log carrying run_settings.
    run_settings = data.get("run_settings")
    if isinstance(run_settings, dict):
        candidates.append(run_settings)

    if len(candidates) == 0:
        raise ReplayError("no replayable settings block found in the run record")
    if len(candidates) > 1:
        raise ReplayError(
            "ambiguous run record: more than one candidate settings block found"
        )

    record = candidates[0]
    version = record.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ReplayError(
            f"unsupported schema version (expected {SUPPORTED_SCHEMA_VERSION!r}); "
            "only schema version 1 can be replayed"
        )
    block = record.get("replayable_settings")
    if not isinstance(block, dict):
        raise ReplayError("run record has no replayable_settings object")
    return block


def _looks_like_path_or_secret(key: str, value: Any) -> bool:
    """Whether a string value looks like a local path or a credential (never echoed)."""
    if not isinstance(value, str):
        return False
    if value.startswith(_PATH_PREFIXES):
        return True
    return any(marker in value for marker in _SECRET_MARKERS)


def _require_str(block: dict[str, Any], key: str) -> str:
    value = block.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReplayError(f"field {key!r} must be a non-empty string")
    if _looks_like_path_or_secret(key, value):
        raise ReplayError(f"field {key!r} contains a path or credential-like value")
    return value


def _optional_str(block: dict[str, Any], key: str) -> str | None:
    value = block.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ReplayError(f"field {key!r} must be a non-empty string or null")
    if _looks_like_path_or_secret(key, value):
        raise ReplayError(f"field {key!r} contains a path or credential-like value")
    return value


def _require_positive_int(block: dict[str, Any], key: str) -> int:
    value = block.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReplayError(f"field {key!r} must be an integer")
    if value < 1:
        raise ReplayError(f"field {key!r} must be at least 1")
    return value


def _validate_and_build(block: dict[str, Any]) -> ReplaySettings:
    unknown = set(block) - ALLOWED_KEYS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ReplayError(f"unknown or forbidden field(s): {names}")

    missing = REQUIRED_KEYS - set(block)
    if missing:
        names = ", ".join(sorted(missing))
        raise ReplayError(f"missing required field(s): {names}")

    # Start from the documented optional defaults, overlaid by the present keys.
    merged: dict[str, Any] = {**OPTIONAL_DEFAULTS}
    merged.update({k: v for k, v in block.items() if k in ALLOWED_KEYS})

    profile = merged.get("profile")
    if profile is not None:
        if not isinstance(profile, str):
            raise ReplayError("field 'profile' must be a string or null")
        if profile not in {"quick", "standard", "deep"}:
            raise ReplayError("field 'profile' is not a supported profile")

    analysts_raw = block.get("analysts")
    if not isinstance(analysts_raw, list) or not analysts_raw:
        raise ReplayError("field 'analysts' must be a non-empty list")
    analysts: list[str] = []
    for name in analysts_raw:
        if not isinstance(name, str) or name not in VALID_ANALYSTS:
            raise ReplayError("field 'analysts' contains an invalid analyst name")
        analysts.append(name)

    llm_provider = _require_str(block, "llm_provider").lower()
    if llm_provider not in VALID_PROVIDERS:
        raise ReplayError("field 'llm_provider' is not a supported provider")

    deep_provider = _optional_str(merged, "deep_think_provider")
    quick_provider = _optional_str(merged, "quick_think_provider")
    for label, prov in (("deep_think_provider", deep_provider),
                        ("quick_think_provider", quick_provider)):
        if prov is not None and prov.lower() not in VALID_PROVIDERS:
            raise ReplayError(f"field {label!r} is not a supported provider")

    deep_llm = _require_str(block, "deep_think_llm")
    quick_llm = _require_str(block, "quick_think_llm")

    max_debate = _require_positive_int(block, "max_debate_rounds")
    max_risk = _require_positive_int(block, "max_risk_discuss_rounds")
    max_tool = _require_positive_int(block, "max_tool_rounds")

    temperature = merged.get("temperature")
    if temperature is not None:
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise ReplayError("field 'temperature' must be a number or null")
        temperature = float(temperature)

    openai_effort = _optional_str(merged, "openai_reasoning_effort")
    google_level = _optional_str(merged, "google_thinking_level")
    anthropic_effort = _optional_str(merged, "anthropic_effort")

    output_language = _require_str(block, "output_language")

    data_vendors = _require_str_dict(block, "data_vendors", VENDOR_CATEGORIES)
    tool_vendors = _optional_str_dict(merged, "tool_vendors")

    return ReplaySettings(
        profile=profile,
        analysts=tuple(analysts),
        llm_provider=llm_provider,
        deep_think_provider=deep_provider.lower() if deep_provider else None,
        quick_think_provider=quick_provider.lower() if quick_provider else None,
        deep_think_llm=deep_llm,
        quick_think_llm=quick_llm,
        max_debate_rounds=max_debate,
        max_risk_discuss_rounds=max_risk,
        max_tool_rounds=max_tool,
        temperature=temperature,
        openai_reasoning_effort=openai_effort,
        google_thinking_level=google_level,
        anthropic_effort=anthropic_effort,
        output_language=output_language,
        data_vendors=data_vendors,
        tool_vendors=tool_vendors,
    )


def _check_vendor_chain(key: str, chain: str) -> None:
    if _looks_like_path_or_secret(key, chain):
        raise ReplayError(f"field {key!r} contains a path or credential-like value")
    for name in chain.split(","):
        if name.strip() and name.strip() not in VALID_VENDORS:
            raise ReplayError(f"field {key!r} names an unknown data vendor")


def _require_str_dict(block: dict[str, Any], key: str,
                      allowed_keys: frozenset[str]) -> dict[str, str]:
    value = block.get(key)
    if not isinstance(value, dict):
        raise ReplayError(f"field {key!r} must be an object")
    out: dict[str, str] = {}
    for name, chain in value.items():
        if name not in allowed_keys:
            raise ReplayError(f"field {key!r} has an unknown key")
        if not isinstance(chain, str) or not chain.strip():
            raise ReplayError(f"field {key!r} has a non-string chain")
        _check_vendor_chain(key, chain)
        out[name] = chain
    return out


def _optional_str_dict(block: dict[str, Any], key: str) -> dict[str, str]:
    value = block.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ReplayError(f"field {key!r} must be an object")
    out: dict[str, str] = {}
    for name, chain in value.items():
        if not isinstance(chain, str) or not chain.strip():
            raise ReplayError(f"field {key!r} has a non-string chain")
        _check_vendor_chain(key, chain)
        out[name] = chain
    return out
