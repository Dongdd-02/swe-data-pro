#!/usr/bin/env python3
"""Conservative duplicate-only baseline for translated failure-repair SWE traces.

Deletes a repeated, identical successful Read action only when it occurs in a
record with an explicit Bash failure and no protected action has intervened.
All remaining messages and observations are byte-for-byte identical as values.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

SRC = Path(r"D:\code_codex\deliverables\swe_sft_4976_zh_staging_20261101")
DST = Path(r"D:\code_codex\deliverables\swe_sft_4976_zh_failure_repair_conservative_20261103")
FAIL = re.compile(r"(?is)(?:^|\n)\s*(?:OBSERVATION:\s*)?(?:Error:|FAILED\b|Traceback \(most recent call last\))|Traceback \(most recent call last\)")
VERIFY = re.compile(r"(?i)\b(?:pytest|unittest|tox|nox|coverage|mypy|pyright|ruff|flake8|pylint|eslint)\b|\b(?:verify|reproduce|test)[\w-]*\.(?:py|sh)\b|git\s+diff\s+--check")
MUTATE = re.compile(r"(?i)(?:\b(?:sed|perl)\s+-i\b|\b(?:apply_patch|git\s+apply|mv|cp|rm|mkdir|touch|tee)\b|>>|(?<![<>])>(?![=>])|write_text|\.write\()")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def actions(messages):
    result = []
    index = 0
    while index < len(messages):
        m = messages[index]
        calls = m.get("tool_calls") or [] if m.get("role") == "assistant" else []
        if not calls:
            index += 1
            continue
        ids = {str(call.get("id") or "") for call in calls}
        end = index + 1
        while end < len(messages) and messages[end].get("role") == "tool" and str(messages[end].get("tool_call_id") or "") in ids:
            end += 1
        tool_messages = messages[index+1:end]
        parsed = []
        for call in calls:
            fn = call.get("function") or {}
            arg = fn.get("arguments") or {}
            if isinstance(arg, str):
                try: arg = json.loads(arg)
                except json.JSONDecodeError: arg = {}
            parsed.append((str(fn.get("name") or ""), arg if isinstance(arg, dict) else {}))
        command = "\n".join(str(arg.get("command") or "") for name,arg in parsed if name == "Bash")
        is_mutation = any(name in ("Edit", "Write") for name,_ in parsed) or bool(MUTATE.search(command))
        is_verification = bool(VERIFY.search(command))
        is_failure = any(name == "Bash" for name,_ in parsed) and any(FAIL.search(str(tm.get("content") or "")) for tm in tool_messages)
        result.append({"start": index, "end": end, "calls": parsed, "failure": is_failure, "protected": is_mutation or is_verification or is_failure, "complete": len(tool_messages) == len(ids)})
        index = end
    return result


def tool_map(messages):
    calls, observations = {}, {}
    for m in messages:
        if m.get("role") == "assistant":
            for c in m.get("tool_calls") or []:
                cid = str(c.get("id") or "")
                if not cid or cid in calls: raise RuntimeError("duplicate tool call id")
                calls[cid] = c
        elif m.get("role") == "tool":
            cid = str(m.get("tool_call_id") or "")
            if cid in observations: raise RuntimeError("duplicate observation id")
            observations[cid] = m
    if calls.keys() != observations.keys(): raise RuntimeError("tool call closure mismatch")
    return calls, observations


def run():
    DST.mkdir(parents=True, exist_ok=True)
    aggregate = Counter()
    with (DST / "record_disposition.jsonl").open("w",encoding="utf-8") as manifest, (DST / "deleted_identical_actions.jsonl").open("w",encoding="utf-8") as deleted:
        for split in ("train.jsonl", "validation.jsonl", "test.jsonl"):
            with (SRC/split).open(encoding="utf-8") as read, (DST/split).open("w",encoding="utf-8") as write:
                for line in read:
                    record = json.loads(line)
                    rid = record["id"]
                    old = record["messages"]
                    units = actions(old)
                    has_explicit_failure = any(unit["failure"] for unit in units)
                    drop = set()
                    seen = set()
                    for unit in units:
                        if unit["protected"] or not unit["complete"]:
                            seen.clear()
                            continue
                        if not has_explicit_failure or not unit["calls"] or any(name != "Read" for name,_ in unit["calls"]):
                            continue
                        segment = old[unit["start"]:unit["end"]]
                        signature = digest([{k:v for k,v in message.items() if k != "tool_call_id" and k != "tool_calls"} for message in segment] + [unit["calls"]])
                        if signature in seen:
                            drop.update(range(unit["start"],unit["end"]))
                            deleted.write(json.dumps({"split":split,"record_id":rid,"start":unit["start"],"end":unit["end"],"messages":segment},ensure_ascii=False)+"\n")
                        seen.add(signature)
                    new = {**record,"messages":[m for index,m in enumerate(old) if index not in drop]}
                    prior_calls,prior_obs = tool_map(old)
                    next_calls,next_obs = tool_map(new["messages"])
                    if any(prior_calls.get(k) != v for k,v in next_calls.items()) or any(prior_obs.get(k) != v for k,v in next_obs.items()):
                        raise RuntimeError(f"tool changed: {rid}")
                    if [m for m in old if m["role"] in ("system","user")] != [m for m in new["messages"] if m["role"] in ("system","user")]:
                        raise RuntimeError(f"system/user changed: {rid}")
                    protected_ids = {str(c.get("id")) for unit in units if unit["protected"] for c in old[unit["start"]].get("tool_calls",[])}
                    if not protected_ids.issubset(next_calls): raise RuntimeError(f"failure/edit/test lost: {rid}")
                    write.write(json.dumps(new,ensure_ascii=False,separators=(",",":"))+"\n")
                    count = len([unit for unit in units if unit["start"] in drop])
                    manifest.write(json.dumps({"split":split,"record_id":rid,"explicit_failure_identified":has_explicit_failure,"disposition":"conservative_exact_duplicate" if count else "unchanged","removed_actions":count,"messages_before":len(old),"messages_after":len(new["messages"]),"replay_status":"not_run"},ensure_ascii=False)+"\n")
                    aggregate.update(records=1,explicit_failures=int(has_explicit_failure),untouched=int(not count),removed_actions=count,messages_before=len(old),messages_after=len(new["messages"]))
    report={"status":"completed_conservative_baseline","source":str(SRC),"output":str(DST),"counts":dict(aggregate),"rule":"Only identical successful Read actions with identical assistant narration and observation, within an explicit-failure trace and without intervening edit/failure/verification, may be deleted.","critical_observations":"unchanged","all_remaining_messages":"unchanged","replay_status":"not_run","candidate_requires_replay":True,"formal_sft_approved":False,"previous_30pct_package_suitable_for_failure_repair_sft":False}
    (DST/"audit_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (DST/"README.md").write_text("# 中文 SWE 失败修复轨迹：保守基线\n\n以最终已翻译的 4,976 条为唯一输入。只去掉可逐字证明重复的成功 Read 动作；未识别出明确失败或无法证明冗余的轨迹保持原样。所有保留的 observation、assistant、system、user 文本均不截断。`record_disposition.jsonl` 标明每条记录的处理状态。没有执行仓库 replay，本目录不能宣称正式可训练。此前的 30% 缩短包不是失败修复 SFT 的可靠输入。\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))

if __name__ == "__main__": run()
