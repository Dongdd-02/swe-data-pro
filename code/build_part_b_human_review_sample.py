#!/usr/bin/env python3
"""Build a deterministic, stratified human-review sample for Part B deletions."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path


SEED = "part-b-full-unreferenced-review-v1"


def load_jsonl(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def message_text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in content)
    return str(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--fraction", type=float, default=0.05)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if not 0 < args.fraction <= 1:
        parser.error("--fraction must be in (0, 1]")

    out = args.root / "parts" / "part_B" / "full_unreferenced_revisit"
    output = args.output or out / "human_review_sample.csv"
    decisions = {item["record_id"]: item for item in load_jsonl(out / "model_decisions.jsonl")}
    removed = defaultdict(list)
    with gzip.open(out / "removed_unreferenced_actions.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                removed[item["record_id"]].append(item)

    by_split = defaultdict(list)
    for record_id, items in removed.items():
        by_split[items[0]["split"]].append(record_id)
    chosen = set()
    sample_counts = {}
    for split, ids in by_split.items():
        ids.sort(key=lambda rid: hashlib.sha256(f"{SEED}\0{split}\0{rid}".encode("utf-8")).hexdigest())
        count = min(len(ids), max(1, math.ceil(len(ids) * args.fraction)))
        chosen.update(ids[:count])
        sample_counts[split] = count

    columns = [
        "split", "record_id", "action_index", "message_start", "message_end",
        "tool_name", "tool_arguments", "assistant_call_excerpt", "tool_reply_excerpt",
        "model_reason", "model_confidence", "human_verdict", "restore_action", "review_notes",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record_id in sorted(chosen, key=lambda rid: (decisions[rid]["split"], rid)):
            decision = decisions[record_id]
            evals = {item["action_index"]: item for item in decision.get("evaluations", [])}
            for item in sorted(removed[record_id], key=lambda x: x["action_index"]):
                messages = item["messages"]
                assistant = next((m for m in messages if m.get("role") == "assistant"), {})
                observation = next((m for m in messages if m.get("role") == "tool"), {})
                call = next(iter(assistant.get("tool_calls", [])), {})
                function = call.get("function", {})
                evaluation = evals.get(item["action_index"], {})
                writer.writerow({
                    "split": item["split"],
                    "record_id": record_id,
                    "action_index": item["action_index"],
                    "message_start": item["start"],
                    "message_end": item["end"],
                    "tool_name": function.get("name", ""),
                    "tool_arguments": json.dumps(function.get("arguments", {}), ensure_ascii=False),
                    "assistant_call_excerpt": message_text(assistant)[:1200],
                    "tool_reply_excerpt": message_text(observation)[:2400],
                    "model_reason": evaluation.get("reason", ""),
                    "model_confidence": evaluation.get("confidence", ""),
                    "human_verdict": "pending",
                    "restore_action": "",
                    "review_notes": "",
                })
                row_count += 1
    print(json.dumps({"output": str(output), "seed": SEED, "fraction": args.fraction, "sampled_records_by_split": sample_counts, "sampled_records": len(chosen), "sampled_removed_actions": row_count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
