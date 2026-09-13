# 第三方依赖与素材来源

本仓库首版用于私有审阅，原创代码尚未选择开源许可证。私有审阅不改变第三方软件、模型或素材原有许可。本说明不授予额外的 SDK、数据或模型再分发权。

| 依赖 | 来源与使用方式 |
|---|---|
| ROS 2 Humble、rosbag2、rclpy、sensor_msgs | [ROS 2](https://github.com/ros2) 上游，通过系统包安装；本仓库未包含其源码副本 |
| Unitree 相机接口/SDK | 由关联导航与共用环境仓库提供；使用设备适配版本和厂商许可，不作为本项目原创代码 |
| NumPy、OpenCV、PyYAML、FFmpeg | 机器人端图像、配置和视频处理依赖；通过系统或 Python 包安装 |
| PyTorch、torchvision 与 CUDA runtime wheels | [PyTorch](https://pytorch.org/)，对应版本见云端锁文件；NVIDIA 组件另有其分发条款 |
| Transformers 与 Hugging Face 模型工具 | [Transformers](https://github.com/huggingface/transformers)，云端使用 4.46.3 |
| Grounded-SAM-2 | [IDEA-Research/Grounded-SAM-2](https://github.com/IDEA-Research/Grounded-SAM-2)，历史固定提交 `b7a9c29f196edff0eb54dbe14588d7ae5e3dde28`，安装器需要外部源码归档 |
| Grounding DINO Tiny | [IDEA-Research/grounding-dino-tiny](https://huggingface.co/IDEA-Research/grounding-dino-tiny)，完整本地模型快照由使用者提供 |
| SAM 2 | [facebookresearch/sam2](https://github.com/facebookresearch/sam2)，历史准备了 SAM2.1 Hiera Large；本项目未完成传播验证 |
| Miniconda | [Miniconda](https://docs.anaconda.com/miniconda/)，外部离线安装器用于创建 Python 3.10 环境 |

外部源码、安装器、权重与 wheelhouse 均不随 Git 仓库分发。获取时保留对应版本的 LICENSE、NOTICE、模型卡和供应方校验和；运行环境可用不等于获得公开再分发权。上述来源用于定位依赖，本次发布未对所有外部依赖进行完整许可证法律审查。

`docs/images/` 的四张精选 JPEG 来自项目实际相机采集后的历史 DINO 叠加报告，候选尚未审核。来源文件名与字节哈希见 [images/README.md](docs/images/README.md)。只纳入所选展示素材；原始数据全集和完整报告未发布。
