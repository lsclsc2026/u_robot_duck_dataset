# 首轮验证集与划分

`build_model_validation_set.py` 是复现 `grounded_sam2_v1` 的固定实验脚本，要求下面四个 session 及其 `frames/frames.jsonl` 已存在。源数据未随仓库发布，因此新克隆仓库不能直接重建这套历史基准。新采集数据需要先制定新的 session 划分、目标数量与片段规格；本版没有通用配置输入接口。

## 固定数据组成

| 划分 | 来源 session | 图像数 |
|---|---|---:|
| calibration | `20260903_061720_room_a_duck_repositioned` | 45 |
| calibration | `20260903_073208_room_a_duck_repositioned` | 55 |
| holdout | `20260903_053540_room_a` | 15 |
| holdout | `20260903_071223_room_a_duck_repositioned` | 45 |

共 160 张 960×540 JPEG。calibration 用于选择提示词、阈值和过滤规则；holdout 的 60 张只有在配置冻结后才用于独立评价。两组按 session 隔离，相邻帧不得随机拆到两个集合；同房间采集仍存在场景相似性，不能据此宣称跨场景泛化。

| 连续片段 | 来源 session 时间标识 | 时间范围（秒，左闭右开） | 历史帧数 |
|---|---|---|---:|
| `061720_multi_far` | 061720 | [90, 120) | 300 |
| `071223_open_floor` | 071223 | [0, 30) | 300 |
| `073208_chair_multi` | 073208 | [110, 150) | 400 |
| `073208_edge_far` | 073208 | [250, 280) | 300 |

这些片段用于后续 SAM2 实验，保留实际约 10 FPS 的全部帧，共 1300 帧。片段中包含 holdout 来源 session；如果利用它调节整条检测/跟踪流程，该 session 就不能继续作为整条流程的独立 holdout，需要另建未见数据。当前只完成片段准备，没有 SAM2 跟踪结果。

## 生成命令

拥有对应源 session 时先预演：

```bash
python3 scripts/build_model_validation_set.py \
  --data-root "$U_ROBOT_DUCK_DATA_ROOT" --dry-run
```

确认计划后生成：

```bash
python3 scripts/build_model_validation_set.py --data-root "$U_ROBOT_DUCK_DATA_ROOT"
```

输出固定为 `DATA_ROOT/benchmarks/grounded_sam2_v1`，与 `sessions/` 同级。`--overwrite` 删除并替换该基准目录；不删除源 sessions。脚本在临时派生目录完成检查后替换输出。`quick_build_validation.sh` 是同一入口的快捷包装。

## 选择规则与追溯

每一秒选择最接近中点的帧作为候选，再按时间分桶、清晰度和 dHash 距离选择。约 10% 槽位故意优先模糊困难帧；相似度过滤无可选项时会回退，因此它不是严格全局去重算法。复制前后核对 SHA256、可解码性和 960×540 尺寸。

```text
grounded_sam2_v1/
├── summary.json
├── grounding_dino/
│   ├── calibration/images/
│   ├── holdout/images/
│   ├── manifest.jsonl
│   ├── contact_sheet_calibration.jpg
│   ├── contact_sheet_holdout.jpg
│   └── report.html
└── sam2_clips/CLIP_NAME/
    ├── frames/000000.jpg
    ├── mapping.jsonl
    └── clip.yaml
```

`manifest.jsonl` 保存来源 session、原始帧号、时间、尺寸、SHA256、清晰度、亮度与 dHash；`annotation_status` 初始为 `unreviewed`。`mapping.jsonl` 保存连续片段的新旧帧号关系。输出不创建标签，图片无标签不能解释为真负。

历史四个 session 的 `duck.present` 都是 true，尚无确认的纯负 session。后续需独立采集并检查负样本，同时保留模糊、远距离、遮挡和无检测帧。
