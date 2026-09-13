# 验证记录与已知限制

2026-09-13 对首版发布副本进行离线检查。未启动真实相机录制、机器人运动、GPU 推理或云端安装，也未修改原始采集与报告数据。

## 本次实际运行

| 检查 | 结果 | 范围 |
|---|---|---|
| `./scripts/run_tests.sh` | 11 项通过，0 跳过 | session 字段/状态、固定划分与采样、合成 rosbag 全流程 |
| Python AST 语法 | 15 个源码/测试文件通过 | 无需导入 GPU 依赖 |
| `bash -n` | 7 个脚本通过 | 所有 shell 脚本和 CLI 包装入口 |
| CLI `--help` | 15 个入口/子命令通过 | 含 cloud 扫描、安装器、验证集、录制与网页帮助 |
| 历史 JSONL 重算 | 100 图、300 条唯一记录、656 个候选；15 组计数一致 | 只读原有报告，不重新推理 |
| 精选图片 | 4 张 JPEG 可解码，均为 960×540 | 与原始叠加图 SHA256 一致，来源清单保存在仓库 |

合成集成测试在临时目录中创建 12 帧 `CompressedImage` sqlite3 bag，验证提取图像与原压缩载荷一致、逐帧哈希、校验报告、contact sheet、预览视频和 HTML 总览。它不启动相机或机器狗。

```bash
./scripts/run_tests.sh
python3 cloud/run_grounding_scan.py --help
python3 scripts/build_model_validation_set.py --help
bash -n cloud/setup_cloud_env.sh
```

测试入口会在存在时加载 `/opt/ros/humble/setup.bash`。无 ROS Python 模块的电脑会跳过 bag 集成测试；不能将“测试命令返回成功且有跳过”解释为 bag 全链路已验证。

## 历史证据与本次验证的区别

历史记录显示 2026-09-11 在 Python 3.10.21 / PyTorch 2.5.1+cu121 / Transformers 4.46.3 / A800 上完成完整 calibration 扫描。此次只读核对报告统计并复制精选图，没有重建云端环境、重新下载模型或重新运行推理。

本次参数化后的源码与历史扫描脚本字节不同。模型导入已移到 CLI 参数解析之后，因此无 torch/Transformers 的 CPU 环境也能查看帮助；帮助成功不代表模型环境完整。离线资产未随 Git 发布，本次没有从空白 GPU 主机验证安装器。

## 已知限制

- calibration 仍待人工审核；没有精确率、召回率或 mAP 可报告。
- holdout 尚未执行；SAM2 import 的历史冒烟通过不代表跟踪功能已完成。
- 固定验证集脚本只接受历史四 session 的内容；不提供新 session 配置参数。
- 当前四个历史 session 皆为正样本采集，纯负场景与跨场景数据不足。
- CLI 不加载 `configs/duck.yaml`；它只记录参考默认值和规划项。
- 录制与网页脚本会清除 `CYCLONEDDS_URI`；非当前本地桥接部署需核对 DDS 配置。
- 浏览器不含认证、人工编辑与同步；模型结果仍需外部审核工具。
- 云端锁文件缺每个 wheel 哈希，模型快照 revision/权重哈希与驱动没有被完整固化。
- 云端 `--overwrite` 可留下上轮叠加图；不同配置请使用新输出目录。
- 尚未实现 SAM2 传播、质量过滤、YOLO 标签导出、训练或机器人视觉部署。
