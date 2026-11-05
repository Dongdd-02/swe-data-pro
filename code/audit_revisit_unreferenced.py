#!/usr/bin/env python3
"""Audit third-pass Part A candidates for exact source preservation."""
from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

from compress_swe_failure_repair_conservative import actions, tool_map
from pilot_revisit_unreferenced import digest, load_jsonl, previous_targets, read_source, safe_candidate


def audit(out):
    targets = previous_targets()
    selected = load_jsonl(out / "selection.jsonl")
    expected_pairs = {(item["record_id"], item["action_index"]) for item in targets}
    errors = []
    if len(targets) != 16 or selected != targets or len(expected_pairs) != 16:
        errors.append(("selection", "not_exact_16_previous_unreferenced_actions"))
    if any(item.get("part") != "part_A" for item in selected):
        errors.append(("selection", "part_B_present"))
    decisions = {}
    for item in load_jsonl(out / "model_decisions.jsonl"):
        if item["record_id"] in decisions:
            errors.append((item["record_id"], "duplicate_decision"))
        decisions[item["record_id"]] = item
    candidates = {}
    for item in load_jsonl(out / "candidate_records.jsonl"):
        rid = item["record"]["id"]
        if item.get("part") != "part_A" or rid in candidates:
            errors.append((rid, "duplicate_or_not_part_A_candidate"))
        candidates[rid] = item["record"]
    removals = defaultdict(list)
    with gzip.open(out / "removed_unreferenced_actions.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                removals[item["record_id"]].append(item)
    grouped = defaultdict(list)
    for item in targets:
        grouped[item["record_id"]].append(item)
    expected_ids = set(grouped)
    if set(decisions) != expected_ids or set(candidates) != expected_ids or set(removals) - expected_ids:
        errors.append(("all", "record_set_mismatch"))
    stats = Counter()
    for rid, items in grouped.items():
        decision = decisions.get(rid)
        candidate = candidates.get(rid)
        if decision is None or candidate is None:
            continue
        source = read_source(items[0])
        units = actions(source["messages"])
        allowed = {item["action_index"] for item in items}
        stats["records"] += 1
        stats["actions_before"] += len(units)
        stats["messages_before"] += len(source["messages"])
        if decision.get("status") not in ("unchanged", "candidate_pending_human_review"):
            errors.append((rid, "unsuccessful_model_review"))
            continue
        if decision.get("source_sha256") != digest(source) or decision.get("candidate_sha256") != digest(candidate):
            errors.append((rid, "record_hash_mismatch"))
        if sorted(decision.get("target_action_indices", [])) != sorted(allowed):
            errors.append((rid, "decision_targets_mismatch"))
        evaluations = decision.get("evaluations", [])
        if {item.get("action_index") for item in evaluations} != allowed or len(evaluations) != len(allowed):
            errors.append((rid, "missing_or_duplicate_model_evaluation"))
        accepted = decision.get("accepted_action_indices", [])
        dropped = removals.get(rid, [])
        if sorted(accepted) != sorted(item["action_index"] for item in dropped) or any((rid, index) not in expected_pairs for index in accepted):
            errors.append((rid, "decision_sidecar_mismatch"))
        if bool(accepted) != (decision.get("status") == "candidate_pending_human_review"):
            errors.append((rid, "status_mismatch"))
        evaluations_by_index = {item.get("action_index"): item for item in evaluations}
        removed_messages = set()
        for removal in dropped:
            index = removal["action_index"]
            if index not in allowed or not 0 <= index < len(units):
                errors.append((rid, "removed_index_not_allowed"))
                continue
            unit = units[index]
            chunk = source["messages"][unit["start"]:unit["end"]]
            if removal.get("part") != "part_A" or removal["start"] != unit["start"] or removal["end"] != unit["end"] or removal["messages"] != chunk or removal["sha256"] != digest(chunk):
                errors.append((rid, "sidecar_not_exact_source_chunk"))
            evaluation = evaluations_by_index.get(index, {})
            okay, reason = safe_candidate(source["messages"], unit, evaluation)
            if not okay:
                errors.append((rid, "unsafe_action_deleted", reason))
            if evaluation.get("decision") != "drop" or evaluation.get("narrative_complete") is not True or evaluation.get("unique_evidence") is not False or evaluation.get("confidence") != "high":
                errors.append((rid, "model_did_not_confirm_semantic_deletion"))
            removed_messages.update(range(unit["start"], unit["end"]))
        expected_candidate = {**source, "messages": [message for index, message in enumerate(source["messages"]) if index not in removed_messages]}
        if candidate != expected_candidate:
            errors.append((rid, "candidate_not_exact_source_subsequence"))
        try:
            source_calls, source_observations = tool_map(source["messages"])
            candidate_calls, candidate_observations = tool_map(candidate["messages"])
            if any(source_calls.get(key) != value for key, value in candidate_calls.items()) or any(source_observations.get(key) != value for key, value in candidate_observations.items()):
                errors.append((rid, "retained_tool_call_or_observation_changed"))
        except Exception as exc:
            errors.append((rid, "tool_link_invalid", type(exc).__name__))
        if [m for m in source["messages"] if m["role"] in ("system", "user")] != [m for m in candidate["messages"] if m["role"] in ("system", "user")]:
            errors.append((rid, "system_or_user_changed"))
        stats["removed_actions"] += len(dropped)
        stats["changed_records"] += bool(dropped)
        stats["actions_after"] += len(actions(candidate["messages"]))
        stats["messages_after"] += len(candidate["messages"])
    result = {"status": "structural_audit_passed_pending_human_review" if not errors else "structural_audit_failed", "selected_actions": len(targets), "selected_records": len(grouped), "decisions": len(decisions), "candidates": len(candidates), "stats": dict(stats), "error_count": len(errors), "examples": errors[:25], "limits": "Semantic no-reference and narrative-completeness judgments come from a strong model, not independent repository replay. Changed candidates require human review; no correctness or success certification."}
    (out / "independent_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "parts" / "part_A" / "review_v3_unreferenced_revisit")
    args = parser.parse_args()
    audit(args.out)
