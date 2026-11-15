"""Validate requirements registry YAML files against docs/req/req-schema.json.

Course blocking gate 3 (project.pdf p10). Usage:

    python tools/ci/validate_req_registry.py docs/req/req-schema.json FILE [FILE ...]

Every listed file that exists must pass the schema. IDs must also be unique
within each file (the schema cannot express cross-item uniqueness).
"""

import json
import sys
from pathlib import Path

import jsonschema
import yaml


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "usage: validate_req_registry.py <schema.json> <registry.yaml> [...]",
            file=sys.stderr,
        )
        return 2

    schema_path = Path(argv[1])
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    failures: list[str] = []
    for raw in argv[2:]:
        path = Path(raw)
        if not path.is_file():
            failures.append(f"{path}: file listed for validation does not exist")
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
            location = "/".join(str(part) for part in error.path) or "<root>"
            failures.append(f"{path}: schema violation at {location}: {error.message}")

        entries = (data or {}).get("requirements") or []
        seen: dict[str, int] = {}
        for entry in entries:
            entry_id = entry.get("id", "<missing id>")
            seen[entry_id] = seen.get(entry_id, 0) + 1
        for entry_id, count in seen.items():
            if count > 1:
                failures.append(f"{path}: duplicate requirement id {entry_id} ({count}x)")

    if failures:
        for failure in failures:
            print(f"::error::{failure}")
        print(f"schema gate FAILED: {len(failures)} problem(s)")
        return 1

    checked = ", ".join(argv[2:])
    print(f"schema gate PASSED: {checked} valid against {schema_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
