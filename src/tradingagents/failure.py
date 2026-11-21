"""Controlled failure codes and the machine-readable failure record (REQ-TA-QR-001).

Implements: ADR-005; REQ-TA-QR-001.

REQ-TA-QR-001 requires five controlled failure scenarios to each end with a
defined status and a safe diagnostic and zero uncaught exceptions. The registry
has not approved a new top-level status enum, and the run record's lifecycle
status is fixed at ``completed`` / ``failed`` (REQ-TA-QR-004). So this module
adds a *separate* allowlisted ``run_metadata.failure`` block — never a new
status — carrying a closed, machine-readable code plus a fixed safe diagnostic.

This module depends only on the standard library and the public data error
taxonomy. It does not import the graph, the CLI, or any provider SDK, so the
graph, the CLI and the report layer all share one classification (SC-1).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class FailureCode(StrEnum):
    """The closed vocabulary of controlled failures (ADR-005 D-C).

    Exactly these five codes; adding one is a vocabulary change that returns to
    the ADR.
    """

    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    INVALID_AGENT_JSON = "INVALID_AGENT_JSON"
    MISSING_API_KEY = "MISSING_API_KEY"
    STOCK_DATA_UNAVAILABLE = "STOCK_DATA_UNAVAILABLE"
    TOKEN_BUDGET_EXHAUSTED = "TOKEN_BUDGET_EXHAUSTED"


# A fixed, safe human-readable message per code (ADR-005 D-E). Never derived
# from raw exception text, a URL, an endpoint, a key or a local path.
_DIAGNOSTICS: dict[str, str] = {
    FailureCode.PROVIDER_TIMEOUT: (
        "The model provider did not respond in time; the run stopped without a "
        "tradeable result. Retry, or choose a faster model/provider."
    ),
    FailureCode.INVALID_AGENT_JSON: (
        "An agent returned output that could not be parsed; the run stopped "
        "without a tradeable result rather than inventing one."
    ),
    FailureCode.MISSING_API_KEY: (
        "A required model provider API key is not configured; set the provider's "
        "key (see .env.example) before running."
    ),
    FailureCode.STOCK_DATA_UNAVAILABLE: (
        "Required market data was unavailable; no exact price-based conclusion "
        "was issued. This is a data gap, not a finding about the instrument."
    ),
    FailureCode.TOKEN_BUDGET_EXHAUSTED: (
        "The run reached its token budget before producing a complete result; "
        "it stopped without a tradeable recommendation."
    ),
}

# Error types that mean "the provider did not answer" (timeout / transport).
_TIMEOUT_TYPE_NAMES = frozenset({
    "TimeoutError",
    "Timeout",
    "ReadTimeout",
    "ConnectTimeout",
    "APITimeoutError",
    "APIConnectionError",
    "ConnectionError",
})

# Error types that mean "the agent's structured output could not be parsed".
_INVALID_JSON_TYPE_NAMES = frozenset({
    "JSONDecodeError",
    "ValidationError",
    "OutputParserException",
    "ModelBehaviorError",
})


def diagnostic_for(code: FailureCode | str) -> str:
    """The fixed safe diagnostic for ``code`` (ADR-005 D-E)."""
    return _DIAGNOSTICS.get(str(code), "The run ended in a controlled failure.")


def build_failure(
    code: FailureCode | str,
    *,
    phase: str,
    exception_type: str | None = None,
) -> dict[str, Any]:
    """Build one ``run_metadata.failure`` block (ADR-005 D-C).

    Contains only the allowlisted keys: ``code``, ``phase``, a fixed
    ``diagnostic``, and an optional non-sensitive ``exception_type`` class name.
    No raw exception text, URL, endpoint, key or local path is included.
    """
    block: dict[str, Any] = {
        "code": str(code),
        "phase": phase,
        "diagnostic": diagnostic_for(code),
    }
    if exception_type:
        block["exception_type"] = _safe_exception_type(exception_type)
    return block


def _safe_exception_type(name: str) -> str:
    """A bare class name only (no module path, args, or message)."""
    text = str(name).rsplit(".", 1)[-1]
    # Keep it a plausible identifier; drop anything else so no payload leaks.
    return text if text.isidentifier() else "Exception"


def classify_exception(exc: BaseException) -> FailureCode | None:
    """Map a provider/parse exception to a failure code, or ``None`` if not ours.

    Timeout/transport errors and structured-output parse errors are the two
    LLM-layer controlled failures (ADR-005). Anything else returns ``None`` so
    the caller does not misclassify an unrelated bug as a controlled failure.
    """
    if isinstance(exc, TimeoutError):
        return FailureCode.PROVIDER_TIMEOUT
    # Match by class name up the MRO: provider SDKs and pydantic live outside
    # this package, so name-matching avoids importing them here.
    names = {cls.__name__ for cls in type(exc).__mro__}
    if names & _TIMEOUT_TYPE_NAMES:
        return FailureCode.PROVIDER_TIMEOUT
    if names & _INVALID_JSON_TYPE_NAMES:
        return FailureCode.INVALID_AGENT_JSON
    return None


class MissingApiKeyError(ValueError):
    """A provider credential is missing or invalid (ADR-005 D-B).

    A ``ValueError`` subclass so existing ``except ValueError`` callers keep
    working. Carries only the environment-variable name, never the key value,
    and a fixed safe diagnostic.
    """

    code = FailureCode.MISSING_API_KEY

    def __init__(self, env_var: str | None = None, *, provider: str | None = None):
        self.env_var = env_var
        self.provider = provider
        detail = f" ({env_var})" if env_var else ""
        super().__init__(
            "A required model provider API key is not configured"
            f"{detail}; set it before running."
        )

    def to_failure(self, *, phase: str = "startup") -> dict[str, Any]:
        """This error as a ``run_metadata.failure`` block (ADR-005 D-C)."""
        return build_failure(self.code, phase=phase, exception_type=type(self).__name__)


__all__ = [
    "FailureCode",
    "MissingApiKeyError",
    "build_failure",
    "classify_exception",
    "diagnostic_for",
]
