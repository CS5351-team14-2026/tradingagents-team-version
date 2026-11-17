"""CLI adapter for shared usage accounting (ADR-003; REQ-TA-FR-002; QR-004)."""

from tradingagents.llm_clients.usage import UsageCallbackHandler


class StatsCallbackHandler(UsageCallbackHandler):
    """Preserve the CLI handler name while the shared run ledger owns accounting."""
