#!/usr/bin/env python3
"""Independently audit the exact-source Part A pre-failure revisit candidates."""
from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

from compress_swe_failure_repair_conservative import actions, tool_map
from pilot_revisit_pre_failure import build_targets, digest, load_jsonl, read_source, safe_no_result_navigation


def audit(out):
    targets = build_targets()
    selected = load_jsonl(out / "selection.jsonl")
    expected = {(x["record_id"], x["action_index"]) for x in targets}
    errors = []
    if len(targets) != 77 or selected != targets or len(expected) != 77:
        errors.append(("selection", "not_exact_77_original_rejections"))
    if any(item["part"] != "part_A" for item in selected):
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
    with gzip.open(out / "removed_pre_failure_actions.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                removals[item["record_id"]].append(item)
    expected_ids = {item["record_id"] for item in targets}
    if set(decisions) != expected_ids or set(candidates) != expected_ids or set(removals) - expected_ids:
        errors.append(("all", "record_set_mismatch"))
    grouped = defaultdict(list)
    for item in targets:
        grouped[item["record_id"]].append(item)
    summary = Counter()
    for rid, items in grouped.items():
        decision = decisions.get(rid)
        candidate = candidates.get(rid)
        if decision is None or candidate is None:
            continue
        source = read_source(items[0])
        units = actions(source["messages"])
        summary["records"] += 1
        summary["actions_before"] += len(units)
        summary["messages_before"] += len(source["messages"])
        if decision.get("status") not in ("unchanged", "candidate_pending_human_review"):
            errors.append((rid, "unsuccessful_model_review"))
            continue
        if decision.get("source_sha256") != digest(source) or decision.get("candidate_sha256") != digest(candidate):
            errors.append((rid, "record_hash_mismatch"))
        allowed = {item["action_index"] for item in items}
        if sorted(decision.get("target_action_indices", [])) != sorted(allowed):
            errors.append((rid, "decision_targets_mismatch"))
        evaluation = decision.get("evaluations", [])
        if {x.get("action_index") for x in evaluation} != allowed or len(evaluation) != len(allowed):
            errors.append((rid, "missing_or_duplicate_model_evaluation"))
        anchor = decision.get("semantic_failure_anchor")
        accepted = decision.get("accepted_action_indices", [])
        dropped = removals.get(rid, [])
        if len(accepted) != len(set(accepted)) or len(dropped) != len(set(x["action_index"] for x in dropped)):
            errors.append((rid, "duplicate_removed_action"))
        if sorted(accepted) != sorted(x["action_index"] for x in dropped) or any((rid, x) not in expected for x in accepted):
            errors.append((rid, "decision_sidecar_mismatch"))
        if bool(accepted) != (decision["status"] == "candidate_pending_human_review"):
            errors.append((rid, "status_mismatch"))
        removed_positions = set()
        for removal in dropped:
            index = removal["action_index"]
            if not isinstance(index, int) or index not in allowed or not 0 <= index < len(units):
                errors.append((rid, "removed_index_not_allowed"))
                continue
            unit = units[index]
            chunk = source["messages"][unit["start"]:unit["end"]]
            if removal.get("part") != "part_A" or removal["start"] != unit["start"] or removal["end"] != unit["end"] or removal["messages"] != chunk or removal["sha256"] != digest(chunk):
                errors.append((rid, "sidecar_not_exact_source_chunk"))
            if type(anchor) is not int or not index < anchor < len(units):
                errors.append((rid, "not_before_semantic_failure_anchor"))
            ev = next((x for x in evaluation if x.get("action_index") == index), {})
            if ev.get("decision") != "drop" or ev.get("later_reference") is not False or ev.get("confidence") != "high":
                errors.append((rid, "model_did_not_confirm_unreferenced_deletion"))
            safe, reason = safe_no_result_navigation(source["messages"], unit)
            if not safe:
                errors.append((rid, "protected_action_deleted", reason))
            removed_positions.update(range(unit["start"], unit["end"]))
        expected_record = {**source, "messages": [m for index, m in enumerate(source["messages"]) if index not in removed_positions]}
        if candidate != expected_record:
            errors.append((rid, "candidate_not_exact_subsequence"))
        try:
            orig_calls, orig_observations = tool_map(source["messages"])
            calls, observations = tool_map(candidate["messages"])
            if any(orig_calls.get(k) != v for k, v in calls.items()) or any(orig_observations.get(k) != v for k, v in observations.items()):
                errors.append((rid, "retained_tool_call_or_observation_changed"))
        except Exception as exc:
            errors.append((rid, "tool_link_invalid", type(exc).__name__))
        if [m for m in source["messages"] if m["role"] in ("system", "user")] != [m for m in candidate["messages"] if m["role"] in ("system", "user")]:
            errors.append((rid, "system_or_user_changed"))
        summary["removed_actions"] += len(dropped)
        summary["changed_records"] += bool(dropped)
        summary["actions_after"] += len(actions(candidate["messages"]))
        summary["messages_after"] += len(candidate["messages"])
    result = {"status": "structural_audit_passed_pending_human_review" if not errors else "structural_audit_failed", "selected_actions": len(targets), "selected_records": len(grouped), "decisions": len(decisions), "candidates": len(candidates), "stats": dict(summary), "error_count": len(errors), "examples": errors[:20], "limits": "The semantic failure anchor and non-reference judgments come from a strong model, not independent repository replay. No correctness or success certification; review changed records manually."}
    (out / "independent_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "parts" / "part_A" / "review_v3_pre_failure_revisit")
    args = parser.parse_args()
    audit(args.out)
