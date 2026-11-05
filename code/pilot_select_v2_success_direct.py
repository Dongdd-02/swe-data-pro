#!/usr/bin/env python3
"""Inspect v2 long-trace candidates for a 50-case evidence-preserving pilot."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compress_swe_failure_repair_conservative import actions

ROOT = Path(__file__).resolve().parent.parent
SPLITS = ("train.jsonl", "validation.jsonl", "test.jsonl")
PART = "part_A"
TEST = re.compile(r"(?i)\b(?:pytest|unittest|tox|nox|mypy|pyright|ruff|flake8|eslint|npm\s+test|pnpm\s+test|cargo\s+test|go\s+test|git\s+diff\s+--check)\b")
FAIL = re.compile(r"(?im)(?:^|\n)\s*(?:OBSERVATION:\s*)?(?:Error:|FAILED\b|Traceback \(most recent call last\))|\[exit code: [1-9]\d*\]")
PASS = re.compile(r"(?i)\b\d+\s+passed\b|\bOK\s*\(tests?=\d+\)|\btests?\s+passed\b|\btest result:\s+ok\b|\bbuild succeeded\b|\bAll checks passed\b")


def collect(rows_per_part: int, min_actions: int, max_chars: int):
    all_rows = []
    part = PART
    for split in SPLITS:
        with (ROOT / "parts" / part / "focused_v2" / split).open(encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, 1):
                row = json.loads(raw)
                messages = row["messages"]
                units = actions(messages)
                failing = [i for i, u in enumerate(units) if u["failure"]]
                edits = [i for i, u in enumerate(units) if any(name in ("Edit", "Write") for name, _ in u["calls"])]
                success = []
                for i, u in enumerate(units):
                    command = "\n".join(str(arg.get("command") or "") for name, arg in u["calls"] if name == "Bash")
                    reply = "\n".join(str(m.get("content") or "") for m in messages[u["start"] + 1:u["end"]])
                    if TEST.search(command) and PASS.search(reply) and not FAIL.search(reply):
                        success.append(i)
                after_edit = [i for i in success if edits and i > edits[-1]]
                text_chars = sum(len(str(m.get("content") or "")) for m in messages)
                if not failing or not edits or not after_edit or len(units) < min_actions:
                    continue
                if max_chars and text_chars > max_chars:
                    continue
                all_rows.append({"part": part, "split": split, "line": line_no, "record_id": row["id"], "actions": len(units), "messages": len(messages), "chars": text_chars, "failure_indices": failing[:10], "edit_indices": edits, "success_indices": after_edit[:10], "first_failure": failing[0], "last_edit": edits[-1], "last_success": after_edit[-1]})
    selected = sorted(all_rows, key=lambda r: (-r["actions"], r["chars"], r["record_id"]))[:rows_per_part]
    return selected, {"eligible_records": len(all_rows), "selected": len(selected), "selected_part": PART}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-part", type=int, default=25)
    parser.add_argument("--min-actions", type=int, default=35)
    parser.add_argument("--max-chars", type=int, default=160000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    selected, report = collect(args.per_part, args.min_actions, args.max_chars)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in selected:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps(report, ensure_ascii=False))
