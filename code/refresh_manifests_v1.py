#!/usr/bin/env python3
"""Refresh repository manifests and checksums after the cleanup merge."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_NAMES = {'SHA256SUMS.txt', 'package_manifest.json'}


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def collect(root):
    rows = []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.name in SKIP_NAMES:
            continue
        rows.append({'path': str(path.relative_to(root)).replace('\\', '/'),
                     'bytes': path.stat().st_size, 'sha256': sha256(path)})
    return rows


def write_sums(path, rows):
    path.write_text(''.join(f"{r['sha256']}  {r['path']}\n" for r in rows), encoding='utf-8')


def main():
    manifest_path = ROOT / 'manifests' / 'package_manifest.json'
    previous = json.loads(manifest_path.read_text(encoding='utf-8'))
    files = collect(ROOT)
    manifest = {'files': files, 'assignment': previous['assignment']}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    write_sums(ROOT / 'SHA256SUMS.txt', files)
    part_b = ROOT / 'parts' / 'part_B'
    if part_b.is_dir():
        write_sums(part_b / 'SHA256SUMS.txt', collect(part_b))
    print(json.dumps({'files': len(files), 'sha256sums_lines': len(files),
                      'part_b_sums': len(collect(part_b)) if part_b.is_dir() else 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()