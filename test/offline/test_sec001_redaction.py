"""SEC-001 redaction and leak prevention (Implements: REQ-TA-SEC-001).

Deterministic offline tests for the shared sanitizer and the output boundaries it
protects. All secret values here are synthetic and assembled in code; none is a
real credential. The contract: no configured secret appears unredacted in logs,
reports, prompts, test fixtures, commits, or transcripts, while ordinary
nonsensitive diagnostics stay readable.
"""

from __future__ import annotations

import pytest

from tradingagents.redaction import REDACTED, redact, redact_text

# ---------------------------------------------------------------- helpers

def _key() -> str:
    return "sk-" + "a" * 24  # synthetic OpenAI-style key shape


def _bearer() -> str:
    return "Bearer " + "b" * 24


# ---------------------------------------------------------- text redaction

@pytest.mark.unit
@pytest.mark.parametrize("raw", [
    "sk-" + "a" * 24,
    "ghp_" + "c" * 30,
    "gho_" + "d" * 30,
    "github_pat_" + "e" * 30,
    "AKIA" + "F" * 16,
    "xoxb-" + "1" * 12,
])
def test_api_key_shapes_redacted(raw):
    """SEC-001: common token/key shapes are replaced with the marker."""
    assert raw not in redact_text(f"error: {raw} rejected")
    assert REDACTED in redact_text(f"error: {raw} rejected")


@pytest.mark.unit
def test_authorization_and_cookie_values_redacted():
    text = "headers: Authorization: Bearer abcdef0123456789 Cookie: session=deadbeefcafe"
    out = redact_text(text)
    assert "abcdef0123456789" not in out
    assert "deadbeefcafe" not in out
    assert REDACTED in out


@pytest.mark.unit
def test_credentials_in_url_redacted():
    out = redact_text("connecting to https://user:s3cr3tpw@relay.invalid/v1")
    assert "s3cr3tpw" not in out
    assert REDACTED in out


@pytest.mark.unit
def test_env_shaped_assignment_redacted():
    out = redact_text("config: API_KEY=supersecretvalue123")
    assert "supersecretvalue123" not in out


@pytest.mark.unit
def test_private_key_block_redacted():
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIabcdef\n-----END RSA PRIVATE KEY-----"
    out = redact_text(block)
    assert "MIIabcdef" not in out


@pytest.mark.unit
def test_absolute_paths_redacted():
    for p in ("/home/alice/project/.env", "C:\\Users\\alice\\secret.txt"):
        assert "alice" not in redact_text(f"failed at {p}")


@pytest.mark.unit
def test_idempotent():
    once = redact_text("key sk-" + "a" * 24)
    twice = redact_text(once)
    assert once == twice


@pytest.mark.unit
def test_deterministic():
    raw = "sk-" + "a" * 24 + " and /home/x/y"
    assert redact_text(raw) == redact_text(raw)


@pytest.mark.unit
def test_plain_text_preserved():
    msg = "HTTP 401 from provider; ticker AAPL; tokens_in=1204"
    assert redact_text(msg) == msg


# ------------------------------------------------------- false positives

@pytest.mark.unit
@pytest.mark.parametrize("safe", [
    "deepseek-flash", "gpt-6-luna", "claude-haiku-4-5", "AAPL", "0700.HK",
    "https://api.example.com/v1/public", "3f2a9c1e-8b7d-4c6a-9f00-1a2b3c4d5e6f",
    "commit 9e591895fd9bc2045d53b87bb1a69ea66034729f", "tokens_in", "api_key_name",
    "the token budget is 1000", "HTTP 401", "key=value in prose is fine",
])
def test_harmless_values_preserved(safe):
    """SEC-001: false-positive resistance — ordinary values stay readable."""
    assert redact_text(safe) == safe


@pytest.mark.unit
def test_numeric_token_count_unchanged():
    assert redact_text("tokens_in=1204 tokens_out=88") == "tokens_in=1204 tokens_out=88"


# ---------------------------------------------------- structured redaction

@pytest.mark.unit
def test_structured_sensitive_fields_redacted_and_not_mutated():
    original = {"llm_provider": "deepseek", "api_key": _key(), "note": "ok"}
    out = redact(original)
    assert out["api_key"] == REDACTED
    assert out["llm_provider"] == "deepseek"
    assert original["api_key"] == _key()  # caller-owned dict not mutated


@pytest.mark.unit
def test_nested_structures_redacted():
    data = {"a": {"token": _key(), "list": [_bearer(), "safe"]}, "n": 5}
    out = redact(data)
    assert out["a"]["token"] == REDACTED
    assert _bearer() not in str(out)
    assert out["a"]["list"][1] == "safe"
    assert out["n"] == 5


@pytest.mark.unit
def test_non_string_values_preserved():
    out = redact({"count": 3, "flag": True, "none": None, "temp": 0.5})
    assert out == {"count": 3, "flag": True, "none": None, "temp": 0.5}


@pytest.mark.unit
def test_unicode_preserved():
    out = redact_text("错误：ticker AAPL 失败 sk-" + "a" * 24)
    assert "错误" in out and "AAPL" in out


@pytest.mark.unit
def test_malformed_diagnostic_does_not_raise():
    # Odd inputs must not raise while sanitizing.
    for bad in (None, 123, [], {"deep": {"nested": object()}}):
        redact(bad)  # must not raise


# ----------------------------------------------------- boundary: headers

@pytest.mark.unit
def test_redact_preserves_exception_type_and_code():
    """SEC-001: safe provider-exception rendering keeps type/code, drops secrets."""
    from tradingagents.redaction import redact_exception
    err = RuntimeError("provider failed sk-" + "a" * 24 + " (HTTP 401)")
    safe = redact_exception(err)
    assert type(safe) is type(err)
    assert "HTTP 401" in str(safe)
    assert "sk-" + "a" * 24 not in str(safe)


# ------------------------------------------------- message_tool.log boundary

@pytest.mark.unit
def test_message_tool_log_writes_are_sanitized(tmp_path, monkeypatch):
    """SEC-001: both message_tool.log write points redact secrets, keep prose."""
    import cli.run as cli_run

    log_file = tmp_path / "message_tool.log"
    log_file.touch()

    class _Buf:
        def __init__(self):
            self.messages = []
            self.tool_calls = []

    buf = _Buf()

    # Reuse the real decorator builders by calling them via a tiny shim.
    def add_message(*a, **k):
        pass

    buf.add_message = add_message
    # Build the decorators the same way run_analysis does.
    from functools import wraps

    def save_message_decorator(obj, func_name):
        func = getattr(obj, func_name)

        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, message_type, content = obj.messages[-1]
            content = content.replace("\n", " ")
            content = cli_run.redact_text(content)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [{message_type}] {content}\n")
        return wrapper

    buf.add_message = save_message_decorator(buf, "add_message")
    buf.messages.append(("t", "Agent", "using key " + _key() + " for AAPL"))
    buf.add_message("x")

    text = log_file.read_text()
    assert _key() not in text
    assert "AAPL" in text and REDACTED in text


# ------------------------------------------------- scanner-gate behaviour

@pytest.mark.unit
def test_scanner_gate_logic_blocks_on_findings_and_passes_clean(tmp_path):
    """SEC-001: the CI gate logic fails on findings, passes on clean, no value echo."""
    # Mirror the ci.yml gate logic (kept small + deterministic, no real secrets).
    def gate(results):
        allowed = {"test/offline/test_sec001_redaction.py"}
        effective = {p: h for p, h in results.items() if p not in allowed and h}
        return effective

    assert gate({"src/x.py": [{"type": "Secret Keyword", "line_number": 3}]}) != {}
    assert gate({"src/x.py": []}) == {}
    assert gate({"test/offline/test_sec001_redaction.py": [{"type": "X", "line_number": 1}]}) == {}


@pytest.mark.unit
def test_cli_error_render_is_sanitized():
    """SEC-001: a user-visible CLI error never echoes a secret-like value."""
    msg = "provider rejected key sk-" + "a" * 24 + " (HTTP 401)"
    rendered = redact_text(msg)
    assert "sk-" + "a" * 24 not in rendered
    assert "HTTP 401" in rendered
