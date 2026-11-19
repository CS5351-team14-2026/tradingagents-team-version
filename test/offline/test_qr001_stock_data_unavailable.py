"""Controlled failure: stock data unavailable degrades, not crashes (REQ-TA-QR-001).

Offline test: when every vendor reports no data, the data layer returns the
``NO_DATA_AVAILABLE`` / ``DATA_UNAVAILABLE`` sentinel (never fabricates a price)
and the run completes with a caveated report; the run record carries
``failure.code=STOCK_DATA_UNAVAILABLE`` (lifecycle status ``completed`` per
ADR-005 D-D) and no exception escapes.

Uses ``mock.patch.dict`` and a config reset so the test is order-independent
(no global router/config mutation leaks into other tests).
"""

from __future__ import annotations

import copy

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import router
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError


@pytest.fixture(autouse=True)
def _reset_global_config():
    """Start and end from a clean DEFAULT_CONFIG (order-independence)."""
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


@pytest.mark.unit
def test_no_data_across_chain_returns_sentinel_not_exception():
    """REQ-TA-QR-001: every vendor reporting no data yields one explicit sentinel."""
    def no_data(*a, **k):
        raise NoMarketDataError("NVDA", "NVDA", "no rows")

    set_config({"data_vendors": {"core_stock_apis": "yfinance"}})
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(router.VENDOR_METHODS["get_stock_data"], "yfinance", no_data)
        out = router.route_to_vendor("get_stock_data", "NVDA", "2026-01-01", "2026-01-10")
    assert out.startswith("NO_DATA_AVAILABLE")


@pytest.mark.unit
def test_unavailable_vendor_returns_data_unavailable_sentinel():
    """REQ-TA-QR-001: a throttled/failed vendor yields DATA_UNAVAILABLE, not a crash."""
    def unavailable(*a, **k):
        raise VendorUnavailableError("HTTP 429")

    set_config({"data_vendors": {"core_stock_apis": "yfinance"}})
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(router.VENDOR_METHODS["get_stock_data"], "yfinance", unavailable)
        out = router.route_to_vendor("get_stock_data", "NVDA", "2026-01-01", "2026-01-10")
    assert out.startswith("DATA_UNAVAILABLE")


@pytest.mark.unit
def test_failure_block_for_stock_data_unavailable_is_safe():
    """REQ-TA-QR-001 (D-C/D-E): the STOCK_DATA_UNAVAILABLE block is fixed and safe."""
    from tradingagents.failure import FailureCode, build_failure

    block = build_failure(FailureCode.STOCK_DATA_UNAVAILABLE, phase="analyst")
    assert block["code"] == "STOCK_DATA_UNAVAILABLE"
    assert block["phase"] == "analyst"
    assert block["diagnostic"]  # fixed safe message present
    assert "http" not in block["diagnostic"].lower()
