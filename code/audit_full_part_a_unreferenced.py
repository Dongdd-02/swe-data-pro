#!/usr/bin/env python3
"""Independent structural audit for a full collaboration-part pruning pass."""
from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

from compress_swe_failure_repair_conservative import actions, tool_map
from full_part_a_unreferenced import digest, load_jsonl, prefilter_targets, read_source_line, safe_candidate


def audit(root, out, part):
    source_records = []
    source_by_id = {}
    for split in ("train.jsonl", "validation.jsonl", "test.jsonl"):
        path = root / "parts" / part / "focused_v2" / split
        for line_no, raw in enumerate(path.open(encoding="utf-8"), 1):
            row = json.loads(raw)
            source_records.append({"record_id": row["id"], "split": split, "line": line_no, "row": row})
            source_by_id[row["id"]] = row
    errors = []
    selected = load_jsonl(out / "selection.jsonl")
    expected_selection = []
    expected_target_map = {}
    for item in source_records:
        indices = prefilter_targets(item["row"])
        expected_target_map[item["record_id"]] = indices
        for index in indices:
            expected_selection.append({"record_id": item["record_id"], "split": item["split"], "part": part, "line": item["line"], "action_index": index, "prefilter": "complete_read_or_static_bash_no_exact_later_reference"})
    if selected != expected_selection:
        errors.append(("selection", "prefilter_selection_mismatch"))
    if any(item.get("part") != part for item in selected):
        errors.append(("selection", "unexpected_part_present"))
    decisions = {}
    for item in load_jsonl(out / "model_decisions.jsonl"):
        rid = item.get("record_id")
        if rid in decisions:
            errors.append((rid, "duplicate_decision"))
        decisions[rid] = item
    candidates = {}
    for item in load_jsonl(out / "candidate_records.jsonl"):
        record = item.get("record", item)
        rid = record.get("id")
        if item.get("part") != part or rid in candidates:
            errors.append((rid, "duplicate_or_unexpected_part_candidate"))
        candidates[rid] = item
    removals = defaultdict(list)
    sidecar = out / "removed_unreferenced_actions.jsonl.gz"
    if sidecar.exists():
        with gzip.open(sidecar, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    item = json.loads(line)
                    removals[item["record_id"]].append(item)
    expected_ids = {item["record_id"] for item in source_records}
    if set(decisions) != expected_ids:
        errors.append(("all", "decision_record_set_mismatch"))
    if set(candidates) != expected_ids:
        errors.append(("all", "candidate_record_set_mismatch"))
    stats = Counter(records=len(source_records), target_actions=len(selected))
    for source in source_records:
        rid = source["record_id"]
        row = source["row"]
        decision = decisions.get(rid)
        wrapped = candidates.get(rid)
        candidate = wrapped.get("record", wrapped) if wrapped else None
        if decision is None or candidate is None:
            continue
        units = actions(row["messages"])
        target_indices = set(expected_target_map[rid])
        if decision.get("target_action_indices", []) != sorted(target_indices):
            errors.append((rid, "decision_targets_mismatch"))
        if decision.get("source_sha256") != digest(row) or decision.get("candidate_sha256") != digest(candidate):
            errors.append((rid, "record_hash_mismatch"))
        if decision.get("status") not in ("not_targeted", "unchanged", "candidate_pending_human_review", "model_or_audit_error"):
            errors.append((rid, "invalid_status"))
        evaluations = {item.get("action_index"): item for item in decision.get("evaluations", []) if isinstance(item, dict)}
        if decision.get("status") != "not_targeted" and set(evaluations) != target_indices:
            errors.append((rid, "missing_or_duplicate_evaluations"))
        accepted = decision.get("accepted_action_indices", [])
        if any(index not in target_indices for index in accepted):
            errors.append((rid, "accepted_action_outside_selection"))
        dropped = removals.get(rid, [])
        if sorted(accepted) != sorted(item["action_index"] for item in dropped):
            errors.append((rid, "decision_sidecar_mismatch"))
        removed_messages = set()
        for removal in dropped:
            index = removal["action_index"]
            if not 0 <= index < len(units):
                errors.append((rid, "removed_index_out_of_range")); continue
            unit = units[index]
            chunk = row["messages"][unit["start"]:unit["end"]]
            if removal.get("part") != part or removal.get("start") != unit["start"] or removal.get("end") != unit["end"] or removal.get("messages") != chunk or removal.get("sha256") != digest(chunk):
                errors.append((rid, "sidecar_not_exact_source_chunk"))
            okay, reason = safe_candidate(row["messages"], unit, evaluations.get(index, {}))
            if not okay:
                errors.append((rid, "unsafe_action_deleted", reason))
            evaluation = evaluations.get(index, {})
            if evaluation.get("decision") != "drop" or evaluation.get("narrative_complete") is not True or evaluation.get("unique_evidence") is not False or evaluation.get("command_failed") is not False or evaluation.get("confidence") != "high":
                errors.append((rid, "model_gate_fields_invalid"))
            removed_messages.update(range(unit["start"], unit["end"]))
        expected_candidate = {**row, "messages": [message for index, message in enumerate(row["messages"]) if index not in removed_messages]}
        if candidate != expected_candidate:
            errors.append((rid, "candidate_not_exact_source_subsequence"))
        try:
            source_calls, source_obs = tool_map(row["messages"])
            candidate_calls, candidate_obs = tool_map(candidate["messages"])
            if any(source_calls.get(key) != value for key, value in candidate_calls.items()) or any(source_obs.get(key) != value for key, value in candidate_obs.items()):
                errors.append((rid, "retained_tool_call_or_observation_changed"))
        except Exception as exc:
            errors.append((rid, "tool_link_invalid", type(exc).__name__))
        if [m for m in row["messages"] if m.get("role") in ("system", "user")] != [m for m in candidate["messages"] if m.get("role") in ("system", "user")]:
            errors.append((rid, "system_or_user_changed"))
        stats["actions_before"] += len(units)
        stats["actions_after"] += len(actions(candidate["messages"]))
        stats["messages_before"] += len(row["messages"])
        stats["messages_after"] += len(candidate["messages"])
        stats["removed_actions"] += len(dropped)
        stats["changed_records"] += bool(dropped)
    result = {"status": "structural_audit_passed_pending_human_review" if not errors else "structural_audit_failed", "source_records": len(source_records), "selected_actions": len(selected), "decisions": len(decisions), "candidates": len(candidates), "stats": dict(stats), "error_count": len(errors), "examples": errors[:30], "limits": "Semantic no-reference and narrative-completeness judgments come from a strong model, not independent repository replay. Changed candidates require human review; no correctness or success certification."}
    (out / "independent_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--part", choices=("part_A", "part_B"), default="part_A")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    output = args.out or (args.root / "parts" / args.part / "full_unreferenced_revisit")
    audit(args.root, output, args.part)
