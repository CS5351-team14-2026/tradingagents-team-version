"""Unit tests for the seeded-order pytest plugin (REQ-TA-QR-005, QR005-04).

These cover the plugin's reordering contract only. The full isolated
acceptance — running the whole default suite under default order, seed 42 and
seed 5351 in a network-isolated environment and comparing selected sets and
execution order — is a CI/container stage, not this offline unit test.
"""

from types import SimpleNamespace

import pytest

from tools.ci import pytest_seeded_order


def _items(count: int = 60) -> list:
    """Stand-in collected items with distinct, sortable node IDs."""
    return [SimpleNamespace(nodeid=f"test/offline/test_x.py::case_{i:03d}") for i in range(count)]


def _order(items: list) -> list:
    return [item.nodeid for item in items]


def test_reorder_keeps_the_selected_set_unchanged():
    """QR005-04: shuffling reorders the items but selects exactly the same ones."""
    items = _items()
    shuffled = pytest_seeded_order.reorder(list(items), 42)

    assert len(shuffled) == len(items)
    assert set(_order(shuffled)) == set(_order(items))


def test_reorder_is_independent_of_collection_order():
    """QR005-04: the seeded order depends on the selected set and seed, not on
    the order pytest happened to collect the items in."""
    items = _items()
    forward = pytest_seeded_order.reorder(list(items), 42)
    backward = pytest_seeded_order.reorder(list(reversed(items)), 42)

    assert _order(forward) == _order(backward)


def test_the_same_seed_reproduces_the_same_order():
    """QR005-04: repeating a seed reproduces its order for the same inputs."""
    items = _items()
    first = pytest_seeded_order.reorder(list(items), 5351)
    second = pytest_seeded_order.reorder(list(items), 5351)

    assert _order(first) == _order(second)


@pytest.mark.parametrize("seed", [42, 5351])
def test_a_shuffled_order_differs_from_collection_order(seed):
    """QR005-04: at least the sampled seeds reorder rather than echo collection
    order; a plugin that did nothing would not prove order-independence."""
    items = _items()
    default_order = _order(sorted(items, key=lambda item: item.nodeid))
    shuffled = _order(pytest_seeded_order.reorder(list(items), seed))

    assert shuffled != default_order


def test_different_seeds_give_different_orders():
    """QR005-04: the two required seeds (42, 5351) sample different orders of
    the same selected set."""
    items = _items()
    order_42 = _order(pytest_seeded_order.reorder(list(items), 42))
    order_5351 = _order(pytest_seeded_order.reorder(list(items), 5351))

    assert set(order_42) == set(order_5351)
    assert order_42 != order_5351


def test_the_plugin_is_a_noop_without_a_seed():
    """QR005-04: the ordinary regression run must be unchanged when the plugin is
    loaded but ``--order-seed`` is absent."""
    items = _items()
    collected = _order(items)
    config = SimpleNamespace(getoption=lambda name, default=None: None)

    pytest_seeded_order.pytest_collection_modifyitems(config, items)

    assert _order(items) == collected


def test_collection_modifyitems_applies_the_seed():
    """QR005-04: when a seed is given, the hook reorders items in place to the
    same order ``reorder`` produces."""
    items = _items()
    expected = _order(pytest_seeded_order.reorder(list(items), 42))
    config = SimpleNamespace(getoption=lambda name, default=None: 42)

    pytest_seeded_order.pytest_collection_modifyitems(config, items)

    assert _order(items) == expected


def test_addoption_registers_the_order_seed_flag():
    """QR005-04: the plugin advertises ``--order-seed`` so the CI commands from
    Issue #32 are accepted only when the plugin is loaded."""

    class _Parser:
        def __init__(self):
            self.options = []

        def addoption(self, *args, **kwargs):
            self.options.append((args, kwargs))

    parser = _Parser()
    pytest_seeded_order.pytest_addoption(parser)

    assert parser.options
    flags = [args for args, _ in parser.options]
    assert any(pytest_seeded_order._FLAG in flag for flag in flags)
