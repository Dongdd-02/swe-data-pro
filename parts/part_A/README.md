# Part A：同事负责

本目录是双人协作包中的 **Part A**。由同事负责审阅和修改；你负责 Part B。两部分放在同一个 GitHub 仓库中，但两人只修改各自的 `parts/part_A/` 或 `parts/part_B/`，避免编辑同一个完整 JSONL 造成冲突。

## 内容

- `original/`：最终已翻译的原始轨迹。
- `focused_v2/`：当前回退版本。
- `focused_v2_metadata/record_manifest.jsonl`：本分片被删除探索动作的清单。
- `focused_v2_metadata/removed_exploration.jsonl.gz`：本分片被合并的完整原始消息，可审计和恢复。

## focused_v2 处理方案

当前版本的目标是删除**冗余探索轮次**，不是压缩工具回复正文：

- 明确失败、错误回显、Edit/Write、执行、重试和测试/验证动作保留。
- 中间只读探索按阶段判断；冗余探索合并成中文阶段摘要。
- 摘要保留路径、无结果搜索事实、部分命中信息和未被后续动作覆盖的编号代码行。
- 大文件缩略 Read 只有在同阶段存在后续同文件定向 Read，且未发现后续 Edit 依赖缺失时才删除。
- 被删除的完整动作和回显都在 `removed_exploration.jsonl.gz` 中；保留动作的工具回复不应被再次裁剪。

## 提交协作修改

建议使用 `review/part-a` 分支，通过 Pull Request 合并到 `main`。修改时记录 `record_id`、修改原因和是否影响失败→诊断→修改→执行→验证链。提交前在仓库根目录运行：

```bash
python code/verify_swe_collaboration.py --root .
```

不要把本分片单独当作完整数据集；最终重组必须按根目录 `manifests/assignment.jsonl` 的 `source_line` 排序。详细规则见根 README。
