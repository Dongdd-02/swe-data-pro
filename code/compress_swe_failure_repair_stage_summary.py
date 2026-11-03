#!/usr/bin/env python3
"""Build a stage-aware *candidate* for translated SWE failure-repair SFT.

This intentionally makes a trade-off: some non-anchor exploration gets a
factual Chinese summary instead of its full tool output. It is not replayed
or approved for training. Source chunks are losslessly preserved in sidecar.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from compress_swe_failure_repair_conservative import SRC, actions, tool_map

DEFAULT_OUT = Path(r"D:\code_codex\deliverables\swe_sft_4976_zh_failure_repair_stage_summary_20261103")
FILENAME = re.compile(r"(?:/testbed|\./)[\w./-]+")
POSITIVE = re.compile(r"^\s*\d+[:\-]\S", re.M)
SEARCH = re.compile(r"^\s*(?:cd\s+\S+\s*&&\s*)?(?:grep|rg|find|ls|head|tail|wc|cat|git\s+(?:status|log|ls-files))\b")


def obs(messages, unit):
    return "\n".join(str(m.get("content") or "") for m in messages[unit["start"] + 1:unit["end"]])


def describe(messages, units, indices, retained):
    paths, negative, hits, read_count = set(), 0, [], 0
    covered = set()
    for i in retained:
        for message in messages[units[i]["start"] + 1:units[i]["end"]]:
            covered.update(re.findall(r"^\s*\d+\t.*$", str(message.get("content") or "").replace("\r", ""), re.M))
    unique_code = defaultdict(list)
    for i in indices:
        u = units[i]
        for name, args in u["calls"]:
            if name == "Read":
                read_count += 1
                path = str(args.get("file_path") or "")
                if path: paths.add(path)
                text = obs(messages, u).replace("\r", "")
                for source_line in re.findall(r"^\s*\d+\t.*$", text, re.M):
                    if source_line not in covered:
                        unique_code[path].append(source_line)
                        covered.add(source_line)
            elif name == "Bash":
                cmd = str(args.get("command") or "")
                for path in FILENAME.findall(cmd):
                    if len(paths) < 8: paths.add(path)
                if "did not produce any output" in obs(messages, u): negative += 1
                else:
                    text = obs(messages, u)
                    for match in POSITIVE.findall(text):
                        if match not in hits and len(hits)<3:hits.append(match[:120])
    short_paths = sorted(paths)[:6]
    lines = [f"[诊断探索合并：省略 {len(indices)} 轮只读探索；原始调用与输出保存在对应 sidecar。]", f"其中读取文件 {read_count} 次、无结果搜索 {negative} 次。"]
    if short_paths:lines.append("涉及路径：" + "、".join(short_paths) + (" 等" if len(paths)>6 else "") + "。")
    if hits:lines.append("搜索命中示例（原文片段）：" + "；".join(hits) + "。")
    for path, code_lines in sorted(unique_code.items()):
        lines.append("省略读取中仅有的原始编号代码行（" + path + "）：\n" + "\n".join(code_lines))
    lines.append("后续保留的工具动作和原始失败输出继续展示诊断、修改及验证过程。")
    return "\n".join(lines)


def candidate_run(messages, units, run):
    if len(run) < 4:return []
    keep = {run[0], run[-1]}
    # Keep the earliest and latest code view per file (including unmodified
    # caller/test/config files), plus every successful search result.
    reads = defaultdict(list)
    for index in run:
        u=units[index]
        narration=str(messages[u["start"]].get("content") or "")
        if len(narration)>200 or re.search(r"发现|原因|这意味着|因此|所以|问题在|根本原因|怀疑|我们需要修复|确认", narration):
            keep.add(index)
        if len(u["calls"])!=1 or not u["complete"]:
            keep.add(index);continue
        name,args=u["calls"][0]
        if name == "Read":
            read_result = obs(messages, u)
            if re.search(r"(?im)^\s*(?:OBSERVATION:\s*)?(?:Error:|Invalid `view_range`|File not found)", read_result):
                keep.add(index)
            else:
                reads[str(args.get("file_path") or "")].append(index)
        elif name == "Bash":
            cmd=str(args.get("command") or "")
            result=obs(messages,u)
            if not SEARCH.match(cmd) or ("did not produce any output" not in result and result.strip()):
                keep.add(index)
        else:keep.add(index)
    for indexes in reads.values():
        keep.update((indexes[0],indexes[-1]))
    # Keep a probe near a decision boundary even if it was a negative search.
    keep.update(run[-2:])
    drop=[i for i in run if i not in keep]
    return drop if len(drop)>=2 else []


def select(messages, units):
    if not any(u["failure"] for u in units):return []
    runs=[];current=[];prev_end=None
    for i,u in enumerate(units):
        if u["protected"] or (prev_end is not None and prev_end<u["start"]):
            if current:runs.append(current)
            current=[]
        if not u["protected"]:current.append(i)
        prev_end=u["end"]
    if current:runs.append(current)
    return [(run,candidate_run(messages,units,run)) for run in runs if candidate_run(messages,units,run)]


def build(limit, output):
    output.mkdir(parents=True,exist_ok=True)
    stats=Counter();case_samples=[]
    with gzip.open(output/"removed_exploration.jsonl.gz","wt",encoding="utf-8") as sidecar,(output/"record_manifest.jsonl").open("w",encoding="utf-8") as manifest:
        for split in ("train.jsonl","validation.jsonl","test.jsonl"):
            with (SRC/split).open(encoding="utf-8") as source,(output/split).open("w",encoding="utf-8") as target:
                for raw in source:
                    if limit and stats['records']>=limit:break
                    row=json.loads(raw);messages=row['messages'];units=actions(messages);groups=select(messages,units)
                    drop=set();summaries={};removed=[]
                    for run,indices in groups:
                        start=units[indices[-1]]["start"]
                        summaries[start]={"role":"assistant","content":describe(messages,units,indices,[i for i in run if i not in indices])}
                        for index in indices:
                            unit=units[index]
                            drop.update(range(unit["start"],unit["end"]))
                            sidecar.write(json.dumps({"split":split,"record_id":row['id'],"action_index":index,"start":unit["start"],"end":unit["end"],"messages":messages[unit["start"]:unit["end"]]},ensure_ascii=False,separators=(",",":"))+"\n")
                            removed.append(index)
                    result=[]
                    for i,m in enumerate(messages):
                        if i in summaries:result.append(summaries[i])
                        if i not in drop:result.append(m)
                    outrow={**row,"messages":result}
                    old_calls,old_obs=tool_map(messages);new_calls,new_obs=tool_map(result)
                    if any(old_calls.get(k)!=v for k,v in new_calls.items()) or any(old_obs.get(k)!=v for k,v in new_obs.items()):raise RuntimeError(f"retained tool changed: {row['id']}")
                    if [m for m in messages if m['role'] in ('system','user')]!=[m for m in result if m['role'] in ('system','user')]:raise RuntimeError(f"translated system/user changed: {row['id']}")
                    if any(units[i]['protected'] for i in removed):raise RuntimeError(f"removed protected action: {row['id']}")
                    target.write(json.dumps(outrow,ensure_ascii=False,separators=(",",":"))+"\n")
                    stats.update(records=1,explicit_failure_records=int(any(u['failure'] for u in units)),untouched=int(not removed),removed_exploration_actions=len(removed),summary_messages=len(summaries),messages_before=len(messages),messages_after=len(result),observation_chars_before=sum(len(str(m.get('content') or '')) for m in messages),observation_chars_after=sum(len(str(m.get('content') or '')) for m in result))
                    if removed and len(case_samples)<8:case_samples.append({"record_id":row['id'],"removed":len(removed),"summary_count":len(summaries)})
                    manifest.write(json.dumps({"split":split,"record_id":row['id'],"explicit_failure_identified":any(u['failure'] for u in units),"removed_action_indices":removed,"summary_messages":len(summaries),"disposition":"stage_summary" if removed else "unchanged","replay_status":"not_run"},ensure_ascii=False,separators=(",",":"))+"\n")
            if limit and stats['records']>=limit:break
    report={"status":"candidate_needs_semantic_review_and_replay","source":str(SRC),"output":str(output),"stats":dict(stats),"pilot_examples":case_samples,"method":"Preserve all recognized failure/mutation/verification and their complete observations; retain first/last Read of every file in exploratory runs and all positive/non-read probes; merge intermediate redundant probes into a Chinese transition, copying each otherwise-unseen numbered source-code line verbatim with its file path; retain full raw sidecar.","important_limitations":["Assistant reasoning and non-numbered text from removed exploratory reads may be absent in the model-visible summary.","Classifiers are heuristic; human review of removed segments and repository replay are required before Pangu SFT use.","Records without an explicit detectable failure are left unchanged, not certified clean or suitable."],"formal_sft_approved":False}
    (output/"audit_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=0);parser.add_argument('--out',type=Path,default=DEFAULT_OUT);args=parser.parse_args();build(args.limit,args.out)
