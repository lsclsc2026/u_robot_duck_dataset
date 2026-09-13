# ROS 容器与云端环境

机器人端可使用 [unitree_docker](https://github.com/lsclsc2026/unitree_docker) 提供的 ROS 2 Humble 开发环境。按该仓库配置源码目录和数据目录挂载，再在容器内设置 `U_ROBOT_DUCK_DATA_ROOT` 为数据挂载中的目录。

本仓库的录制、处理和测试脚本自动加载 `/opt/ros/humble/setup.bash`。相机桥接由 [u_robot_move](https://github.com/lsclsc2026/u_robot_move) 构建提供；当前仓库不包含机器人 SDK 或 Docker 镜像。

确认源码与数据挂载分别生效后再采集；容器中的可写目录不自动意味着宿主机已持久化。不要用复制整个数据集进镜像的方式保存录制数据。

云端推理采用独立 Python 3.10 虚拟环境，安装方式见 [cloud/README.md](../cloud/README.md)。锁定依赖与 NVIDIA GPU 检查由该环境负责，机器人 ROS 镜像不要求安装 PyTorch 或 SAM2。
