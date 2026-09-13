# 数据契约

## Session 是最小数据管理单元

一个 session 对应一次连续采集。场景、鸭子是否存在、鸭子数量、光照、距离和遮挡条件记录在 `session.yaml` 中。

后续 train/val 切分必须以 session 为单位，以防止同一视频的相邻帧泄漏到两个集合。

## 原始数据不可变

`raw/camera_bag` 是采集证据，不由处理脚本覆盖。重新抽帧只允许替换同一 session 下的 `frames/`。

## 图像不重新编码

`frames/NNNNNN.jpg` 的内容与 ROS `sensor_msgs/msg/CompressedImage.data` 完全一致。抽帧器会用 OpenCV 解码以确认数据有效并取得宽高，但不会把解码结果重新写成训练图片。

`frames/frames.jsonl` 每行字段如下：

| 字段 | 含义 |
|---|---|
| `index` | session 内从 0 开始的连续序号 |
| `filename` | 数字 JPEG/PNG 文件名，兼容后续 SAM 视频读取 |
| `topic` | 来源 ROS 话题 |
| `bag_timestamp_ns` | rosbag 记录时间戳 |
| `header_timestamp_ns` | 消息头时间戳；无有效时间戳时为 null |
| `relative_sec` | 相对本话题第一条消息的秒数 |
| `format` | ROS 消息中的压缩格式 |
| `width`, `height` | 解码验证得到的图像尺寸 |
| `payload_bytes` | 原始压缩数据大小 |
| `sha256` | 原始压缩数据哈希 |
| `duplicate_of` | 内容完全相同时首次出现的 frame index，否则为 null |

## 负样本语义

- `duck.present: false`：采集时明确没有放置鸭子，可以作为真负样本候选。
- `duck.present: true`：明确存在鸭子。
- `duck.present: null`：状态不明确，禁止自动导出为空标签负样本。

未来模型漏检帧不能单凭“没有检测框”认定为负样本。

## 可视化产物

`contact_sheet.jpg`、`preview.mp4` 和 `report.html` 是派生检查文件，不作为训练输入。所有未来模型结果也应保留模型版本、checkpoint 哈希、提示词、阈值和过滤原因。

## 文件布局与状态

```text
DATA_ROOT/
├── sessions/SESSION_ID/
│   ├── session.yaml
│   ├── raw/camera_bag/           # metadata.yaml、sqlite3 db3
│   ├── frames/                  # 原压缩图像、frames.jsonl
│   ├── artifacts/               # 抽帧/校验摘要、图片/视频/HTML
│   └── logs/record.log
└── benchmarks/grounded_sam2_v1/ # 派生验证集
```

`session.yaml` 保存 `schema_version`、`session_id`、创建/更新时间、状态、scene、duck、conditions、camera、paths、notes，并在后续阶段加入 recording/extraction/validation 等摘要。`paths` 为 session 内相对路径；帧文件名保持连续编号。

校验器将尺寸画像不匹配、未知鸭子存在性、超过 5% 的重复压缩帧列为 warning；哈希不匹配、文件损坏、索引不连续和非严格递增的时间戳属于 error。校验通过只能证明工具检查范围内的完整性，不证明画面内容标签正确、录制无漏帧或模型准确。

公开分享派生 manifest 或日志前应另行检查路径、场景备注及画面内容；当前 Git 忽略数据与运行输出，精选图片位于 `docs/images/`。
