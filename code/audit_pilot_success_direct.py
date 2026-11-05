#!/usr/bin/env python3
"""Independent source-subsequence audit for Part A v2 strong-model pilot.

All candidate messages must be the exact ordered subsequence of their v2 record,
with every omission accounted for in the reversible gzip sidecar. This verifies
historical trace consistency, NOT independent correctness of repairs.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from compress_swe_failure_repair_conservative import actions, tool_map

TEST = re.compile(r"(?i)\b(?:pytest|unittest|tox|nox|mypy|pyright|ruff|flake8|eslint|npm\s+test|pnpm\s+test|cargo\s+test|go\s+test|git\s+diff\s+--check)\b")
FAIL = re.compile(r"(?im)(?:^|\n)\s*(?:OBSERVATION:\s*)?(?:Error:|FAILED\b|Traceback \(most recent call last\))|\[exit code: [1-9]\d*\]")
PASS = re.compile(r"(?i)\b\d+\s+passed\b|\bOK\s*\(tests?=\d+\)|\btests?\s+passed\b|\btest result:\s+ok\b|\bbuild succeeded\b|\bAll checks passed\b")
MUTATE = re.compile(r"(?i)(?:\b(?:sed|perl)\s+-i\b|\b(?:apply_patch|git\s+apply|mv|cp|rm|mkdir|touch|tee)\b|>>|(?<![<>])>(?![=>])|write_text|\.write\()")


def hash_json(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def source_records(root, selection):
    grouped = defaultdict(dict)
    for item in selection:
        grouped[item["split"]][item["record_id"]] = item
    found = {}
    for split, wanted in grouped.items():
        with (root / "parts" / "part_A" / "focused_v2" / split).open(encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, 1):
                row = json.loads(raw)
                if row["id"] in wanted:
                    if wanted[row["id"]]["line"] != line_no:
                        raise ValueError(f"line mismatch {row['id']}")
                    found[row["id"]] = row
    if len(found) != len(selection):
        raise ValueError("selected source records missing")
    return found


def verify(root, pilot):
    selection = [json.loads(x) for x in (pilot / "selection.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(selection) != 50 or any(item["part"] != "part_A" for item in selection):
        raise ValueError("selection must contain 50 Part A cases")
    sources = source_records(root, selection)
    decisions = [json.loads(x) for x in (pilot / "model_decisions.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    latest = {}
    for item in decisions:
        latest[item["record_id"]] = item
    candidates = {}
    with (pilot / "candidate_records.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if item["part"] != "part_A" or item["record"]["id"] in candidates:
                raise ValueError("candidate not unique or not Part A")
            candidates[item["record"]["id"]] = item["record"]
    deleted = defaultdict(list)
    with gzip.open(pilot / "removed_v3_actions.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if item["part"] != "part_A":
                raise ValueError("removed action outside Part A")
            deleted[item["record_id"]].append(item)
    errors, stats = [], Counter()
    for item in selection:
        rid = item["record_id"]
        decision = latest.get(rid)
        source = sources[rid]
        candidate = candidates.get(rid)
        if decision is None or candidate is None:
            errors.append((rid, "missing_latest_decision_or_candidate"))
            continue
        if decision["status"] == "model_or_audit_error":
            errors.append((rid, "latest_decision_error"))
            continue
        if decision.get("source_sha256") != hash_json(source) or decision.get("candidate_sha256") != hash_json(candidate):
            errors.append((rid, "record_hash_mismatch"))
        source_msgs = source["messages"]
        original_actions = actions(source_msgs)
        drop = set()
        seen_removed = set()
        for removal in deleted.get(rid, []):
            idx = removal["action_index"]
            if idx in seen_removed:
                errors.append((rid, "duplicate_removed_index"))
            seen_removed.add(idx)
            if not isinstance(idx, int) or not 0 <= idx < len(original_actions):
                errors.append((rid, "invalid_removed_index"))
                continue
            unit = original_actions[idx]
            chunk = source_msgs[unit["start"]:unit["end"]]
            if unit["start"] != removal["start"] or unit["end"] != removal["end"] or chunk != removal["messages"] or hash_json(chunk) != removal["sha256"]:
                errors.append((rid, "removed_chunk_does_not_match_source"))
            if unit["protected"] or not unit["complete"] or len(unit["calls"]) != 1:
                errors.append((rid, "protected_or_incomplete_removed"))
            else:
                name, args = unit["calls"][0]
                reply = "\n".join(str(msg.get("content") or "") for msg in source_msgs[unit["start"] + 1:unit["end"]])
                command = str(args.get("command") or "")
                if name not in ("Read", "Bash") or (name == "Bash" and (MUTATE.search(command) or TEST.search(command) or not re.match(r"^\s*(?:cd\s+[^;&|]+\s*&&\s*)?(?:grep|rg|find|ls|head|tail|wc|cat|git\s+(?:status|log|ls-files))\b", command, re.I))) or FAIL.search(reply):
                    errors.append((rid, "removed_non_navigation_or_failure"))
            drop.update(range(unit["start"], unit["end"]))
        expected = [msg for index, msg in enumerate(source_msgs) if index not in drop]
        if candidate["messages"] != expected or {k:v for k,v in candidate.items() if k!="messages"} != {k:v for k,v in source.items() if k!="messages"}:
            errors.append((rid, "candidate_not_exact_source_subsequence"))
        if sorted(decision["removed_action_indices"]) != sorted(item["action_index"] for item in deleted.get(rid, [])):
            errors.append((rid, "decision_sidecar_mismatch"))
        try:
            source_calls, source_obs = tool_map(source_msgs)
            candidate_calls, candidate_obs = tool_map(candidate["messages"])
            if any(source_calls.get(k) != v for k,v in candidate_calls.items()) or any(source_obs.get(k) != v for k,v in candidate_obs.items()):
                errors.append((rid, "retained_tool_changed"))
        except Exception as exc:
            errors.append((rid, "broken_tool_link", type(exc).__name__))
        ca = actions(candidate["messages"])
        if [source_msgs[u["start"]:u["end"]] for u in original_actions if u["protected"]] != [candidate["messages"][u["start"]:u["end"]] for u in ca if u["protected"]]:
            errors.append((rid, "protected_action_changed"))
        if not any(u["failure"] for u in ca) or not any(any(name in ("Edit", "Write") for name,_ in u["calls"]) for u in ca):
            errors.append((rid, "failed_or_edit_chain_missing"))
        # This is a *signal* only, not a replayed claim of success.
        edit_positions = [i for i,u in enumerate(ca) if any(name in ("Edit", "Write") for name,_ in u["calls"])]
        passing = []
        for index,u in enumerate(ca):
            cmd = "\n".join(str(arg.get("command") or "") for name,arg in u["calls"] if name=="Bash")
            text = "\n".join(str(m.get("content") or "") for m in candidate["messages"][u["start"]+1:u["end"]])
            if edit_positions and index > edit_positions[-1] and TEST.search(cmd) and PASS.search(text) and not FAIL.search(text):
                passing.append(index)
        if not passing:
            errors.append((rid, "passing_test_signal_missing_after_last_edit"))
        stats.update(records=1, removed_actions=len(deleted.get(rid, [])), unchanged=int(not deleted.get(rid)), actions_before=len(original_actions), actions_after=len(ca), messages_before=len(source_msgs), messages_after=len(candidate["messages"]))
    if len(latest) != len(selection) or len(candidates) != len(selection):
        errors.append(("all", "candidate_or_decision_record_count_mismatch", len(latest), len(candidates)))
    result = {"status": "structural_audit_passed_pending_human_review" if not errors else "structural_audit_failed", "selected": len(selection), "latest_decisions": len(latest), "candidates": len(candidates), "stats": dict(stats), "errors": len(errors), "examples": errors[:25], "limits": "Trace-level evidence preserved. Pass regex is not independent proof of a successful code repair. Repository replay not available; all changed cases require human causal-review before training."}
    (pilot / "independent_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--pilot", type=Path)
    arg = parser.parse_args()
    verify(arg.root, arg.pilot or arg.root / "parts" / "part_A" / "review_v3_pilot")
