#!/usr/bin/env python3
"""Package translated SWE source and focused-v2 candidate for two-person review.

The split is deterministic by record_id SHA-256 parity. Each part contains the
same record subset in both original and focused-v2 form, plus the focused-v2
sidecar and manifest entries needed to inspect/reconstruct removed actions.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

SPLITS = ("train.jsonl", "validation.jsonl", "test.jsonl")
CODE_FILES = (
    "compress_swe_failure_repair_conservative.py",
    "compress_swe_failure_repair_stage_summary.py",
    "compress_swe_failure_repair_focused.py",
    "audit_swe_failure_repair_focused.py",
    "package_swe_collaboration.py",
    "verify_swe_collaboration.py",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def part_for(record_id: str) -> str:
    return "part_A" if int.from_bytes(hashlib.sha256(record_id.encode("utf-8")).digest()[:8], "big") % 2 == 0 else "part_B"


def read_lines(path: Path) -> list[tuple[int, bytes, dict]]:
    result = []
    with path.open("rb") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            result.append((line_no, raw, json.loads(raw.decode("utf-8"))))
    return result


def write_json_line(handle, obj):
    handle.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")


def copy_metadata(src: Path, dst: Path, excluded: set[str]) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir()):
        if item.is_file() and item.name not in excluded:
            shutil.copy2(item, dst / item.name)


def hash_manifest(root: Path) -> list[dict]:
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {"SHA256SUMS.txt"}:
            rows.append({"path": str(path.relative_to(root)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_bytes(path.read_bytes())})
    return rows


def build(source: Path, focused: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    output.mkdir(parents=True)
    for part in ("part_A", "part_B"):
        for version in ("original", "focused_v2"):
            (output / "parts" / part / version).mkdir(parents=True)
        (output / "parts" / part / "focused_v2_metadata").mkdir(parents=True)
    (output / "manifests").mkdir()
    (output / "code").mkdir()
    (output / "source_metadata").mkdir()
    (output / "focused_v2_metadata").mkdir()

    assignments = {}
    stats = Counter()
    part_stats = {part: Counter() for part in ("part_A", "part_B")}
    for split in SPLITS:
        source_rows = read_lines(source / split)
        focused_rows = read_lines(focused / split)
        source_by_id = {row[2]["id"]: row for row in source_rows}
        focused_by_id = {row[2]["id"]: row for row in focused_rows}
        if set(source_by_id) != set(focused_by_id):
            raise ValueError(f"record IDs differ in {split}")
        source_handles = {}
        focused_handles = {}
        try:
            for part in ("part_A", "part_B"):
                source_handles[part] = (output / "parts" / part / "original" / split).open("wb")
                focused_handles[part] = (output / "parts" / part / "focused_v2" / split).open("wb")
            focused_line_no = {row[2]["id"]: row[0] for row in focused_rows}
            for source_line_no, source_raw, source_obj in source_rows:
                rid = source_obj["id"]
                part = part_for(rid)
                _, focused_raw, focused_obj = focused_by_id[rid]
                source_handles[part].write(source_raw)
                focused_handles[part].write(focused_raw)
                key = (split, rid)
                assignments[key] = {"split": split, "record_id": rid, "part": part, "source_line": source_line_no, "focused_line": focused_line_no[rid], "source_line_sha256": sha256_bytes(source_raw.rstrip(b"\r\n")), "focused_line_sha256": sha256_bytes(focused_raw.rstrip(b"\r\n"))}
                stats["records"] += 1
                part_stats[part][split] += 1
        finally:
            for handle in list(source_handles.values()) + list(focused_handles.values()):
                handle.close()

    assignment_text = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in sorted(assignments.values(), key=lambda item: (item["split"], item["source_line"])))
    (output / "manifests" / "assignment.jsonl").write_text(assignment_text, encoding="utf-8")

    # Partition focused-v2 audit manifest and lossless removed-action sidecar.
    manifest_paths = {"part_A": (output / "parts" / "part_A" / "focused_v2_metadata" / "record_manifest.jsonl").open("w", encoding="utf-8"), "part_B": (output / "parts" / "part_B" / "focused_v2_metadata" / "record_manifest.jsonl").open("w", encoding="utf-8")}
    try:
        with (focused / "record_manifest.jsonl").open(encoding="utf-8") as handle:
            for raw in handle:
                item = json.loads(raw)
                manifest_paths[assignments[item["split"], item["record_id"]]["part"]].write(raw)
    finally:
        for handle in manifest_paths.values():
            handle.close()
    sidecar_paths = {"part_A": gzip.open(output / "parts" / "part_A" / "focused_v2_metadata" / "removed_exploration.jsonl.gz", "wt", encoding="utf-8"), "part_B": gzip.open(output / "parts" / "part_B" / "focused_v2_metadata" / "removed_exploration.jsonl.gz", "wt", encoding="utf-8")}
    try:
        with gzip.open(focused / "removed_exploration.jsonl.gz", "rt", encoding="utf-8") as handle:
            for raw in handle:
                item = json.loads(raw)
                part = assignments[item["split"], item["record_id"]]["part"]
                sidecar_paths[part].write(raw)
    finally:
        for handle in sidecar_paths.values():
            handle.close()

    # Keep complete reports and the complete focused sidecar/manifest in shared metadata.
    copy_metadata(source, output / "source_metadata", set(SPLITS))
    copy_metadata(focused, output / "focused_v2_metadata", set(SPLITS))
    for name in ("record_manifest.jsonl", "removed_exploration.jsonl.gz"):
        shutil.copy2(focused / name, output / "focused_v2_metadata" / name)
    code_root = Path(__file__).resolve().parent
    for name in CODE_FILES:
        shutil.copy2(code_root / name, output / "code" / name)

    assignment_rows = list(assignments.values())
    assignment_summary = {"records": len(assignment_rows), "parts": {part: {"train.jsonl": part_stats[part]["train.jsonl"], "validation.jsonl": part_stats[part]["validation.jsonl"], "test.jsonl": part_stats[part]["test.jsonl"]} for part in ("part_A", "part_B")}, "rule": "part_A iff int.from_bytes(SHA256(record_id)[:8], big) % 2 == 0; otherwise part_B", "source": str(source), "focused_v2": str(focused)}
    (output / "manifests" / "assignment_summary.json").write_text(json.dumps(assignment_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / ".gitattributes").write_text("*.jsonl filter=lfs diff=lfs merge=lfs -text\n*.jsonl.gz filter=lfs diff=lfs merge=lfs -text\n*.zip filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")
    (output / "README.md").write_text(f"""# 中文 SWE 失败恢复数据：GitHub 双人协作包

本包回退到 `swe_sft_4976_zh_failure_repair_focused_v2_20261103`，不是 17.59% 的 dense 工具回显裁剪版，也不是只合并 0.0173% 搜索调用版。

## 数据

- `parts/part_A/original/` 与 `parts/part_B/original/`：最终已翻译的原始数据，合计 4,976 条轨迹。
- `parts/part_A/focused_v2/` 与 `parts/part_B/focused_v2/`：当前回退版本，保留失败、修改、执行和验证主链；中间冗余探索被阶段摘要合并。
- 每个 part 的 `focused_v2_metadata/` 含该 part 的 `record_manifest.jsonl` 和 `removed_exploration.jsonl.gz`；根目录 `focused_v2_metadata/` 还保留完整候选的审计报告、完整清单和完整 sidecar。
- `manifests/assignment.jsonl` 记录每条轨迹属于哪个 part、原始行号和两套数据行哈希。按 `record_id` 的 SHA-256 奇偶确定分片，重跑时稳定。

当前回退版本原始统计：4,976 条轨迹；工具动作从 128,700 减至 121,974，减少 6,726（5.2261%）；消息从 278,348 减至 267,055，减少 11,293（4.0578%）；消息正文字符减少 6.3175%。

## 双人协作建议

- 你处理 `part_A`，同事处理 `part_B`。两边每个 part 都同时有 original 和 focused_v2，便于对照审阅。
- 建议把 `code/`、`manifests/`、README 和审计资料放进 Git 普通仓库；JSONL、gzip sidecar 和 ZIP 使用 Git LFS。普通 GitHub 单文件 100 MB 限制，不能直接把大 JSONL 当普通 Git blob 推送。
- 协作修改后运行 `python code/verify_swe_collaboration.py --root .`，检查两部分是否覆盖全部原始轨迹、是否存在重复/遗漏，以及每个 part 的 original/focused_v2 ID 对齐。
- 合并时以 `manifests/assignment.jsonl` 的 `source_line` 排序重建，不要简单先拼 A 再拼 B。

## 重要边界

这是候选数据，不是已批准的正式 Pangu SFT 数据。focused_v2 仍需人工语义审阅、仓库 replay、Pangu tokenizer/chat template 和实际训练验证。
""", encoding="utf-8")

    for part in ("part_A", "part_B"):
        (output / "parts" / part / "README.md").write_text(f"# {part}\n\n本目录包含该分片的 original 与 focused_v2 数据，以及 focused_v2 的分片 sidecar/manifest。记录分配由根目录 manifests/assignment.jsonl 定义。不要把本分片单独当作完整数据集。\n", encoding="utf-8")
        lines = []
        for path in sorted((output / "parts" / part).rglob("*")):
            if path.is_file() and path.name != "SHA256SUMS.txt":
                lines.append(f"{sha256_bytes(path.read_bytes())}  {path.relative_to(output / 'parts' / part).as_posix()}\n")
        (output / "parts" / part / "SHA256SUMS.txt").write_text("".join(lines), encoding="utf-8")

    root_lines = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name not in {"SHA256SUMS.txt"}:
            root_lines.append(f"{sha256_bytes(path.read_bytes())}  {path.relative_to(output).as_posix()}\n")
    (output / "SHA256SUMS.txt").write_text("".join(root_lines), encoding="utf-8")
    (output / "manifests" / "package_manifest.json").write_text(json.dumps({"files": hash_manifest(output), "assignment": assignment_summary}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return assignment_summary


def make_zip(folder: Path, zip_path: Path, top_name: str) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, Path(top_name) / path.relative_to(folder))
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError(f"zip integrity failed: {zip_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--focused", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = build(args.source, args.focused, args.output)
    for part in ("part_A", "part_B"):
        make_zip(args.output / "parts" / part, args.output.parent / f"{args.output.name}_{part}.zip", part)
    make_zip(args.output / "code", args.output.parent / f"{args.output.name}_code.zip", "code")
    print(json.dumps(summary, ensure_ascii=False))
