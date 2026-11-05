#!/usr/bin/env python3
"""Publish the v2 and post-v2 views in Chinese with diagnostic summaries removed.

Both views keep their own action set: `focused_v2/` stays at the first-round
compression and `full_unreferenced_revisit/` at the second-round compression.
Only language changes and standalone summary messages are dropped; the summary
originals are already archived in
`translation_repair_v1/removed_diagnostic_summary_messages.jsonl.gz`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'translation_repair_v1'
ALLOWED_MODELS = {None, 'gpt-5.6-luna', 'deepseek-v4.1-flash-1017'}
SOURCES = [WORK / 'reused_translations.jsonl', WORK / 'luna_translation_results.jsonl',
           *sorted(WORK.glob('ds_*.jsonl'))]
MARKER = '[诊断探索合并'
SPLITS = ('train', 'validation', 'test')
STRIP = re.compile(r'```[\s\S]*?```|`[^`\n]*`|https?://\S+|[A-Za-z]:\\[^\s]+'
                   r'|[A-Za-z0-9_./-]+\.(?:py|js|ts|tsx|json|md|txt|cfg|toml|yaml|yml|ini|sh|html|css)\b')
WORD = re.compile(r"[A-Za-z][A-Za-z']+")
EXPECTED_ACTIONS = {'part_A': {'focused_v2': 62039, 'full_unreferenced_revisit': 59162},
                    'part_B': {'focused_v2': 59935, 'full_unreferenced_revisit': 57213}}
EXPECTED_RECORDS = {'part_A': 2525, 'part_B': 2451}


def key(role, text):
    return hashlib.sha256(f'{role}\0{text}'.encode('utf-8')).hexdigest()


def rows(path):
    with path.open(encoding='utf-8', newline='') as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def needs_translation(text):
    cleaned = STRIP.sub(' ', text)
    if re.search(r'[\u4e00-\u9fff]', cleaned):
        return False
    return bool(WORD.findall(cleaned))


def load_map():
    mapping = {}
    for path in SOURCES:
        if not path.exists():
            continue
        for item in rows(path):
            if item.get('translation_status') != 'translated' or item.get('translation_errors'):
                continue
            model = item.get('model')
            if model not in ALLOWED_MODELS:
                raise RuntimeError(f'rejected model in {path.name}: {model}')
            k = item['translation_key']
            if k in mapping:
                continue
            original, translated = item['original_content'], item['translated_content']
            if key(item['role'], original) != k:
                raise RuntimeError('translation key mismatch')
            if not translated.strip() or translated == original:
                continue
            mapping[k] = translated
    return mapping


def replace_with_retry(tmp, target):
    for attempt in range(8):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == 7:
                os.unlink(target)
                os.rename(tmp, target)
                return
            time.sleep(1.0)


def files_for(directory):
    candidate = directory / 'candidate_records.jsonl'
    if candidate.exists():
        return [candidate]
    return [directory / f'{split}.jsonl' for split in SPLITS]


def messages_of(obj):
    return obj['record']['messages'] if 'record' in obj else obj['messages']


def closure(messages):
    calls, replies = Counter(), Counter()
    for message in messages:
        if message.get('role') == 'assistant':
            for call in message.get('tool_calls', []):
                calls[call['id']] += 1
        if message.get('role') == 'tool':
            replies[message.get('tool_call_id')] += 1
    return calls, replies


def main():
    selected = set(sys.argv[1:])
    mapping = load_map()
    report = {'version': 'v2_views_zh_v1', 'targets': {},
              'review_state': 'requires_human_translation_review',
              'replay_status': 'not_run', 'sft_approved': False,
              'summary_archive': 'translation_repair_v1/removed_diagnostic_summary_messages.jsonl.gz'}
    for part in ('part_A', 'part_B'):
        for view in ('focused_v2', 'full_unreferenced_revisit'):
            if selected and f'{part}/{view}' not in selected:
                continue
            directory = ROOT / 'parts' / part / view
            stats = Counter()
            missing = []
            for path in files_for(directory):
                payloads = []
                for obj in rows(path):
                    messages = messages_of(obj)
                    before = closure(messages)
                    stats['records'] += 1
                    kept = []
                    for index, message in enumerate(messages):
                        role, text = message.get('role'), message.get('content')
                        if role == 'assistant' and isinstance(text, str) and MARKER in text:
                            if message.get('tool_calls'):
                                raise RuntimeError(f'{part}/{view}: summary carries tool_calls')
                            stats['removed_summaries'] += 1
                            continue
                        if role in ('system', 'assistant') and isinstance(text, str):
                            # Translate by map hit, not by a language heuristic: the
                            # queue also covers mixed Chinese/English messages, and
                            # skipping those would diverge from the shipped package.
                            translated = mapping.get(key(role, text))
                            if translated is not None:
                                message['content'] = translated
                                stats['translated'] += 1
                            elif needs_translation(text):
                                missing.append(f'{path.name}:{text[:80]}')
                        kept.append(message)
                    if closure(kept) != before:
                        raise RuntimeError(f'{part}/{view}: tool closure changed')
                    stats['actions'] += sum(len(m.get('tool_calls', []))
                                            for m in kept if m.get('role') == 'assistant')
                    obj_messages = messages_of(obj)
                    obj_messages[:] = kept
                    payloads.append(obj)
                if missing:
                    raise RuntimeError(f'{part}/{view}: {len(missing)} missing translations')
                tmp = path.with_suffix(path.suffix + '.tmp')
                with tmp.open('w', encoding='utf-8', newline='\n') as f:
                    for obj in payloads:
                        f.write(json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n')
                replace_with_retry(tmp, path)
            report['targets'][f'{part}/{view}'] = dict(stats)

    # Post-write verification.
    problems = []
    for part, views in EXPECTED_ACTIONS.items():
        for view, expected in views.items():
            directory = ROOT / 'parts' / part / view
            actions = markers = english = records = 0
            for path in files_for(directory):
                for obj in rows(path):
                    records += 1
                    messages = messages_of(obj)
                    calls, replies = closure(messages)
                    if calls != replies or any(v != 1 for v in calls.values()):
                        problems.append(f'{part}/{view}: closure')
                    for message in messages:
                        role, text = message.get('role'), message.get('content')
                        if role == 'assistant':
                            actions += len(message.get('tool_calls', []))
                            if isinstance(text, str) and MARKER in text:
                                markers += 1
                        if role in ('system', 'assistant') and isinstance(text, str) and needs_translation(text):
                            english += 1
            if records != EXPECTED_RECORDS[part]:
                problems.append(f'{part}/{view}: records {records}')
            if actions != expected:
                problems.append(f'{part}/{view}: actions {actions} != {expected}')
            if markers or english:
                problems.append(f'{part}/{view}: markers={markers} english={english}')
    report['verification'] = problems or 'passed'
    (WORK / 'v2_views_translation_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    if problems:
        raise RuntimeError('; '.join(problems))


if __name__ == '__main__':
    main()