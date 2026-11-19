"""Compare selected sets and execution orders across QR005-04 runs (Issue #32).

Reads the junitxml files produced by the isolated CI runs and checks:

- the default, seed 42 and seed 5351 runs selected the *same* set of tests;
- at least one seed's order differs from the default order;
- repeating seed 42 reproduces its order exactly.

Node IDs are reconstructed as ``classname::name`` (junitxml drops the file path
and keeps the dotted module, which is stable and unique per test). Exit 0 when
all checks hold; non-zero otherwise, with ``::error::`` lines for CI.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_XML = "offline-default.xml"
SEED_42_XML = "offline-seed-42.xml"
SEED_42_REPEAT_XML = "offline-seed-42-repeat.xml"
SEED_5351_XML = "offline-seed-5351.xml"


def _ordered_ids(xml_path: Path) -> list[str]:
    """Return test node IDs in execution order (junitxml keeps that order)."""
    root = ET.parse(xml_path).getroot()
    return [
        f"{case.get('classname', '')}::{case.get('name', '')}"
        for case in root.iter("testcase")
    ]


def compare(artifacts_dir: Path) -> int:
    runs = {
        "default": artifacts_dir / DEFAULT_XML,
        "seed-42": artifacts_dir / SEED_42_XML,
        "seed-42-repeat": artifacts_dir / SEED_42_REPEAT_XML,
        "seed-5351": artifacts_dir / SEED_5351_XML,
    }
    missing = [name for name, path in runs.items() if not path.is_file()]
    if missing:
        for name in missing:
            print(f"::error::missing junitxml for run '{name}' in {artifacts_dir}")
        return 1

    orders = {name: _ordered_ids(path) for name, path in runs.items()}
    for name, order in orders.items():
        print(f"QR005 run '{name}': {len(order)} tests")

    failures: list[str] = []

    default_set = set(orders["default"])
    for name in ("seed-42", "seed-42-repeat", "seed-5351"):
        other = set(orders[name])
        if other != default_set:
            only_default = sorted(default_set - other)[:5]
            only_other = sorted(other - default_set)[:5]
            failures.append(
                f"{name} selected a different set than default "
                f"(missing {len(default_set - other)}, extra {len(other - default_set)}; "
                f"e.g. only-default={only_default}, only-{name}={only_other})"
            )

    if orders["seed-42"] == orders["default"] and orders["seed-5351"] == orders["default"]:
        failures.append(
            "no seed reordered the run: both seeds matched the default order exactly"
        )

    if orders["seed-42"] != orders["seed-42-repeat"]:
        failures.append("seed 42 did not reproduce its order on the repeat run")

    if failures:
        for failure in failures:
            print(f"::error::QR005-04: {failure}")
        print(f"QR005-04 order comparison FAILED: {len(failures)} problem(s)")
        return 1

    print(
        "QR005-04 order comparison PASSED: identical selected sets, "
        "at least one seed reordered, seed 42 reproducible"
    )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: compare_orders.py <artifacts-dir>", file=sys.stderr)
        return 2
    return compare(Path(argv[1]))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
