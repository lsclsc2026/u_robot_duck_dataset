# 环境与安装

## 机器人采集与 CPU 处理

使用 Ubuntu 22.04 / ROS 2 Humble / Python 3.10。录制和抽帧依赖 ROS 的 `rclpy`、`rosbag2_py`、`sensor_msgs` 与 sqlite3 bag storage；这些不是普通 pip 包。CPU 图像处理依赖 OpenCV、NumPy、PyYAML，视频预览调用系统 `ffmpeg`。

在已配置 ROS 2 软件源的 Ubuntu 环境中，可安装：

```bash
sudo apt-get update
sudo apt-get install -y \
  ros-humble-ros-base ros-humble-rosbag2 ros-humble-rosbag2-storage-default-plugins \
  ros-humble-sensor-msgs python3-opencv python3-numpy python3-yaml python3-venv ffmpeg
source /opt/ros/humble/setup.bash
```

克隆本仓库后，`scripts/duck_dataset` 会自动把 `src/` 加入 `PYTHONPATH`，使用上述系统 Python 依赖即可，无需 pip 安装本项目。也可在已有 ROS 环境的虚拟环境中安装命令行入口：

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --no-deps -e .
duck-dataset --help
```

`--no-deps` 使用已有系统图像库。`pyproject.toml` 中机器人 CPU 依赖是最低版本约束，尚非完整锁定环境；不要把云端 CUDA 锁文件安装进机器人环境。

相机由 [u_robot_move](https://github.com/lsclsc2026/u_robot_move) 的 `u_robot_camera_bridge` 提供；其 SDK、网卡和 DDS 设置按导航仓库文档配置。此仓库不附带厂商 SDK。

## 路径与持久化

默认数据根为当前用户的 `~/data/duck_dataset`。推荐显式设置为持久化挂载内的目录：

```bash
export U_ROBOT_DUCK_DATA_ROOT="$HOME/data/duck_dataset"
```

`init/index/serve` 的 `--root`、录制与网页脚本的 `--root`、验证集构建器的 `--data-root` 优先于环境变量。`extract/validate/visualize` 使用显式 `--session`。配置文件 `configs/duck.yaml` 目前是参考表，CLI **不会读取这个 YAML**；修改它不会改变脚本行为。

容器部署见 [Docker 入口](../docker/README.md) 和 [unitree_docker](https://github.com/lsclsc2026/unitree_docker)。检查数据目录是否映射到宿主机持久目录；源码挂载与数据挂载分别设置，不能由容器名推断持久性。

## 无 ROS 的电脑

安装 Python 3.10+、NumPy、OpenCV、PyYAML 后，可管理元数据、校验已提取的帧、生成静态图片报告及构建历史验证集。网页总览可用；无 ROS 模块时实时相机不可用。抽帧和录制必须回到 ROS 环境。没有 `ffmpeg` 时用 `visualize --no-video` 生成图片与 HTML。

云端 GPU 依赖、模型目录与独立 venv 见[云端说明](../cloud/README.md)。
