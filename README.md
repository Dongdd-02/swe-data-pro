
## 一、协作分工

仓库结构：

```text
parts/
  part_A/                       part_B/（结构完全对称）
    original/                   train / validation / test
    focused_v2/                 train / validation / test
    focused_v2_metadata/        record_manifest + removed_exploration
    full_unreferenced_revisit/  candidate_records + 审计 sidecar
    cleaned_candidate_v1/       candidate_records（交付包来源）
code/                           23 个脚本
manifests/                      assignment / summary / verify / package_manifest
source_metadata/                上游来源与历史审计存档
focused_v2_metadata/            全量 focused_v2 的审计与 sidecar
translation_repair_v1/          翻译队列、模型输出、应用报告、否决隔离区
sft_merged_cleaned_zh_v1/       最终交付包（另有同名 ZIP）
```

可以把两部分合并放进一个仓库；这里的“合并”是**同仓库并列管理**，不是把 Part A/B 直接按文件顺序拼成一个未经排序的新数据文件。最终重组必须按 `manifests/assignment.jsonl` 中的 `split` 和 `source_line` 排序。

## 二、数据内容

- `original/`：原始轨迹的翻译版，合计 4,976 条；Part A 2,525 条、Part B 2,451 条，保留全部工具动作。
- `focused_v2/`：v2 版本（第一次压缩），动作 121,974。
- `full_unreferenced_revisit/`：v2 之后再压缩的版本，动作 116,375，附删除明细与审计 sidecar。
- `cleaned_candidate_v1/`：交付包来源，内容与 v2 之后版本逐条一致。
- 四个视图**当前全部为中文、全部无摘要标记**，详见第七节。
- 每个 part 的 `focused_v2_metadata/` 含该 part 的 `record_manifest.jsonl` 和 `removed_exploration.jsonl.gz`。
- 根目录 `focused_v2_metadata/` 保留完整候选的审计报告、完整清单和完整 sidecar。
- `manifests/assignment.jsonl` 记录每条轨迹的 part、原始行号以及两套数据行哈希；分配规则按 `record_id` 的 SHA-256 奇偶确定，重跑稳定。

### focused_v2 的处理方案

focused_v2 的目标是**减少冗余探索轮次，而不是裁剪保留工具回复正文**：

1. 只对当前规则识别出明确失败的轨迹做探索压缩；未识别出明确失败的轨迹保持原样。
2. 保留失败回显、错误信息、Edit/Write 修改、执行命令、重试动作和测试/验证动作及其完整工具输出。
3. 对失败前后的中间只读探索进行阶段化判断：保留每个文件的关键首尾读取、成功搜索结果、非读取工具动作和决策边界附近的探查。
4. 多个被判定为冗余的中间探索轮次由一条中文阶段摘要替代；摘要保留涉及路径、无结果搜索次数、部分搜索命中和未被后续动作覆盖的编号代码行。
5. 大文件缩略预览仅在同一阶段存在后续同文件定向 Read，且没有发现后续 Edit 所需旧代码片段缺失时，才作为冗余探索删除。
6. 删除的完整消息、工具调用和工具回显全部保存在 `removed_exploration.jsonl.gz`，可按 `record_id`、动作索引和消息区间追溯。

当前回退版本统计：4,976 条轨迹；工具动作从 128,700 减至 121,974，减少 6,726（5.2261%）；消息从 278,348 减至 267,055，减少 11,293（4.0578%）；消息正文字符减少 6.3175%。

## 三、GitHub 使用建议

本目录本身就是建议上传的 **GitHub 仓库根目录**，不需要先解压或重新合并数据。直接将本目录中的 `parts/`、`code/`、`manifests/`、审计资料、README 和 `.gitattributes` 一起提交即可；目录外生成的 Part A/B/shared ZIP 只是备份和传输文件，不是后续协作的必需内容。

1. 在 GitHub 新建一个私有仓库，将本目录内容作为仓库根目录提交。
2. 先提交基线并创建保护标签，例如 `focused-v2-baseline`；基线数据不要在 `main` 上直接覆盖。
3. 启用 Git LFS。普通 GitHub 单文件上限为 100 MB，JSONL 和 gzip sidecar 应使用 LFS；本包已提供 `.gitattributes`。ZIP 不需要上传到仓库，除非你们另有归档需求。
4. 同事只在 `review/part-a` 修改 Part A；你只在 `review/part-b` 修改 Part B。每次修改说明 record_id、修改原因和是否影响 focused_v2 主链。
5. PR 合并前运行：

```bash
python code/verify_swe_collaboration.py --root .
```

校验两部分是否覆盖全部轨迹、是否重复/遗漏，以及每个 part 的 original/focused_v2 ID 是否对齐。

6. 最终合并数据时，以 `manifests/assignment.jsonl` 的 `source_line` 排序重建 train/validation/test；不要简单先拼 Part A 再拼 Part B。

## 四、全量 Part A 语义压缩候选

`parts/part_A/full_unreferenced_revisit/` 是在 `focused_v2` 之上的独立全量候选视图，不覆盖 `focused_v2`。它覆盖 Part A 的 train、validation、test 共 2,525 条轨迹：先用本地规则筛出完整单调用 Read/静态只读 Bash，再由强模型判断后文是否真正使用、删除后助手诊断是否完整，最后通过精确子序列和工具闭环审计。

本轮共复审 3,603 个候选动作，覆盖 2,145 条轨迹；1,978 条轨迹产生候选删除，共删除 2,877 个动作。Part A 动作从 62,039 减至 59,162，消息从 135,851 减至 130,097。结构审计和协作分片审计均为 0 错误。

其中真正的测试/验证执行、修改、写入、失败和唯一诊断证据受保护；读取测试源码本身不等于运行测试，静态 `cd ... && grep` 也可以进入候选。所有删除动作写入 `removed_unreferenced_actions.jsonl.gz`，候选状态保持 `candidate_pending_human_review`，不代表 replay 成功或已批准训练。

运行和审计：

```bash
python code/full_part_a_unreferenced.py --part part_A --workers 4
python code/audit_full_part_a_unreferenced.py --part part_A --root .
python code/full_part_a_unreferenced.py --part part_B --workers 4
python code/audit_full_part_a_unreferenced.py --part part_B --root .
python code/verify_swe_collaboration.py --root .
```

`full_unreferenced_revisit/` 的结果不应与前三轮目录合并覆盖；如需比较，应以 `focused_v2` 为共同基线。

## 五、全量 Part B 语义压缩候选

`parts/part_B/full_unreferenced_revisit/` 是在 Part B `focused_v2` 之上的独立全量候选视图，不覆盖 Part B 基线、Part A 全量结果或任何原始数据。它覆盖 train、validation、test 共 2,451 条轨迹，沿用 Part A 的本地预筛、强模型判断、确定性安全门槛、精确子序列和工具闭环审计。

本轮共复审 3,491 个候选动作，覆盖 2,073 条轨迹；2,451 条候选记录全部完成，1,867 条产生候选删除，共删除 2,722 个动作。Part B 动作从 59,935 减至 57,213，消息从 131,204 减至 125,760；分片删除为 train 2,448、validation 145、test 129。结构审计为 `structural_audit_passed_pending_human_review`，0 个错误。

其中 1 条轨迹因模型请求触发安全策略而采用保守全保留回退，没有删除任何动作；该回退已记录在 `model_decisions.jsonl`，不影响结构闭环。所有删除动作写入 `removed_unreferenced_actions.jsonl.gz`；候选仍需人工语义审阅和 replay，不代表已批准训练。

人工抽检入口：打开 `parts/part_B/full_unreferenced_revisit/HUMAN_REVIEW_GUIDE.md`，按固定种子生成的 `human_review_sample.csv` 检查删除动作。本次抽取 94 条轨迹（train 84、validation 5、test 5），共 143 个删除动作；这是风险抽检，不代表未抽样删除已经确认安全。只有完成人工处置、生成独立 reviewed 版本并重跑结构审计后，才考虑用于 SFT；训练只用 train，validation/test 必须保持隔离。当前压缩候选尚未 replay，不是已批准的训练发布版。

运行和审计：

```bash
python code/full_part_a_unreferenced.py --part part_B --workers 4
python code/audit_full_part_a_unreferenced.py --part part_B --root .
python code/verify_swe_collaboration.py --root .
```

## 六、Part A+B 清理版（中文全量，摘要消息已删除）

`sft_merged_cleaned_zh_v1/` 与同名 ZIP 是在 Part A/B `full_unreferenced_revisit` 之上再做的**清理候选**。

本轮做三件事：

1. **删除独立诊断摘要消息**：凡整条 assistant 消息正文包含 `[诊断探索合并]` 标记的，整条删除，共 2,159 条（Part A 1,122、Part B 1,037）。这些消息均不含 `tool_calls`，删除后工具调用与 `tool` 回复仍一一对应；原文完整保存在 `REMOVED_DIAGNOSTIC_SUMMARIES.jsonl.gz`。
2. **同步翻译**：`system` 与 `assistant` 的自然语言统一译为中文，工具消息、参数、代码块、行内代码、URL、路径、报错原文保持逐字节不变。共 6,587 个唯一文本，映射到 9,931 个消息位置（system 1,440、assistant 8,491）。
3. **合并**：按 `manifests/assignment.jsonl` 的 `split` 和 `source_line` 重建，共 4,976 条；train / validation / test = 4,474 / 251 / 251。

译文来源可追溯：`deepseek-v4.1-flash-1017` 6,196 条、历史已验证缓存 301 条、`gpt-5.6-luna` 78 条；用户已否决的 `gpt-6-sol` 结果被隔离在 `translation_repair_v1/discarded_gpt6sol/`，构建脚本遇到该模型直接报错终止，不会混入数据。

另有 95 条原本就是中文、仅夹带英文标识符或代码的文本按原文保留，单独记入 `apply_manifest.json` 的 `preserved_chinese_dominant_false_positives`。

运行：

```bash
python code/prepare_translation_repair_v1.py
python code/apply_translation_repair_v1.py
python code/audit_full_part_a_unreferenced.py --part part_A --root .
python code/audit_full_part_a_unreferenced.py --part part_B --root .
python code/finalize_sft_cleanup_v1.py
python code/publish_v2_views_zh_v1.py
python code/translate_baselines_zh_v1.py part_A/original part_B/original
python code/refresh_manifests_v1.py
```

注意：`apply_translation_repair_v1.py` 与 `finalize_sft_cleanup_v1.py` 依赖 `[诊断探索合并]` 标记，而四份视图已把摘要删净，**这两步不能再原地重跑**；需要重跑请先从仓库外备份恢复英文输入（见第七节）。

审计状态：两个 part 结构审计均 `structural_audit_passed_pending_human_review`、0 错误；清理后残留 `[诊断探索合并]` 为 0 条，纯英文 assistant 叙述为 0 条。

**该数据仍是候选**：`review_state=translation_requires_human_review`、`replay_status=not_run`、`sft_approved=false`。翻译需人工抽检，仓库 replay 未运行；训练只使用 train，validation/test 必须保持隔离。

原未翻译候选 `sft_merged_processed_candidate_20261104/` 和同名 ZIP 已备份到仓库外的 `D:\code_codex\deliverables\swe_sft_4976_pretranslation_backup_20261104/`；原位置现已覆盖为与 `sft_merged_cleaned_zh_v1/` 相同的清理中文版（均为候选）。为避免混淆，建议直接使用名称明确的 `sft_merged_cleaned_zh_v1.zip`。

## 七、`parts/` 各视图当前状态

四份视图**全部为中文、全部无摘要标记**，且各自保留本轮的压缩层级：

| 视图 | Part A | Part B | 含义 |
|---|---|---|---|
| `original/` | 2,525 条 / 65,503 动作 | 2,451 条 / 63,197 动作 | 原始轨迹，**全部动作** |
| `focused_v2/` | 2,525 条 / 62,039 动作 | 2,451 条 / 59,935 动作 | **v2**：第一次压缩（121,974 动作） |
| `full_unreferenced_revisit/` | 2,525 条 / 59,162 动作 | 2,451 条 / 57,213 动作 | **v2 之后再压缩**（116,375 动作） |
| `cleaned_candidate_v1/` | 2,525 条 / 59,162 动作 | 2,451 条 / 57,213 动作 | 交付包来源，内容与 v2 之后版本相同 |

各视图纯英文 `system`/`assistant` 叙述 0 条、`[诊断探索合并]` 残留 0 条、工具闭环错误 0 条。译文条数（按覆盖前备份逐条比对得出）：`focused_v2` A 4,818 / B 5,522，`full_unreferenced_revisit` A 4,631 / B 5,300；删除摘要 A 1,122 / B 1,037（两份视图各一次）。其中 A 15 条、B 8 条是中英混排消息（句子里夹少量汉字），也按译文映射替换，避免与交付包出现差异。

v2 与 v2 之后的差距就是第二次压缩删掉的 **A 2,877 / B 2,722 个动作**（合计 5,599），删除明细在 `full_unreferenced_revisit/removed_unreferenced_actions.jsonl.gz`。

运行：

```bash
python code/publish_v2_views_zh_v1.py                  # 两份视图就地翻译 + 删摘要 + 校验
python code/translate_baselines_zh_v1.py part_A/original part_B/original
```

三点必须知道：

1. **英文原文只存在于仓库外的备份**：`D:\code_codex\deliverables\swe_sft_4976_prebaseline_backup_20261105\`（21 个文件、1,378 MB）。四份视图都已就地改写为中文，仓库内不再有英文本。
2. **合并包不能再原地重跑**：`apply_translation_repair_v1.py` 需要输入里的 `[诊断探索合并]` 标记来产生删除记录，现在四份视图的标记都是 0，重跑会因「找不到标记」终止。需要重跑请从上述备份恢复输入。摘要原文完整保存在 `translation_repair_v1/removed_diagnostic_summary_messages.jsonl.gz`（2,159 条）。
3. `cleaned_candidate_v1/` 与 `full_unreferenced_revisit/` 现在逐条哈希相等（Part A/B 差异记录均为 0）。保留前者是因为交付包 `sft_merged_cleaned_zh_v1.zip` 由它生成，名字也能直接对应产物。

`full_unreferenced_revisit/` 里的审计 sidecar（`removed_unreferenced_actions.jsonl.gz`、`model_decisions.jsonl`、`selection.jsonl`、`record_index.jsonl`、README、`HUMAN_REVIEW_GUIDE.md`、`human_review_sample.csv`）未被改动。

三代试点目录 `review_v3_pilot/`（50 条）、`review_v3_pre_failure_revisit/`（37 条）、`review_v3_unreferenced_revisit/`（12 条）已从 `part_A/` 移除，两个 part 目录结构因此对称。这 99 条是未通过试验的历史产物、仍是英文、未参与本次翻译与合并；完整副本在仓库外 `D:\code_codex\deliverables\swe_sft_4976_pilot_backup_20261105\`（24 个文件、15.31 MB），生成脚本 `pilot_*.py` 仍在 `code/` 下。

`part_B/full_unreferenced_revisit/` 比 Part A 多 `HUMAN_REVIEW_GUIDE.md` 与 `human_review_sample.csv`（5,749 行），是 Part B 独立人工抽检的凭证，保留。
