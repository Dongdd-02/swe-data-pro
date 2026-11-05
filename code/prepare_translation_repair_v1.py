#!/usr/bin/env python3
"""Build a deduplicated queue for English prose missed in SWE translation."""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STOP = set("the a an and or but if then else when while where which who whom this that these those it its they them their we us our you your i me my he she his her is are was were be been being have has had do does did can could would should will may might must not no to of in on at by for from with as into than after before over under between through during because so also only such any all each every other same more most very too just about use using used make made let lets now first second next finally looks seem seems appears found issue problem need needs work works file files method function command output result results line lines error run running please together however therefore previous replace call".split())
PATTERN = re.compile(r"[A-Za-z]{3,}")


def queue_key(role: str, text: str) -> str:
    return hashlib.sha256(f"{role}\0{text}".encode("utf-8")).hexdigest()


def is_summary(text: str) -> bool:
    return "[诊断探索合并：" in text or "[诊断探索合并:" in text


def english_prose(text: str) -> bool:
    words = PATTERN.findall(text)
    low = {w.lower() for w in words}
    # Avoid source-code excerpts: they are evidence, not assistant prose.
    numbered = sum(bool(re.match(r"^\s*\d+\t", line)) for line in text.splitlines())
    if numbered >= 3:
        return False
    residual = text
    residual = re.sub(r"```[\s\S]*?```", " ", residual)
    residual = re.sub(r"`[^`\n]*`", " ", residual)
    residual = re.sub(r"https?://\S+", " ", residual)
    residual = re.sub(r"\b[A-Za-z]:\\[^\s]+", " ", residual)
    words = PATTERN.findall(residual)
    hits = sum(w.lower() in STOP for w in words)
    return len(words) >= 8 and hits >= 4 and hits / len(words) >= 0.18


def main():
    out = ROOT / "translation_repair_v1"
    out.mkdir(parents=True, exist_ok=True)
    candidates = {}
    occurrences = []
    source_counts = {"summary_messages": 0, "english_assistant_messages": 0, "english_system_messages": 0}
    for part in ("part_A", "part_B"):
        src = ROOT / "parts" / part / "full_unreferenced_revisit" / "candidate_records.jsonl"
        with src.open(encoding="utf-8", newline="") as f:
            for line in f:
                if not line.strip():
                    continue
                wrapper = json.loads(line)
                rec = wrapper["record"]
                for index, message in enumerate(rec.get("messages", [])):
                    role, text = message.get("role"), message.get("content")
                    if not isinstance(text, str):
                        continue
                    if role == "assistant" and is_summary(text):
                        source_counts["summary_messages"] += 1
                    eligible = role == "system" and bool(re.search(r"\bYou are a helpful software-engineering assistant\b", text, re.I))
                    if role == "assistant" and not is_summary(text):
                        eligible = english_prose(text)
                    if not eligible:
                        continue
                    source_counts["english_system_messages" if role == "system" else "english_assistant_messages"] += 1
                    key = queue_key(role, text)
                    if key not in candidates:
                        candidates[key] = {"episode_id": f"cleanup_{key}", "message_index": 0, "source_id": "swe_smith_pangu_cleanup_v1", "role": role, "original_content": text, "original_content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "translation_key": key, "occurrence_count": 0}
                    candidates[key]["occurrence_count"] += 1
                    occurrences.append({"part": part, "record_id": rec["id"], "message_index": index, "role": role, "original_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "translation_key": key})
    queue = out / "translation_queue.jsonl"
    with queue.open("w", encoding="utf-8", newline="\n") as f:
        for item in sorted(candidates.values(), key=lambda x: x["translation_key"]):
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    mapping = out / "occurrence_mapping.jsonl"
    with mapping.open("w", encoding="utf-8", newline="\n") as f:
        for item in occurrences:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    (out / "queue_manifest.json").write_text(json.dumps({"queue_items": len(candidates), "occurrences": len(occurrences), "source_counts": source_counts, "queue": queue.name, "mapping": mapping.name, "technical_content_policy": "preserve original technical spans using translate_semantic_queue.py validation"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"queue_items": len(candidates), "occurrences": len(occurrences), "source_counts": source_counts, "output": str(out)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
