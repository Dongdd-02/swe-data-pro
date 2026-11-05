# Full Part A Unreferenced Revisit

这是在 `parts/part_A/focused_v2/` 之上的独立全量语义压缩候选，不覆盖基线，也不修改 Part B。

## Scope

- Source: Part A `focused_v2`
- Records: 2,525
- Splits: train 2,290 / validation 115 / test 120
- Prefilter targets: 3,603 actions across 2,145 records
- Strong-model review: all 3,603 targets reviewed
- Changed records: 1,978
- Removed actions: 2,877
- Actions: 62,039 -> 59,162
- Messages: 135,851 -> 130,097
- Replay: not run
- Review state: pending human signoff

## Rule

The local prefilter selected complete single-call `Read` and static read-only `Bash` actions with no detected failure output and no exact later reference to their path or search term. The strong model then judged whether the action was semantically unreferenced, non-unique evidence, and removable without breaking the narrative.

The deterministic gate protected modifications, writes, test/verification execution, nonzero/failure output, unique diagnostic evidence, incomplete calls, and low-confidence decisions. Reading a test source file is not test execution. Static `cd ... && grep` navigation is not dynamic execution.

A candidate is only an exact ordered subsequence of `focused_v2`. No assistant text, tool arguments, or retained tool replies are rewritten. Every removed action is recoverable from `removed_unreferenced_actions.jsonl.gz`.

## Files

- `selection.jsonl`: exact prefilter target actions.
- `record_index.jsonl`: all Part A records and target indices.
- `model_decisions.jsonl`: per-record evaluations and gate metadata.
- `candidate_records.jsonl`: complete Part A candidate view in source order.
- `removed_unreferenced_actions.jsonl.gz`: lossless removed source chunks.
- `independent_audit.json`: generalized structural audit.
- `runner_summary.json`: run statistics and status.

## Verification

The structural audit passed with zero errors. The collaboration split audit passed with 4,976 records and no assignment errors. These checks prove data integrity and trace preservation only; they do not prove the underlying repository repairs or candidate task success. Human causal review and repository replay remain required before training approval.
