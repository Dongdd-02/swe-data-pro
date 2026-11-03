#!/usr/bin/env python3
"""Audit focused candidate, including intentionally removed large previews."""
import argparse
import collections
import gzip
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from compress_swe_failure_repair_conservative import SRC,actions
LINE=re.compile(r'^[ \t]*\d+[ \t].*$',re.M)


def main(root):
    removed=collections.defaultdict(list)
    with gzip.open(root/'removed_exploration.jsonl.gz','rt',encoding='utf-8') as f:
        for raw in f:
            x=json.loads(raw);removed[x['split'],x['record_id']].append(x)
    manifest={}
    with (root/'record_manifest.jsonl').open(encoding='utf-8') as f:
        for raw in f:
            x=json.loads(raw);manifest[x['split'],x['record_id']]=x
    stats=collections.Counter();errors=[];samples=[]
    for split in ('train.jsonl','validation.jsonl','test.jsonl'):
        with (SRC/split).open(encoding='utf-8') as source,(root/split).open(encoding='utf-8') as target:
            for old,new in zip(source,target):
                before,after=json.loads(old),json.loads(new);key=split,before['id'];items=removed.get(key,[]);drop=set();ordinary=set();previews=[]
                original_actions=actions(before['messages'])
                for d in items:
                    if before['messages'][d['start']:d['end']]!=d['messages']:errors.append((key,'sidecar_diff'))
                    drop.update(range(d['start'],d['end']))
                    if d['messages'][0]['tool_calls'][0]['function']['name']!='Read':continue
                    observation='\n'.join(str(m.get('content') or '') for m in d['messages'][1:]).replace('\r','')
                    if 'This file is too large to display entirely' in observation:
                        previews.append((d,observation))
                    else:ordinary.update(LINE.findall(observation))
                visible='\n'.join(str(m.get('content') or '').replace('\r','') for m in after['messages'])
                if any(row not in visible for row in ordinary):errors.append((key,'ordinary_read_code_lost'))
                for d,text in previews:
                    idx=d['action_index'];path=original_actions[idx]['calls'][0][1].get('file_path');target_read=False
                    for a in original_actions[idx+1:]:
                        if a['protected']:break
                        if len(a['calls'])==1 and a['calls'][0][0]=='Read' and a['calls'][0][1].get('file_path')==path and a['calls'][0][1].get('offset') is not None and a['start'] not in drop:
                            target_read=True;break
                    if not target_read:errors.append((key,'large_preview_lacks_retained_targeted_read'))
                    stats['large_previews_replaced']+=1;stats['large_preview_chars']+=len(text);stats['large_preview_numbered_lines']+=len(LINE.findall(text))
                    if len(samples)<5:samples.append({'record_id':before['id'],'action_index_zero_based':idx,'path':path})
                kept=[m for i,m in enumerate(before['messages']) if i not in drop]
                original_only=[m for m in after['messages'] if not(m['role']=='assistant' and str(m.get('content') or '').startswith('[诊断探索合并：'))]
                if kept!=original_only or {k:v for k,v in before.items() if k!='messages'}!={k:v for k,v in after.items() if k!='messages'}:errors.append((key,'non_deleted_changed'))
                anchor_old=[before['messages'][a['start']:a['end']] for a in original_actions if a['protected']]
                anchor_new=[after['messages'][a['start']:a['end']] for a in actions(after['messages']) if a['protected']]
                if anchor_old!=anchor_new:errors.append((key,'protected_failure_mutation_verification_changed'))
                disposition=manifest.get(key)
                if not disposition or disposition['removed_action_indices']!=[x['action_index'] for x in items]:errors.append((key,'manifest_mismatch'))
                if not disposition['explicit_failure_identified'] and before!=after:errors.append((key,'uncertain_failure_record_changed'))
                stats.update(records=1,removed_actions=len(items),summaries=len(after['messages'])-len(original_only),ordinary_numbered_code_lines_checked=len(ordinary),source_content_chars=sum(len(str(m.get('content') or '')) for m in before['messages']),candidate_content_chars=sum(len(str(m.get('content') or '')) for m in after['messages']),unknown_failure_records_untouched=int(not disposition['explicit_failure_identified']))
    report={'status':'structural_audit_only_semantic_replay_pending','counts':dict(stats),'message_content_reduction_pct':round(100*(stats['source_content_chars']-stats['candidate_content_chars'])/stats['source_content_chars'],4),'removed_action_reduction_pct':round(100*stats['removed_actions']/128700,4),'audit_errors':len(errors),'error_examples':errors[:10],'large_preview_examples':samples,'limitation':'Large abbreviated previews may contain source context not repeated in the targeted read; this candidate needs manual semantic review and repository replay, not formal Pangu SFT approval.'}
    (root/'independent_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    if errors:raise RuntimeError(str(errors[:5]))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('candidate',type=Path);main(ap.parse_args().candidate)
