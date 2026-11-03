
## 一、协作分工

仓库结构：

```text
parts/
  part_A/
    original/
    focused_v2/
    focused_v2_metadata/
  part_B/
    original/
    focused_v2/
    focused_v2_metadata/
code/
manifests/
source_metadata/
focused_v2_metadata/
```

可以把两部分合并放进一个仓库；这里的“合并”是**同仓库并列管理**，不是把 Part A/B 直接按文件顺序拼成一个未经排序的新数据文件。最终重组必须按 `manifests/assignment.jsonl` 中的 `split` 和 `source_line` 排序。

## 二、数据内容

- `parts/part_A/original/` 与 `parts/part_B/original/`：最终已翻译的原始数据，合计 4,976 条轨迹。
- `parts/part_A/focused_v2/` 与 `parts/part_B/focused_v2/`：当前回退版本。
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

## 四、审计边界

当前审计已确认分片覆盖、记录 ID 对齐和 sidecar 分配无错误。focused_v2 仍是候选数据，不是已批准的正式 Pangu SFT 数据；后续仍需人工语义审阅、仓库 replay、Pangu tokenizer/chat template 和实际训练验证。
