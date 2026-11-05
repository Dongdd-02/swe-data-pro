# Part A+B 清理版 SFT 候选

本包按 `manifests/assignment.jsonl` 的 split 与 source_line 顺序合并 Part A/B 清理候选。

- 记录：4976
- train / validation / test：4474 / 251 / 251
- 已删除独立 `[诊断探索合并]` assistant 消息：2159 条；原文保存在 `REMOVED_DIAGNOSTIC_SUMMARIES.jsonl.gz`。
- system/assistant 英文翻译：6587 个唯一文本映射到 9931 个消息位置。

该数据是清理候选，翻译尚需人工抽检，仓库 replay 未运行，尚未获 SFT 正式批准。训练只使用 train；validation/test 保持隔离。
