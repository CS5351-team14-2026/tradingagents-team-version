"""REQ-TA-FR-004 / FR-007: real client binding versus the JSON endpoint contract.

ADR-003; human-approved minimal fix on 2026-11-21 after the formal trial's HTTP400.
All HTTP is replaced; no real credentials or network requests are used.
"""

import json

import httpx
import pytest

from tradingagents.agents.managers.portfolio_manager import _invoke_json_mode
from tradingagents.llm_clients.openai_client import OpenAIClient


@pytest.mark.parametrize("nonfinite", [False, True])
def test_json_retry_obeys_endpoint_contract_and_preserves_strict_decode(nonfinite, monkeypatch):
    """REQ-TA-FR-004: instruct JSON explicitly, retain the schema and reject NaN."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-only")
    seen = []
    responses = []

    def handler(request):
        payload = json.loads(request.content)
        prompt = "\n".join(str(m.get("content", "")) for m in payload["messages"])
        seen.append(payload)
        # The endpoint's keyword precondition is independent of our schema checks.
        if "json" not in prompt.lower():
            responses.append(400)
            return httpx.Response(400, json={"error": {
                "message": "JSON mode requires a JSON instruction in the prompt",
                "type": "invalid_request_error",
            }})
        responses.append(200)
        body = json.dumps({
            "rating": "Hold", "confidence": "medium", "executive_summary": "Wait.",
            "investment_thesis": "Mixed evidence.", "supporting_factors": [],
            "opposing_factors": [], "entry_price": None, "stop_loss": None,
        })
        if nonfinite:
            body = body.replace('"entry_price": null', '"entry_price": NaN')
        return httpx.Response(200, json={
            "id": "chatcmpl-fixture", "object": "chat.completion", "created": 0,
            "model": "deepseek-flash", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": body}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = OpenAIClient(
            "deepseek-flash", base_url="https://example.invalid", provider="deepseek",
            api_key="fixture-only", max_retries=0, http_client=client,  # pragma: allowlist secret -- MockTransport fixture, not a credential
        ).get_llm()
        result = _invoke_json_mode(model, "Weigh these reports and deliver the final decision.")

    assert len(seen) == 1 and responses == [200]
    assert seen[0]["response_format"] == {"type": "json_object"}
    prompt = "\n".join(str(m.get("content", "")) for m in seen[0]["messages"])
    assert "supporting_factors" in prompt and "entry_price" in prompt
    assert "Weigh these reports" in prompt
    if nonfinite:
        assert result is None
    else:
        assert result is not None
        assert result[0].rating.value == "Hold"
