#!/usr/bin/env python3
"""Validate and package the cleaned bilingual Part A+B SFT candidate."""
from __future__ import annotations
import gzip, hashlib, json, re, zipfile
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'sft_merged_cleaned_zh_v1'
ZIP=ROOT/'sft_merged_cleaned_zh_v1.zip'
MODEL='deepseek-v4.1-flash-1017'
MARKER='[诊断探索合并'

def rows(path):
 with path.open(encoding='utf-8',newline='') as f:
  for line in f:
   if line.strip(): yield json.loads(line)
def digest(data): return hashlib.sha256(data).hexdigest()
def textkey(role,text): return digest(f'{role}\0{text}'.encode('utf-8'))
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
 return h.hexdigest()
def summary(m):
 return m.get('role')=='assistant' and isinstance(m.get('content'),str) and MARKER in m['content']
def validate_tool_closure(messages,rid):
 calls=Counter()
 replies=Counter()
 for i,m in enumerate(messages):
  if m.get('role')=='assistant':
   for call in m.get('tool_calls',[]):
    calls[call['id']]+=1
  if m.get('role')=='tool':
   replies[m.get('tool_call_id')]+=1
 if calls!=replies or any(n!=1 for n in calls.values()):
  raise RuntimeError(f'{rid}: tool call / reply closure mismatch')
def main():
 # Apply and translation provenance must be complete before packaging.
 work=ROOT/'translation_repair_v1'
 applied=json.loads((work/'apply_manifest.json').read_text(encoding='utf-8'))
 translations={}
 ALLOWED={None,'gpt-5.6-luna','deepseek-v4.1-flash-1017'}
 for p in [work/'reused_translations.jsonl',work/'luna_translation_results.jsonl',*sorted(work.glob('ds_*.jsonl'))]:
  if p.exists():
   for item in rows(p):
    if item.get('model') not in ALLOWED: raise RuntimeError(f"rejected model: {p.name} {item.get('model')}")
    if item.get('translation_status')!='translated' or item.get('translation_errors'):
     continue
    if item['translation_key'] in translations: continue
    translations[item['translation_key']]=item['translated_content']
 queue_items={}
 for name in ('translation_queue.jsonl','translation_queue_supplement.jsonl'):
  qp=work/name
  if qp.exists():
   for x in rows(qp): queue_items[x['translation_key']]=x
 import re as _re
 skipped=set()
 for k,item in queue_items.items():
  if k in translations: continue
  if _re.search(r'[\u4e00-\u9fff]',item['original_content']): skipped.add(k)
 queue=set(queue_items)-skipped
 if queue-set(translations): raise RuntimeError('translation queue incomplete')
 assignment={}
 for item in rows(ROOT/'manifests'/'assignment.jsonl'):
  assignment[item['record_id']]=(item['split'],item['source_line'],item['part'])
 all_records={}; removed_count=0; diff_counts=Counter(); source_sizes={}
 for part in ('part_A','part_B'):
  original={x['record']['id']:x for x in rows(ROOT/'parts'/part/'full_unreferenced_revisit'/'candidate_records.jsonl')}
  cleaned={x['record']['id']:x for x in rows(ROOT/'parts'/part/'cleaned_candidate_v1'/'candidate_records.jsonl')}
  if set(original)!=set(cleaned): raise RuntimeError(f'{part}: candidate ID mismatch')
  source_sizes[part]=len(original)
  for rid,srcwrap in original.items():
   src=srcwrap['record']; out=cleaned[rid]['record']
   if srcwrap['split']!=cleaned[rid]['split'] or srcwrap['split']!=assignment[rid][0] or assignment[rid][2]!=part: raise RuntimeError(f'{part}: split mismatch {rid}')
   expected=[]
   for i,m in enumerate(src['messages']):
    if summary(m):
     if m.get('tool_calls'): raise RuntimeError(f'{rid}:{i} summary has tool_calls')
     removed_count+=1; continue
    expected.append((i,m))
   actual=out['messages']
   if len(actual)!=len(expected): raise RuntimeError(f'{rid}: message count mismatch')
   for (source_i,old),new in zip(expected,actual):
    if old.get('role')!=new.get('role'): raise RuntimeError(f'{rid}:{source_i}: role changed')
    role=old.get('role')
    if role not in ('system','assistant'):
     if old!=new: raise RuntimeError(f'{rid}:{source_i}: non-translatable message changed')
     continue
    oldrest={k:v for k,v in old.items() if k!='content'}; newrest={k:v for k,v in new.items() if k!='content'}
    if oldrest!=newrest: raise RuntimeError(f'{rid}:{source_i}: message metadata/tool call changed')
    oldtext=old.get('content'); newtext=new.get('content')
    if oldtext!=newtext:
     if not isinstance(oldtext,str) or textkey(role,oldtext) not in queue or translations.get(textkey(role,oldtext))!=newtext:
      raise RuntimeError(f'{rid}:{source_i}: changed text lacks verified translation')
     diff_counts[role]+=1
    elif isinstance(oldtext,str) and textkey(role,oldtext) in queue:
     raise RuntimeError(f'{rid}:{source_i}: queued translation was not applied')
   if rid in all_records: raise RuntimeError('duplicate ID across parts')
   if any(summary(m) for m in actual): raise RuntimeError(f'{rid}: diagnostic summary remains')
   validate_tool_closure(actual,rid)
   all_records[rid]=(assignment[rid][0],assignment[rid][1],out)
 if len(all_records)!=4976: raise RuntimeError(f"record coverage mismatch: {len(all_records)}")
 if removed_count!=applied['removed_summary_messages']: raise RuntimeError('removed summary count mismatch')
 # Sidecar rows must account for every removed message.
 sidecar=work/'removed_diagnostic_summary_messages.jsonl.gz'; sidecar_count=0
 with gzip.open(sidecar,'rt',encoding='utf-8') as f:
  for line in f:
   x=json.loads(line); sidecar_count+=1
   if not summary(x['message']): raise RuntimeError('sidecar includes non-summary')
 if sidecar_count!=removed_count: raise RuntimeError('summary sidecar count mismatch')
 OUT.mkdir(exist_ok=True)
 split_counts={}
 for split in ('train.jsonl','validation.jsonl','test.jsonl'):
  selected=sorted(((source_line,rec) for rid,(sp,source_line,rec) in all_records.items() if sp==split),key=lambda x:x[0])
  if len({n for n,_ in selected})!=len(selected): raise RuntimeError(f'{split}: duplicate source line')
  p=OUT/split
  with p.open('w',encoding='utf-8',newline='\n') as f:
   for _,rec in selected: f.write(json.dumps(rec,ensure_ascii=False,separators=(',',':'))+'\n')
  split_counts[split]=len(selected)
 # Include an auditable copy of the summary-removal sidecar.
 (OUT/'REMOVED_DIAGNOSTIC_SUMMARIES.jsonl.gz').write_bytes(sidecar.read_bytes())
 report={'records':len(all_records),'split_counts':split_counts,'source_records_by_part':source_sizes,'removed_standalone_summary_messages':removed_count,'translated_message_occurrences':dict(diff_counts),'unique_translations':len(queue),'review_state':'translation_requires_human_review','replay_status':'not_run','sft_approved':False,'ordering':'assignment.source_line within split','archive':'sft_merged_cleaned_zh_v1.zip'}
 (OUT/'TRANSLATION_REPAIR_REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (OUT/'README.md').write_text(f"""# Part A+B 清理版 SFT 候选\n\n本包按 `manifests/assignment.jsonl` 的 split 与 source_line 顺序合并 Part A/B 清理候选。\n\n- 记录：{len(all_records)}\n- train / validation / test：{split_counts['train.jsonl']} / {split_counts['validation.jsonl']} / {split_counts['test.jsonl']}\n- 已删除独立 `[诊断探索合并]` assistant 消息：{removed_count} 条；原文保存在 `REMOVED_DIAGNOSTIC_SUMMARIES.jsonl.gz`。\n- system/assistant 英文翻译：{len(queue)} 个唯一文本映射到 {sum(diff_counts.values())} 个消息位置。\n\n该数据是清理候选，翻译尚需人工抽检，仓库 replay 未运行，尚未获 SFT 正式批准。训练只使用 train；validation/test 保持隔离。\n""",encoding='utf-8')
 manifest=[]
 for p in sorted(OUT.iterdir()):
  if p.is_file() and p.name!='SHA256SUMS.json': manifest.append({'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)})
 (OUT/'SHA256SUMS.json').write_text(json.dumps({'files':manifest},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 with zipfile.ZipFile(ZIP,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for p in sorted(OUT.iterdir()):
   if p.is_file(): z.write(p,arcname=p.name)
 with zipfile.ZipFile(ZIP) as z:
  if z.testzip() is not None: raise RuntimeError('zip CRC test failed')
  for item in manifest:
   if digest(z.read(item['path']))!=item['sha256']: raise RuntimeError(f"zip hash mismatch: {item['path']}")
 print(json.dumps({**report,'zip_path':str(ZIP),'zip_bytes':ZIP.stat().st_size,'archive_integrity':'passed'},ensure_ascii=False))
if __name__=='__main__': main()
