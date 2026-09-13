# u_robot_duck_dataset

从 Unitree A2 Pro 前视相机建立可追溯的数据集：录制 ROS 2 session、无损提取压缩帧、生成检查报告，并在独立云端虚拟环境中扫描 Grounding DINO 候选框。

*Traceable camera capture and Grounding DINO candidate review tools for a rubber duck dataset.*

**当前阶段：采集与预处理已实现；100 张 calibration 的 DINO 扫描已完成，人工审核尚未完成。SAM2 连续跟踪、YOLO 标签导出、训练和部署尚未完成。** 本仓库包含完整工具源码和精选结果图，不包含数据全集、模型权重或离线安装包。

![待人工审核的鸭子候选框与墙面大框](docs/images/candidate-near-and-wall.jpg)

上图是 2026-09-11 的 `yellow rubber duck` 候选检测，可视化阈值 0.20。近处鸭子候选、暗处小框与墙面大框同时出现；所有框均未经人工真值审核。更多[候选与失败案例](docs/grounding_calibration_v1_review.md)。

## 能做什么

| 模块 | 已实现内容 | 边界 |
|---|---|---|
| 机器人端采集 | 相机话题录制、场景与采集条件、状态记录、异常 bag reindex | 需要 ROS 2 Humble 和可用相机话题 |
| 离线预处理 | 保留原始压缩字节、逐帧 SHA256、时间戳、重复帧、完整性校验 | 不执行自动修复或自动标注 |
| 人工浏览 | contact sheet、MP4 预览、HTML 总览、实时 MJPEG 监视 | 浏览器服务没有认证功能 |
| 首轮验证集 | 100 张 calibration + 60 张 holdout，4 段连续片段 | 脚本固定对应四个历史 session，数据不随仓库发布 |
| 云端扫描 | 离线模型加载、3 个提示词、5 档 box threshold、JSONL 与叠加图 | 输出是候选；没有评价器、人工标注界面或 YOLO 导出器 |

## 快速开始

机器人端环境与依赖见[安装说明](docs/installation.md)。以下在本仓库根目录执行；路径可自行调整：

```bash
export U_ROBOT_DUCK_DATA_ROOT="$HOME/data/duck_dataset"
./scripts/duck_dataset --help
./scripts/run_tests.sh
```

已有相机话题且准备采集时：

```bash
./scripts/record_camera_session.sh \
  --scene room_a --duck-present true --duck-count 1 \
  --lighting normal --distance-range 1-3m --occlusion none --duration 20
```

将录制结束时输出的路径设为 `SESSION_DIR`，随后处理和浏览：

```bash
export SESSION_DIR="$U_ROBOT_DUCK_DATA_ROOT/sessions/SESSION_ID"
./scripts/process_session.sh "$SESSION_DIR"
./scripts/serve_dataset.sh
```

浏览器打开 <http://127.0.0.1:8090/>；实时相机位于 `/live`。`SESSION_ID` 必须替换为实际目录名。录制脚本仅订阅相机数据，不提供机器狗运动控制；相机桥接与操作步骤见[采集指南](docs/acquisition.md)。

云端用独立 Python 3.10 venv，遵循[离线安装与 DINO 扫描说明](cloud/README.md)。机器人 ROS 环境与云端 GPU 环境分别管理。

## 文档导航

- [环境与安装](docs/installation.md)：ROS 依赖、Python 安装、路径与共享容器。
- [采集与操作](docs/acquisition.md)：相机检查、正负样本、录制、恢复和网页浏览。
- [架构与接口](docs/architecture.md)：数据流、模块职责、CLI、默认参数。
- [数据契约](docs/data_contract.md)：session、帧记录、哈希与负样本语义。
- [验证集构建](docs/validation_set_guide.md)：固定历史划分、连续片段、追溯与 holdout 隔离。
- [云端安装与扫描](cloud/README.md)：离线资产、锁定版本、模型与命令。
- [候选审核与历史结果](docs/grounding_calibration_v1_review.md)：实测计数、精选图、人工审核流程。
- [验证记录与限制](docs/validation.md)、[后续路线](docs/roadmap.md)、[版本记录](CHANGELOG.md)。

## 相关项目与许可

[导航与相机桥接 u_robot_move](https://github.com/lsclsc2026/u_robot_move) · [语音播报 u_robot_audio](https://github.com/lsclsc2026/u_robot_audio) · [共用开发环境 unitree_docker](https://github.com/lsclsc2026/unitree_docker)

首版用于私有审阅，尚未为原创代码选定开源许可证。外部库、模型、SDK 的权利和使用条件见[第三方依赖说明](THIRD_PARTY.md)。
