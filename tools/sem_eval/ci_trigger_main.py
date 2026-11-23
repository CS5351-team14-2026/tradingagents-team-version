"""CI helper: read changed paths, print trigger verdict, write trigger.out.

Used by the Gate 4 workflow. No network, no model.
"""

from __future__ import annotations

import sys

from tools.sem_eval.triggers import is_semantic_eval_triggered


def main(argv: list[str]) -> int:
    paths_file = argv[1] if len(argv) > 1 else "changed.txt"
    out_file = argv[2] if len(argv) > 2 else "trigger.out"
    with open(paths_file, encoding="utf-8") as handle:
        paths = [line.strip() for line in handle if line.strip()]
    verdict, matched = is_semantic_eval_triggered(paths)
    print(f"trigger: {verdict}; matched={matched}")
    with open(out_file, "w", encoding="utf-8") as handle:
        handle.write(verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
