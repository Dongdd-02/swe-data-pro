#!/usr/bin/env python3
"""Translate the three baseline views in place, structure preserved.

Applies the validated translation map to `original/`, `focused_v2/` and
`full_unreferenced_revisit/` for both parts. Message order, tool calls, tool
replies and split assignment are untouched; only `system`/`assistant` natural
language is replaced. Diagnostic summaries already in Chinese are kept, so the
downstream apply/finalize scripts still reproduce.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'translation_repair_v1'
ALLOWED_MODELS = {None, 'gpt-5.6-luna', 'deepseek-v4.1-flash-1017'}
SOURCES = [WORK / 'reused_translations.jsonl', WORK / 'luna_translation_results.jsonl',
           *sorted(WORK.glob('ds_*.jsonl'))]
TARGETS = [('part_A', 'original'), ('part_A', 'focused_v2'),
           ('part_A', 'full_unreferenced_revisit'),
           ('part_B', 'original'), ('part_B', 'focused_v2'),
           ('part_B', 'full_unreferenced_revisit')]
SPLITS = ('train', 'validation', 'test')
STRIP = re.compile(r'```[\s\S]*?```|`[^`\n]*`|https?://\S+|[A-Za-z]:\\[^\s]+'
                   r'|[A-Za-z0-9_./-]+\.(?:py|js|ts|tsx|json|md|txt|cfg|toml|yaml|yml|ini|sh|html|css)\b')
WORD = re.compile(r"[A-Za-z][A-Za-z']+")


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
            mapping[k] = (original, translated)
    return mapping


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
    import sys
    selected = set(sys.argv[1:])
    mapping = load_map()
    report = {'version': 'baseline_zh_v1', 'targets': {}, 'untranslated': [],
              'review_state': 'requires_human_translation_review',
              'replay_status': 'not_run', 'sft_approved': False}
    targets = [(p, s) for p, s in TARGETS if not selected or f'{p}/{s}' in selected]
    for part, sub in targets:
        directory = ROOT / 'parts' / part / sub
        label = f'{part}/{sub}'
        stats = Counter()
        untranslated = []
        for path in files_for(directory):
            if not path.exists():
                raise RuntimeError(f'missing target file: {path}')
            payloads, changed = [], 0
            for obj in rows(path):
                messages = messages_of(obj)
                before_calls, before_replies = closure(messages)
                stats['records'] += 1
                for message in messages:
                    role, text = message.get('role'), message.get('content')
                    if role not in ('system', 'assistant') or not isinstance(text, str):
                        continue
                    if not needs_translation(text):
                        stats['already_chinese'] += 1
                        continue
                    hit = mapping.get(key(role, text))
                    if hit is None:
                        untranslated.append({'file': str(path.relative_to(ROOT)),
                                             'record': obj.get('id'), 'role': role,
                                             'text': text[:160]})
                        continue
                    message['content'] = hit[1]
                    changed += 1
                    stats['translated'] += 1
                after_calls, after_replies = closure(messages)
                if (before_calls, before_replies) != (after_calls, after_replies):
                    raise RuntimeError(f'{path.name}: tool closure changed')
                payloads.append(obj)
            stats['changed_messages'] += changed
            tmp = path.with_suffix(path.suffix + '.tmp')
            with tmp.open('w', encoding='utf-8', newline='\n') as f:
                for obj in payloads:
                    f.write(json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n')
            tmp.replace(path)
        report['targets'][label] = dict(stats)
        report['untranslated'].extend(untranslated)

    # Post-write verification: no English residue, structures intact.
    residue = 0
    for part, sub in TARGETS:
        directory = ROOT / 'parts' / part / sub
        for path in files_for(directory):
            for obj in rows(path):
                for message in messages_of(obj):
                    if message.get('role') not in ('system', 'assistant'):
                        continue
                    text = message.get('content')
                    if isinstance(text, str) and needs_translation(text):
                        residue += 1

    expected = {'part_A': 2525, 'part_B': 2451}
    for part in expected:
        for sub in ('original', 'focused_v2', 'full_unreferenced_revisit'):
            directory = ROOT / 'parts' / part / sub
            if (directory / 'candidate_records.jsonl').exists():
                count = sum(1 for _ in rows(directory / 'candidate_records.jsonl'))
            else:
                count = sum(sum(1 for _ in rows(directory / f'{s}.jsonl')) for s in SPLITS)
            if count != expected[part]:
                raise RuntimeError(f'{part}/{sub}: record count {count}')

    report['english_residue'] = residue
    report['untranslated_count'] = len(report['untranslated'])
    (WORK / 'baseline_translation_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'untranslated'},
                     ensure_ascii=False))
    if report['untranslated']:
        raise RuntimeError(f"{len(report['untranslated'])} messages lack a translation")


if __name__ == '__main__':
    main()