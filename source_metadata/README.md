# SWE-smith Pangu trace-only staging: 4,976 records

This package preserves the existing 2,251-row staging and appends 2,725 newly selected SWE-smith trajectories. The appended rows have passed tool-protocol, semantic translation, and record-structure audits.

## Composition

- Existing staging preserved: 2,251
- Added extended review tier requiring replay: 1,630
- Added filter-excluded tier requiring replay: 1,095
- Total: 4,976

## Status

This is trace-only staging, not a production-ready training set. Independent repository replay is not run; Pangu tokenizer/chat-template validation is not run; license review is pending; final splits are not repository-disjoint; and production admission is false. The 1,095-row filter-excluded tier is lower confidence and must remain explicitly separated.

See `FINAL_STATUS.json` and `provenance.jsonl` for record-level origin and replay status.

## Included audit files

- `SOURCE_SELECTION_REPORT.json`: 2,725-row extension selection and three-key deduplication report.
- `BATCH4_TOOL_PROTOCOL_AUDIT.json`: tool protocol and closure audit for the extension.
- `BATCH4_SEMANTIC_TRANSLATION_AUDIT.json`: protected-token and semantic translation audit.
- `BATCH4_SFT_AUDIT.json`: model-facing export audit for the extension.
- `sft_contract_audit.json`: final 4,976-row model-facing contract audit.
- `FINAL_INTEGRITY_AUDIT.json`: final ID, provenance, message-hash, and base-preservation audit.
- `TRANSLATION_REPAIR_AUDIT.json`: exact repair audit for the 78 quality-retry items.
