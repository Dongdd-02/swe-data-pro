# Full Part B Unreferenced Revisit

这是在 `parts/part_B/focused_v2/` 之上的独立全量语义压缩候选，不覆盖基线、Part A 全量候选或原始数据。

## Scope

- Source: Part B `focused_v2`
- Records: 2,451
- Splits: train 2,184 / validation 136 / test 131
- Prefilter targets: 3,491 actions across 2,073 records
- Completed candidate records: 2,451; model/audit errors: 0
- Changed records: 1,867; removed actions: 2,722
- Actions: 59,935 → 57,213; messages: 131,204 → 125,760
- Split removals: train 2,448; validation 145; test 129
- Strong-model review: completed for all selected targets; one cyber-policy refusal used a conservative keep-all fallback
- Structural audit: passed with 0 errors
- Human review sample: 94 trajectories / 143 removed actions (5% stratified by split); see `human_review_sample.csv` and `HUMAN_REVIEW_GUIDE.md`
- Replay: not run
- Review state: pending human signoff

## Rule

The local prefilter selects complete single-call `Read` and static read-only `Bash` actions with no detected failure output and no exact later reference to their path or search term. The strong model judges semantic non-use, evidence uniqueness, narrative completeness, and confidence.

The deterministic gate protects modifications, writes, test/verification execution, nonzero/failure output, unique diagnostic evidence, incomplete calls, and low-confidence decisions. Reading a test source file is not test execution. Static `cd ... && grep` navigation is not dynamic execution.

Every candidate is an exact ordered subsequence of `focused_v2`; retained assistant text, tool arguments, and tool replies are unchanged. Removed actions are recoverable from `removed_unreferenced_actions.jsonl.gz`.

## Files

- `selection.jsonl`: exact prefilter target actions.
- `record_index.jsonl`: all Part B records and target indices.
- `model_decisions.jsonl`: per-record evaluations and gate metadata.
- `candidate_records.jsonl`: complete Part B candidate view in source order.
- `removed_unreferenced_actions.jsonl.gz`: lossless removed source chunks.
- `independent_audit.json`: generalized structural audit.
- `runner_summary.json`: run statistics and status.
- `human_review_sample.csv`: deterministic 5% stratified sample of changed records; one row per deleted action.
- `HUMAN_REVIEW_GUIDE.md`: review criteria, escalation, recovery, and SFT gating.

The candidate remains `candidate_pending_human_review` for changed records. Structural validation proves data integrity and trace preservation only; it does not certify repository repair success or training readiness.
