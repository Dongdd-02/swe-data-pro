#!/usr/bin/env python3
"""Apply validated translations and delete standalone diagnostic summaries."""
from __future__ import annotations
import gzip, hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'translation_repair_v1'
# gpt-6-sol output was rejected by the user and must never be reused.
ALLOWED_MODELS = {None, 'gpt-5.6-luna', 'deepseek-v4.1-flash-1017'}
SOURCES = [WORK / 'reused_translations.jsonl', WORK / 'luna_translation_results.jsonl',
           *sorted(WORK.glob('ds_*.jsonl'))]
MARKER = '[诊断探索合并'


def key(role, text):
    return hashlib.sha256(f'{role}\0{text}'.encode('utf-8')).hexdigest()


def read_jsonl(path):
    with path.open(encoding='utf-8', newline='') as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path, rows):
    with path.open('w', encoding='utf-8', newline='\n') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')


def chinese_dominant(item):
    # Source already carries Chinese prose; only identifiers/code stay in English.
    return bool(re.search(r'[\u4e00-\u9fff]', item['original_content']))


def load_translations(queue_keys):
    translations, provenance = {}, {}
    for path in SOURCES:
        if not path.exists():
            continue
        for item in read_jsonl(path):
            model = item.get('model')
            if item.get('translation_status') != 'translated' or item.get('translation_errors'):
                continue
            if model not in ALLOWED_MODELS:
                raise RuntimeError(f'rejected model in {path.name}: {model}')
            k = item['translation_key']
            if k not in queue_keys or k in translations:
                continue
            original, translated = item['original_content'], item['translated_content']
            if key(item['role'], original) != k:
                raise RuntimeError('translation key mismatch')
            if not translated.strip() or translated == original:
                continue
            translations[k] = translated
            provenance[k] = model or 'historical_cache'
    return translations, provenance


def load_queue():
    items = {}
    for name in ('translation_queue.jsonl', 'translation_queue_supplement.jsonl'):
        path = WORK / name
        if path.exists():
            for item in read_jsonl(path):
                items[item['translation_key']] = item
    return items


def main():
    queue_items = load_queue()
    translations, provenance = load_translations(set(queue_items))
    skipped = {k for k, item in queue_items.items() if k not in translations and chinese_dominant(item)}
    pending = set(queue_items) - skipped
    missing = pending - set(translations)
    if missing:
        raise RuntimeError(f'{len(missing)} translations still missing')
    removed, stats = [], {}
    for part in ('part_A', 'part_B'):
        src = ROOT / 'parts' / part / 'full_unreferenced_revisit' / 'candidate_records.jsonl'
        dest = ROOT / 'parts' / part / 'cleaned_candidate_v1'
        dest.mkdir(parents=True, exist_ok=True)
        outrows = []
        ps = {'records': 0, 'removed_summary_messages': 0,
              'translated_system_messages': 0, 'translated_assistant_messages': 0}
        for wrapper in read_jsonl(src):
            rec = wrapper['record']
            kept = []
            for index, message in enumerate(rec.get('messages', [])):
                role, text = message.get('role'), message.get('content')
                if role == 'assistant' and isinstance(text, str) and MARKER in text:
                    if message.get('tool_calls'):
                        raise RuntimeError(f"summary message contains tool_calls: {rec['id']}:{index}")
                    payload = json.dumps(message, ensure_ascii=False, separators=(',', ':'))
                    removed.append({'part': part, 'split': wrapper['split'], 'record_id': rec['id'],
                                    'message_index': index, 'message': message,
                                    'sha256': hashlib.sha256(payload.encode()).hexdigest()})
                    ps['removed_summary_messages'] += 1
                    continue
                if role in ('system', 'assistant') and isinstance(text, str):
                    k = key(role, text)
                    if k in pending:
                        message = {**message, 'content': translations[k]}
                        ps['translated_system_messages' if role == 'system'
                           else 'translated_assistant_messages'] += 1
                kept.append(message)
            outrows.append({'part': part, 'split': wrapper['split'], 'record': {**rec, 'messages': kept}})
            ps['records'] += 1
        write_jsonl(dest / 'candidate_records.jsonl', outrows)
        stats[part] = ps
    with gzip.open(WORK / 'removed_diagnostic_summary_messages.jsonl.gz', 'wt',
                   encoding='utf-8', newline='\n', compresslevel=6) as f:
        for item in removed:
            f.write(json.dumps(item, ensure_ascii=False, separators=(',', ':')) + '\n')
    if sum(v['records'] for v in stats.values()) != 4976:
        raise RuntimeError('unexpected record count')
    if not removed:
        raise RuntimeError('no diagnostic messages removed')
    if sum(v['removed_summary_messages'] for v in stats.values()) != len(removed):
        raise RuntimeError('summary count mismatch')
    for part in stats:
        for row in read_jsonl(ROOT / 'parts' / part / 'cleaned_candidate_v1' / 'candidate_records.jsonl'):
            for m in row['record']['messages']:
                if m.get('role') == 'assistant' and isinstance(m.get('content'), str) and MARKER in m['content']:
                    raise RuntimeError('diagnostic summary remains')
    prov = {}
    for v in provenance.values():
        prov[v] = prov.get(v, 0) + 1
    manifest = {'version': 'cleaned_candidate_v1', 'translation_provenance': prov,
                'rejected_models': ['gpt-6-sol'],
                'translation_items': len(queue_items), 'applied_translation_items': len(pending),
                'preserved_chinese_dominant_false_positives': len(skipped),
                'removed_summary_messages': len(removed), 'parts': stats,
                'review_state': 'requires_human_translation_review', 'replay_status': 'not_run',
                'sft_approved': False,
                'removed_messages_sidecar': 'translation_repair_v1/removed_diagnostic_summary_messages.jsonl.gz'}
    (WORK / 'apply_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    main()