#!/usr/bin/env python3
"""Verify a two-part SWE collaboration package without external dependencies."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path

SPLITS = ("train.jsonl", "validation.jsonl", "test.jsonl")
PARTS = ("part_A", "part_B")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: Path):
    with path.open("rb") as handle:
        for line_no, raw in enumerate(handle, 1):
            if raw.strip():
                yield line_no, raw, json.loads(raw.decode("utf-8"))


def verify(root: Path) -> dict:
    assignments = {}
    with (root / "manifests" / "assignment.jsonl").open(encoding="utf-8") as handle:
        for raw in handle:
            item = json.loads(raw)
            key = item["split"], item["record_id"]
            if key in assignments:
                raise ValueError(f"duplicate assignment: {key}")
            assignments[key] = item
    counts = defaultdict(int)
    errors = []
    seen = set()
    for part in PARTS:
        for split in SPLITS:
            original = list(read(root / "parts" / part / "original" / split))
            focused = list(read(root / "parts" / part / "focused_v2" / split))
            if [obj["id"] for _, _, obj in original] != [obj["id"] for _, _, obj in focused]:
                errors.append((part, split, "original_focused_id_order_mismatch"))
            for line_no, raw, obj in original:
                key = split, obj["id"]
                if key in seen:
                    errors.append((key, "duplicate_part_record"))
                seen.add(key)
                item = assignments.get(key)
                if not item or item["part"] != part:
                    errors.append((key, "missing_or_wrong_assignment"))
                elif item["source_line_sha256"] != sha256(raw.rstrip(b"\r\n")):
                    errors.append((key, "original_line_hash_mismatch"))
                counts[part, split] += 1
            for _, _, obj in focused:
                key = split, obj["id"]
                if key not in assignments or assignments[key]["part"] != part:
                    errors.append((key, "focused_record_not_assigned"))
    expected = {(split, item["record_id"]) for (split, item) in assignments.items()}
    if seen != set(assignments):
        errors.append(("all", "assignment_coverage_mismatch", len(seen), len(assignments)))
    for part in PARTS:
        with gzip.open(root / "parts" / part / "focused_v2_metadata" / "removed_exploration.jsonl.gz", "rt", encoding="utf-8") as handle:
            for raw in handle:
                item = json.loads(raw)
                if assignments.get((item["split"], item["record_id"]), {}).get("part") != part:
                    errors.append((part, "sidecar_wrong_part"))
                    break
    result = {"status": "passed_collaboration_split_audit" if not errors else "failed", "records": len(assignments), "counts": {f"{part}/{split}": counts[part, split] for part in PARTS for split in SPLITS}, "errors": errors[:30], "error_count": len(errors)}
    (root / "manifests" / "collaboration_verify.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.root)
    print(json.dumps(result, ensure_ascii=False))
    if result["error_count"]:
        raise SystemExit(1)
