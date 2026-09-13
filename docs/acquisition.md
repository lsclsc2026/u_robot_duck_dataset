# 采集与日常操作

所有命令在仓库根目录执行。先设置 `U_ROBOT_DUCK_DATA_ROOT` 指向持久目录；每次采集独立一个 session。

## 相机准备

已构建导航工作区时，设定其位置：

```bash
export MOVE_WORKSPACE="$HOME/workspaces/u_robot_move"
source /opt/ros/humble/setup.bash
source "$MOVE_WORKSPACE/install/setup.bash"
ros2 launch u_robot_camera_bridge front_camera.launch.py
```

在另一终端加载 ROS 后检查：

```bash
ros2 topic type /camera/front/image/compressed
ros2 topic hz /camera/front/image/compressed
```

类型必须为 `sensor_msgs/msg/CompressedImage`。默认画像为 JPEG、960×540、名义 15 FPS；既有验证片段实际约 10 FPS，应以消息时间戳计算的帧率为准。脚本 `record_camera_session.sh` 和 `serve_dataset.sh` 在加载 Humble 后会 `unset CYCLONEDDS_URI`，延续本地相机采集方式；若部署必须依赖自定义 DDS 配置，应先核查该行为与桥接话题可见性。

## 录制正样本

```bash
./scripts/record_camera_session.sh \
  --scene room_a --duck-present true --duck-count 1 \
  --lighting normal --distance-range 1-3m --occlusion none \
  --duration 20 --notes "固定鸭子，记录采集条件"
```

`--duration` 单位是秒；不传时按一次 Ctrl-C，等待 rosbag 收尾。脚本使用 sqlite3、10 MiB 缓存和最长 60 秒的定时收尾等待。若数据库已存在但缺少 `metadata.yaml`，自动尝试 `ros2 bag reindex`。失败 session 和日志保留，不应直接当成已完成数据。

场景、光照、遮挡和距离为文字元数据；`--duck-count` 是采集者填写的数量，不是程序逐帧计数结果。实际每帧可见目标仍需审核。

## 真实负样本

明确确认采集画面没有鸭子时：

```bash
./scripts/record_camera_session.sh \
  --scene room_a_no_duck --duck-present false --duck-count 0 \
  --lighting normal --occlusion none --duration 20
```

不确定则用 `--duck-present unknown`。模型没有框不能证明没有鸭子；负样本元数据也不能替代最终数据质检。

## 处理 session

把录制脚本打印的完整路径放入 `SESSION_DIR`：

```bash
export SESSION_DIR="$U_ROBOT_DUCK_DATA_ROOT/sessions/SESSION_ID"
./scripts/process_session.sh "$SESSION_DIR"
```

顺序为 `extract → validate → visualize`。完整帧保留原始 `CompressedImage.data` 字节，预览视频仅供检查。默认抽取全部帧，供未来 SAM2 连续传播；快速检查可另外选择时间与采样率：

```bash
./scripts/duck_dataset extract --session "$SESSION_DIR" \
  --start-sec 2 --end-sec 8 --sample-fps 5
./scripts/duck_dataset validate --session "$SESSION_DIR"
./scripts/duck_dataset visualize --session "$SESSION_DIR" --no-video
```

不要把抽样帧当成原帧率的连续输入。已有 `frames/` 时抽帧拒绝覆盖；`process_session.sh SESSION_DIR --overwrite` 会删除并重建该 session 的 `frames/`，原始 bag 保留。先确认路径和派生数据备份。

## 网页查看

```bash
./scripts/serve_dataset.sh --root "$U_ROBOT_DUCK_DATA_ROOT" --port 8090
```

默认绑定 `127.0.0.1`。总览 `/` 展示 session 状态、报告和原始帧入口；`/live` 展示实时图像、FPS、帧年龄与最近 session 的 bag 增长量。静态报告无需启动 ROS；实时订阅需要 ROS 和相机话题。

远程访问，在浏览器所在电脑执行：

```bash
ssh -N -L 18090:127.0.0.1:8090 USER@ROBOT_HOST
```

打开 <http://127.0.0.1:18090/>。`USER` 与 `ROBOT_HOST` 是自行填写的连接参数。服务没有认证，直接 LAN 访问需主动传 `--bind 0.0.0.0` 并限制访问范围。Ctrl-C 停止网页服务，不会删除数据。

## 常见问题

| 现象 | 检查与处理 |
|---|---|
| 话题不存在/类型错误 | 确认桥接已启动、DDS 域与网络配置一致，检查脚本清除 CYCLONEDDS_URI 的影响 |
| 录制结束缺 metadata | 查看 `logs/record.log` 与 db3；确认 reindex 是否成功，保留原 bag 后再排查 |
| session 已存在 | 换 session ID；已有原始数据不覆盖录制 |
| SHA256 不一致 | 停止把该帧用于导出，核对原 bag、传输与磁盘；不要忽略后继续当作合格样本 |
| MP4 失败 | 安装可用的 ffmpeg，或 `visualize --no-video` 先检查图片 |
| 本地端口被占用 | 选择另一个 SSH 本地转发端口，无需停止远端服务 |
| 页面可打开但无实时帧 | 检查 ROS Python 模块、话题、最后帧年龄与桥接日志 |
