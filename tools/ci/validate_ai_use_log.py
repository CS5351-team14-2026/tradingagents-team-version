"""Validate the structure of docs/ai-use-log.yaml.

Companion to course blocking gate 6 (project.pdf p10): every AI-use log entry
must parse and carry the minimal identification fields so the log stays
machine-checkable and current. The update requirement itself (a PR that
touches src/ or prompts/ must also touch the log) is enforced in ci.yml.
"""

import sys
from pathlib import Path

import yaml

REQUIRED_FIELDS = ("id", "date", "task")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_ai_use_log.py <ai-use-log.yaml>", file=sys.stderr)
        return 2

    path = Path(argv[1])
    if not path.is_file():
        print(f"::error::{path}: AI-use log does not exist (deliverable D1, gate 6)")
        return 1

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        print(f"::error::{path}: must contain a non-empty 'entries' list")
        return 1

    failures: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"entries[{index}]"
        if not isinstance(entry, dict):
            failures.append(f"{label}: entry is not a mapping")
            continue
        for field in REQUIRED_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                failures.append(f"{label}: missing or empty required field '{field}'")
        entry_id = str(entry.get("id", ""))
        if entry_id in seen:
            failures.append(f"{label}: duplicate entry id '{entry_id}'")
        seen.add(entry_id)

    if failures:
        for failure in failures:
            print(f"::error::{path}: {failure}")
        print(f"AI-use log gate FAILED: {len(failures)} problem(s)")
        return 1

    print(f"AI-use log gate PASSED: {path} has {len(entries)} well-formed entries")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
