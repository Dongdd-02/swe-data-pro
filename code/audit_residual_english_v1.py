#!/usr/bin/env python3
"""Report residual English prose in cleaned system/assistant messages."""
from __future__ import annotations
import json,re
from collections import Counter
from pathlib import Path
from prepare_translation_repair_v1 import english_prose,is_summary
ROOT=Path(__file__).resolve().parents[1]
START=re.compile(r"^\s*(?:Now|Let's|Let us|Great|Perfect|Next|First|We need|I will|I can|It looks|This is|The issue|To fix|Finally|However|Therefore|We have|Here is|There are|After that)\b",re.I)
FENCE=re.compile(r"```[\s\S]*?```")
INLINE=re.compile(r"`[^`\n]*`")

def main():
 stats=Counter();examples=[]
 for part in ('part_A','part_B'):
  p=ROOT/'parts'/part/'cleaned_candidate_v1'/'candidate_records.jsonl'
  if not p.is_file(): continue
  with p.open(encoding='utf-8',newline='') as f:
   for line in f:
    if not line.strip():continue
    rec=json.loads(line)['record']
    for i,m in enumerate(rec['messages']):
     role=m.get('role');text=m.get('content')
     if role not in ('system','assistant') or not isinstance(text,str):continue
     if role=='assistant' and is_summary(text): stats['remaining_summary']+=1
     plain=INLINE.sub(' ',FENCE.sub(' ',text)).strip()
     if role=='system' and plain.startswith('You are a helpful'): stats['english_system']+=1
     if role=='assistant' and (english_prose(text) or START.search(plain)):
      stats['possible_english_assistant']+=1
      if len(examples)<100:
       examples.append({'record_id':rec['id'],'part':part,'message_index':i,'excerpt':plain[:350]})
 out={'counts':dict(stats),'sample':examples,'limits':'Heuristic report. Technical words and quoted error messages may be English; manually review the samples. Do not claim zero English without independent review.'}
 target=ROOT/'translation_repair_v1'/'residual_language_audit.json'
 target.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'counts':dict(stats),'sample_count':len(examples),'output':str(target)},ensure_ascii=False))
if __name__=='__main__':main()
