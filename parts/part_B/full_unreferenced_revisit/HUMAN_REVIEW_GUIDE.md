# Part B 人工抽检与 SFT 准入指南

## 当前状态

`full_unreferenced_revisit/` 是压缩候选，不是已经批准训练的数据。结构审计只证明记录、调用闭环、消息子序列和删除 sidecar 一致；语义删除仍需人工判断。本目录不包含仓库 replay 结果，也没有声称代码修复成功。

候选基线为 Part B `focused_v2`。全量共 2,451 条轨迹，3,491 个预筛动作；2,722 个动作被候选删除，分布在 1,867 条轨迹。删除比例较小，但每个删除动作仍可能包含有用的错误上下文或调查证据。

## 抽检文件

- `human_review_sample.csv`：按 split 分层、固定种子抽取有删除轨迹的 5%，每条抽中轨迹的所有删除动作均列为独立行。本次为 train 84 条、validation 5 条、test 5 条，共 94 条轨迹和 143 个动作。
- `model_decisions.jsonl`：逐轨迹模型判断、理由和动作索引。
- `removed_unreferenced_actions.jsonl.gz`：删除动作的完整原始消息，可无损恢复。
- `candidate_records.jsonl`：本轮候选轨迹；需与同 ID 的 Part B `focused_v2` 基线对照。

抽样可复现：

```bash
python code/build_part_b_human_review_sample.py --root . --fraction 0.05
```

脚本使用固定种子 `part-b-full-unreferenced-review-v1`，按 train/validation/test 分层，并按轨迹 ID 的 SHA-256 顺序取样。改变 `--fraction` 可生成不同覆盖比例的队列。

## 如何审阅每一行

1. 先按 `record_id` 找到完整源轨迹和候选轨迹，不要只凭 CSV 中的截断摘录下结论。源记录在 `parts/part_B/focused_v2/<split>`，候选在本目录的 `candidate_records.jsonl`；完整删除消息在 sidecar，按 `record_id` 与 `action_index` 定位。
2. 阅读被删动作之前和之后的助手内容，理解该动作在当时是为了解决什么问题。CSV 的 `tool_reply_excerpt` 可能被截断，不能代替完整工具输出。
3. 判断被删的 Read/Bash 输出是否包含后续决策所需的信息：错误文本、环境/路径、搜索命中、版本信息、失败与否、代码行或测试线索。即使后文没有原样引用，也可能是助手推理的依据。
4. 检查删除后叙事是否自然连贯，是否会让后续诊断、修改或测试像是“凭空出现”。若依赖关系不明确，判为不确定而不是接受删除。
5. 在 `human_verdict` 填 `accept_delete`、`restore` 或 `uncertain`；在 `review_notes` 记录具体证据。若恢复，填 `restore_action` 为 `yes`。不要直接改写基线或覆盖候选文件；保留审核表和 sidecar，后续构建经审核版本时按记录 ID/动作索引从原轨迹恢复。

建议重点关注：失败附近的 Bash 输出、成功搜索结果、测试前的环境检查、后续虽未精确引用但可能影响选择的代码读取，以及助手在被删动作前后对调查阶段的解释。

## 抽检结果如何使用

这是一个风险抽检，不是自动验收。若发现任何“删除后丢失关键错误/环境/代码证据”或“后续步骤失去因果依据”的误删：

- 记录样本中的 record ID、动作索引、误删类型和原文证据；
- 扩大同一 split 及相同工具/内容类型的抽样，必要时对相关类别全量复核；
- 在生成审核版时恢复误删动作，并重新运行结构审计；
- 在审核结论前，不要把未审核的全量候选称为已通过人工 review。

抽检中未发现问题只能降低风险，不能证明其余未抽样动作全部安全。团队应先确定可接受的误删阈值和扩样规则，并记录审核人、日期、样本范围、判定数及发现的问题。

## SFT 使用前的硬性检查

1. 人工审核形成明确结论；所有 `restore` 和 `uncertain` 项得到处置，保留带审核标记的记录及其版本哈希。
2. 从本轮候选加上审核要求恢复的原始动作，生成一个新的、独立命名的 reviewed 版本；不覆盖 `focused_v2` 或本候选。
3. 重新执行精确子序列、工具调用闭环、split/ID 对齐和 sidecar 恢复审计；为 reviewed 输出刷新哈希清单。
4. 对适合 replay 的轨迹，在对应仓库环境中运行必要测试/验证，记录成功、失败、跳过及环境缺失，不将结构审计替代 replay。
5. SFT 训练只使用 train split。validation 和 test 保持隔离，仅用于选择/评估；不得把抽检队列中的 held-out 轨迹混入训练。
6. 做基线与审核后候选的同配置对照实验，报告代码修复成功率、测试通过率，并单列 Bash 失败诊断/修正/重试表现。没有该评估前，不宣称压缩带来能力提升。

当前 `candidate_records.jsonl` 是未完成人工 review、未 replay 的压缩候选，不能直接视作正式 SFT 发布版。
