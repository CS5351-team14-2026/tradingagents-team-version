"""Shared redaction for secret-bearing text and structures (Implements: REQ-TA-SEC-001).

A single, dependency-free sanitizer for the output boundaries that must never
carry a configured secret: CLI errors, application logs, provider exceptions,
``message_tool.log``, reports, run records, and replay-validation errors.

Design rules (SEC-001):

- High-confidence secret *shapes* only — never indiscriminate word matching, so
  ordinary prose, model names, tickers, UUIDs, hashes, public URLs, HTTP codes,
  and numeric token counts stay readable.
- One stable marker: :data:`REDACTED`.
- ``redact`` copies caller-owned mappings/sequences rather than mutating them.
- Safe on malformed input: sanitizing never raises.
- No provider SDK imports, no environment reads, no record of which real value
  triggered redaction.

This is not general-purpose DLP; it targets the patterns SEC-001 names.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

# Field names whose values are always sensitive, matched case-insensitively.
_SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd|"
    r"authorization|cookie|credential|client[_-]?secret|private[_-]?key)",
    re.IGNORECASE,
)
# Keys that merely *name* something token-ish without carrying a secret value
# (e.g. ``tokens_in``, ``api_key_name``) must not be redacted by name alone.
_SAFE_TOKEN_KEYS = frozenset(
    {"tokens_in", "tokens_out", "total_tokens", "max_tokens", "api_key_name",
     "api_key_env", "token_budget", "token_count", "token_totals"}
)

# High-confidence value patterns (ordered; applied to text).
_VALUE_PATTERNS = [
    # PEM private-key blocks.
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
               re.DOTALL),
    # Common API token/key prefixes with a long opaque tail.
    re.compile(r"\b(?:sk|rk|ghp|gho|ghs|ghu|github_pat|xox[baprs]|AKIA|AIza)[-_A-Za-z0-9]{12,}\b"),
    # Authorization / cookie header values.
    re.compile(r"(?i)\b(authorization|proxy-authorization)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bcookie\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bset-cookie\s*:\s*[^\n]+"),
    # ``user:password@host`` credentials embedded in a URL.
    re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"),
    # .env-shaped assignments for sensitive names.
    re.compile(r"(?im)^(\s*[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*\s*=\s*)\S+"),
    # Absolute POSIX and Windows user paths.
    re.compile(r"(/home/[^/\s]+|/Users/[^/\s]+|/root/[^\s]+)"),
    re.compile(r"([A-Za-z]:\\\\?Users\\\\?[^\\\s]+)"),
]


def _redact_pem_whole(text: str) -> str:
    return _VALUE_PATTERNS[0].sub(REDACTED, text)


def redact_text(text: str) -> str:
    """Return ``text`` with high-confidence secret shapes replaced.

    Idempotent and safe on any string. Non-sensitive text is returned unchanged.
    """
    if not isinstance(text, str) or not text:
        return text
    out = text
    # A private-key block is replaced wholesale first.
    out = _redact_pem_whole(out)
    # URL credentials: keep scheme + host, redact the userinfo.
    out = re.sub(
        r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@",
        lambda m: f"{m.group(1)}{REDACTED}@",
        out,
    )
    # ``Bearer``/``Basic``/``Token`` scheme values anywhere.
    out = re.sub(r"(?i)\b(Bearer|Basic|Token)\s+[A-Za-z0-9._\-+/=]{8,}",
                 lambda m: f"{m.group(1)} {REDACTED}", out)
    # Sensitive-name assignments (``KEY=...``/``token: ...``) anywhere, but not
    # the safe token-metric names (tokens_in/out, token count/budget, etc.).
    out = _redact_assignments(out)
    # Header values (Authorization/Cookie/Set-Cookie) with everything after.
    out = re.sub(r"(?i)\b(authorization|proxy-authorization)\s*[:=]\s*[^\n,;]+",
                 lambda m: f"{m.group(1)}: {REDACTED}", out)
    out = re.sub(r"(?i)\b(set-cookie|cookie)\s*[:=]\s*[^\n,;]+",
                 lambda m: f"{m.group(1)}: {REDACTED}", out)
    # Absolute user paths.
    out = re.sub(r"(/home/[^/\s]+|/Users/[^/\s]+|/root/[^\s]+)", REDACTED, out)
    out = re.sub(r"([A-Za-z]:\\\\?Users\\\\?[^\\\s]+)", REDACTED, out)
    # API key/token shapes (not already placed inside a marker).
    out = _replace_token_shapes(out)
    return out


# ``NAME = value`` / ``NAME: value`` where NAME looks sensitive (contains KEY,
# TOKEN, SECRET, PASSWORD, CREDENTIAL, AUTH, COOKIE) but is not a safe metric.
_ASSIGN_RE = re.compile(
    r"(?i)\b((?:[A-Za-z0-9]+[_-])*(?:API[_-]?KEY|ACCESS[_-]?TOKEN|REFRESH[_-]?TOKEN|"
    r"SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTHORIZATION|COOKIE|BEARER)"
    r"(?:[_-][A-Za-z0-9]+)*)\s*([:=])\s*(['\"]?)([^\s'\";,]+)\3"
)


def _redact_assignments(text: str) -> str:
    def _sub(m: re.Match) -> str:
        name = m.group(1)
        if name.lower() in _SAFE_TOKEN_KEYS:
            return m.group(0)
        value = m.group(4)
        if value == REDACTED:
            return m.group(0)
        return f"{name}{m.group(2)}{REDACTED}"
    return _ASSIGN_RE.sub(_sub, text)


_TOKEN_SHAPE_RE = re.compile(
    r"\b(?:sk|rk|ghp|gho|ghs|ghu|github_pat|xox[baprs]|AKIA|AIza)[-_A-Za-z0-9]{12,}\b"
)


def _replace_token_shapes(text: str) -> str:
    def _sub(m: re.Match) -> str:
        # Never re-redact inside an existing marker.
        if REDACTED in m.group(0):
            return m.group(0)
        return REDACTED
    return _TOKEN_SHAPE_RE.sub(_sub, text)


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    if key.lower() in _SAFE_TOKEN_KEYS:
        return False
    return bool(_SENSITIVE_KEY_RE.search(key))


def redact(value: Any) -> Any:
    """Return a sanitized copy of ``value`` (str, mapping, sequence, or scalar).

    Mappings and sequences are copied, not mutated. Sensitive *named* fields are
    replaced with :data:`REDACTED`; string values are run through
    :func:`redact_text`. Non-strings (ints, bools, None, floats) pass through
    unchanged. Never raises on malformed input.
    """
    try:
        return _redact(value)
    except Exception:  # sanitizing must never raise; fall back to a safe marker
        return REDACTED


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if _is_sensitive_key(k) and v not in (None, ""):
                out[k] = REDACTED
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, (list, tuple)):
        redacted = [_redact(v) for v in value]
        return type(value)(redacted) if isinstance(value, tuple) else redacted
    return value


def redact_exception(exc: BaseException) -> BaseException:
    """A same-type copy of ``exc`` with its message sanitized (SEC-001).

    Preserves the exception class (so classification/``except`` logic is
    unchanged) and nonsensitive diagnostics such as ``HTTP 401``; removes
    credential-like content. Returns the original object unchanged when its
    message is already clean.
    """
    try:
        original = str(exc)
        safe = redact_text(original)
        if safe == original:
            return exc
        try:
            new = type(exc)(safe)
        except Exception:
            new = RuntimeError(safe)
        return new
    except Exception:
        return exc
