# 云端虚拟环境与 Grounding DINO 扫描

云端采用独立 Python 3.10 venv，不要求 Docker。此目录保留环境安装器、依赖锁文件和推理脚本；离线 wheelhouse、模型权重、第三方源码归档和数据集需单独准备。

## 环境版本与资产

历史环境使用 Python 3.10.21、PyTorch `2.5.1+cu121`、torchvision `0.20.1+cu121`、Transformers `4.46.3`，在 NVIDIA A800 上完成 calibration 推理。完整 Python 版本列表见 [requirements-cu121.lock](requirements-cu121.lock)。锁文件保存版本但没有每个 wheel 的哈希，也未固定操作系统和 NVIDIA 驱动；它不是跨平台可复现保证。

```bash
export CLOUD_WORKSPACE="$HOME/duck_auto_label"
export BENCHMARK_ROOT="$HOME/datasets/grounded_sam2_v1"
```

安装器接受 `setup_cloud_env.sh WORKSPACE`；未传参数时读 `U_ROBOT_DUCK_CLOUD_ROOT`，再回退到 `~/duck_auto_label`。预先准备：

```text
WORKSPACE/
├── offline/
│   ├── Miniconda3-py310_26.7.1-1-Linux-x86_64.sh
│   ├── requirements-cu121.lock
│   ├── Grounded-SAM-2-b7a9c29.tar.gz
│   └── wheelhouse/                  # 所有依赖的兼容 wheels
├── models/grounding-dino-tiny/       # 完整 HF 模型与 processor/tokenizer 文件
└── checkpoints/sam2.1_hiera_large.pt # 后续 SAM2 实验使用，DINO 不需要
```

第三方归档必须解压出顶层 `Grounded-SAM-2/`，对应提交 `b7a9c29f196edff0eb54dbe14588d7ae5e3dde28`。常规 `git archive` 如没有指定 `--prefix=Grounded-SAM-2/`，不符合安装器约定。

## 在联网机器准备离线包

使用匹配目标平台的 Linux x86_64 / Python 3.10 环境。下载上述 Miniconda 安装器，并按供应方校验和核对；准备固定提交源码及许可证；将本仓库锁文件复制到 `offline/`。普通 Python 包可使用清华 PyPI 镜像，`+cu121` 的 PyTorch/torchvision 来自官方 CUDA 12.1 索引。

已有 Python 3.10 的准备环境中，可构建 wheelhouse：

```bash
python3.10 -m pip wheel \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  --extra-index-url https://download.pytorch.org/whl/cu121 \
  --wheel-dir "$CLOUD_WORKSPACE/offline/wheelhouse" \
  -r cloud/requirements-cu121.lock
cp cloud/requirements-cu121.lock "$CLOUD_WORKSPACE/offline/requirements-cu121.lock"
```

某些依赖仅提供源码分发，需要在联网准备环境构建 wheel；离线安装器使用 `--only-binary=:all:`，只有 sdist 不足以安装。确认准备环境 Python 版本/架构与目标一致，检查包来源，并生成离线包 SHA256 清单保存到自己的资产管理位置。以上是准备流程，本次发布未重新联网下载或重建 wheelhouse。

模型采用 `IDEA-Research/grounding-dino-tiny` 的完整本地 Hugging Face 快照。复制模型时保留配置、processor、tokenizer 与 safetensors，不只复制一个权重文件。历史记录未保存可核验的模型快照 revision/权重哈希；新实验应补充记录以便复现。

## 离线安装

将资产与基准数据完整传到目标主机后：

```bash
./cloud/setup_cloud_env.sh "$CLOUD_WORKSPACE"
source "$CLOUD_WORKSPACE/.venv/bin/activate"
python -m pip check
```

安装器由 Miniconda 提供 Python，再创建 `.venv`，使用 `--no-index --find-links` 安装锁定依赖，将固定源码以 editable 方式安装。pip 镜像设置仅写入该 venv 的 site 配置。SAM2 使用 `SAM2_BUILD_CUDA=0` 关闭可选 CUDA 扩展，避免依赖系统 nvcc；核心 GPU 运算仍需要可用 NVIDIA 驱动。

**安装器最后会执行真实 CUDA 矩阵乘法冒烟检查**，因此仅在准备使用的 GPU 环境中运行。检查通过代表环境能执行 GPU 运算，不代表 SAM2 传播已完成。源码目录或已有 venv 不会自动更新到新的版本；升级时建立新环境并保留原实验。

## calibration 扫描

```bash
CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  "$CLOUD_WORKSPACE/.venv/bin/python" cloud/run_grounding_scan.py \
  --dataset-root "$BENCHMARK_ROOT" \
  --model-dir "$CLOUD_WORKSPACE/models/grounding-dino-tiny" \
  --output-dir "$CLOUD_WORKSPACE/results/grounding_calibration_v2" \
  --split calibration --visual-threshold 0.20
```

三个路径参数必填；模型使用 `local_files_only=True`。新实验采用新的输出目录。`--overwrite` 允许覆盖已有结果，但不会清空旧叠加图，因此不同图片集合或提示词的重跑应使用新目录，避免残留图误导审核。

| 参数 | 默认值/含义 |
|---|---|
| `--split` | `calibration`；也接受 `holdout` |
| `--prompts` | `yellow rubber duck`、`rubber duck`、`yellow duck toy` |
| `--thresholds` | 0.15、0.20、0.25、0.30、0.35；候选框计数阈值 |
| `--text-threshold` | 0.15 |
| `--visual-threshold` | CLI 默认 0.25；历史完整扫描显式使用 0.20 |
| `--limit` | 0 表示所有图片；正数仅取按文件名排序的前 N 张 |
| `--device` | `cuda:0`；可指定 `cpu`，本次没有验证 CPU 模型推理 |

程序没有自动强制冻结参数或限制 holdout；实验负责人必须在 calibration 审核完成后记录配置，再运行 holdout。候选分数不等同于概率或准确率，不应直接用最高分框初始化跟踪。

## 报告与复现记录

输出包括 `predictions.jsonl`、`summary.json`、`overlays/`、每个提示词的 contact sheet 与 `report.html`。每张图/提示词一条 JSONL，保存原始像素 `boxes_xyxy`、`scores`、`labels`；报告显示的是按 visual threshold 筛选的子集。

```bash
python3 -m http.server 8090 --bind 127.0.0.1 \
  --directory "$CLOUD_WORKSPACE/results/grounding_calibration_v2"
```

浏览器所在机器通过 `ssh -N -L 18090:127.0.0.1:8090 USER@CLOUD_HOST` 转发后打开 <http://127.0.0.1:18090/>。连接账号、地址与端口由使用者配置。停止服务用 Ctrl-C。

`summary.json` 记录模型本地路径、阈值、设备、torch 版本与耗时；尚不自动保存 checkpoint 哈希、驱动、脚本提交与 dataset manifest 哈希。每轮应另行记录这些信息，并保存完整命令、日志和人工审核版本。

历史计数和审核方法见[calibration 记录](../docs/grounding_calibration_v1_review.md)。当前没有人工评价、CSV 审核表生成、SAM2 传播或 YOLO 导出脚本；不要把历史额外审核材料误认为扫描器的默认输出。
