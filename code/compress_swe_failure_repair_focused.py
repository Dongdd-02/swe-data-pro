#!/usr/bin/env python3
"""Focused large-file preview pruning on the auditable stage-summary candidate.

A generic, abbreviated Read preview can be removed when the same phase has a
later targeted Read of the same path. Such previews are recorded losslessly in
the sidecar; this is a semantic candidate requiring manual review/replay.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
import compress_swe_failure_repair_stage_summary as base

OUTPUT=Path(r"D:\code_codex\deliverables\swe_sft_4976_zh_failure_repair_focused_20261103")
original_candidate_run=base.candidate_run
original_describe=base.describe


def preview_redundant(messages, units, run, index):
    unit=units[index]
    if unit['protected'] or not unit['complete'] or len(unit['calls'])!=1 or unit['calls'][0][0]!='Read':return False
    narration=str(messages[unit['start']].get('content') or '')
    if len(narration)>200 or re.search(r'发现|原因|这意味着|因此|所以|问题在|根本原因|怀疑|我们需要修复|确认',narration):return False
    text=base.obs(messages,unit)
    if 'This file is too large to display entirely' not in text:return False
    path=unit['calls'][0][1].get('file_path')
    for later in run[run.index(index)+1:]:
        action=units[later]
        if len(action['calls'])!=1 or action['calls'][0][0]!='Read':continue
        args=action['calls'][0][1]
        if args.get('file_path')==path and args.get('offset') is not None and action['complete']:
            targeted_text=base.obs(messages,action)
            for future in units[index+1:]:
                for name,change in future['calls']:
                    if name!='Edit' or change.get('file_path')!=path:continue
                    for fragment in str(change.get('old_string') or '').splitlines():
                        fragment=fragment.strip()
                        if len(fragment)>=15 and fragment in text and fragment not in targeted_text:
                            return False
            return True
    return False


def candidate_run(messages,units,run):
    common=original_candidate_run(messages,units,run)
    previews=[i for i in run if preview_redundant(messages,units,run,i)]
    drops=sorted(set(common+previews))
    return drops if len(drops)>=1 else []


def describe(messages,units,indices,retained):
    previews=[i for i in indices if preview_redundant(messages,units,sorted(set(indices+retained)),i)]
    # The preview contains an arbitrary head/tail of a large file; copying the
    # whole preview into the model view would defeat semantic compaction.
    # Keep the later targeted view, and explicitly describe this trade-off.
    body=original_describe(messages,units,[i for i in indices if i not in previews],retained)
    if previews:
        paths=sorted({str(units[i]['calls'][0][1].get('file_path')) for i in previews})
        body+='\n同一阶段已用精确范围读取替代 '+str(len(previews))+' 次大文件缩略预览：'+'、'.join(paths[:8])+'。预览的非目标行仍可在 sidecar 审计。'
    return body


base.candidate_run=candidate_run
base.describe=describe
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--out',type=Path,default=OUTPUT)
    args=parser.parse_args()
    base.build(args.limit,args.out)
    path=args.out/'audit_report.json'
    report=json.loads(path.read_text(encoding='utf-8'))
    report['method']='Only explicit-failure records are considered. Every recognized failure, Edit/Write and verification action is retained with full original output. Intermediate redundant exploration is grouped with verbatim unique numbered code lines; a large abbreviated Read is omitted only if a later same-file targeted Read occurs in the same phase. All omitted actions are in a lossless sidecar.'
    report['important_limitations'].append('Large abbreviated source previews can contain distinct lines not repeated by the targeted Read; they require semantic human review before Pangu use.')
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
