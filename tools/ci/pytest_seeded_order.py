"""Test-only pytest plugin that runs the selected tests in a seeded order.

REQ-TA-QR-005 (Issue #32, QR005-04). Loaded explicitly, never registered:

    python -m pytest -p tools.ci.pytest_seeded_order --order-seed 42

The plugin sorts the default-selected node IDs and shuffles them with a local
``random.Random(N)`` drawn from the same Python version, so:

- the *set* of selected items is unchanged (it runs after the default marker
  deselection and only reorders what was already chosen);
- a given seed reproduces its order for the same inputs and Python version;
- across seeds the selected set is identical but the order may differ.

Loading it without ``--order-seed`` is a no-op, so the ordinary regression
invocation stays the same when the flag is absent.
"""

import contextlib
import random

_FLAG = "--order-seed"


def reorder(items: list, seed: int) -> list:
    """Return ``items`` shuffled deterministically for ``seed``.

    The input is first sorted by node ID so the result depends only on the
    selected set and the seed, not on the order pytest collected them in.
    """
    ordered = sorted(items, key=lambda item: item.nodeid)
    random.Random(seed).shuffle(ordered)
    return ordered


def pytest_addoption(parser):
    """Register ``--order-seed`` only when the plugin is loaded explicitly."""
    # A second load (-p twice) re-registers the same option; the ValueError is
    # harmless and ``pytest_collection_modifyitems`` still runs.
    with contextlib.suppress(ValueError):
        parser.addoption(
            _FLAG,
            action="store",
            type=int,
            default=None,
            metavar="N",
            help="run the selected tests in the order shuffled with this seed (QR005-04)",
        )


def pytest_collection_modifyitems(config, items):
    """Reorder ``items`` in place; the selected set never changes.

    Called after the default ``not integration`` deselection has already
    dropped items, so whatever remains is exactly the default selection.
    """
    seed = config.getoption(_FLAG, default=None)
    if seed is None:
        return
    items[:] = reorder(items, int(seed))
