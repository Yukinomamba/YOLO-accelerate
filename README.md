# YOLO-accelerate

RISC-V 控制的静态图像目标检测加速器。电脑传入图片，软核调度 FPGA 卷积计算，
再返回类别、置信度与检测框。当前以 **YOLOX-Tiny 为主、Nano 为备选**，
采用 **adamgallas 的 128 MAC 卷积后端移植**，不使用摄像头。

本仓库独立开发；不修改上级三个文档、任何 `AGENTS.md` 或 `hgb-aisystem_riscv`。
当前分支为 `npu/adamgallas-128-verilator`。

## 已完成与下一步

2026-10-23：已完成 8 输入通道×16 输出通道的 128 MAC 后端与 Verilator 验证。
上游 27×18 打包乘法已改为两路 signed 8×8，四拍延迟与全部输入组合逐项一致；
新增 tile 缓存、1×1/3×3、stride/padding、INT32 累加及背压控制。
[实现与接口](docs/ADAM128.md) 给出数据布局、分块、数值、验证和内存限制。
[选型报告](docs/ACCELERATOR_SELECTION.md) 保留模型和板卡评估，
[移植约束](docs/PORTING.md) 保留完整 YOLOX、SoC 与 UART 的后续工作。

| 已完成 | 结果 |
| --- | --- |
| 官方 YOLOX-Nano CPU FP32 参考 | 上游 dog.jpg 检出 3 个目标；保存权重/图片哈希与检测框 |
| 官方 YOLOX-Tiny CPU FP32 参考 | 上游 dog.jpg 检出自行车、汽车、狗；结果见 `reports/dog-reference-tiny.json` |
| 两个官方计算图实际前向分析 | Tiny：5,055,855 参数，416 输入约 3.206G MAC，INT8 卷积权重约 4.805 MiB；Nano 约 0.523G MAC、0.855 MiB |
| adamgallas 算术移植 | 16,777,216 个全部 INT8 三元组与原版及整数参考逐拍一致；RAM 1,024 项通过 |
| 128 MAC 卷积后端 | 110 个任务、6,270 个输出像素；最大 768 输入通道、四种整图分块拼接通过 |
| 协议与结构 | 背压、非法命令、8 次复位恢复、执行周期检查通过；展开结构确认为 128 路乘法 |
| Verilator 严格 lint | 移植 RTL `-Wall` 通过；上游对照文件仅使用局部 waiver |
| 本次内存 | 全新构建进程组采样峰值 350.6 MiB；卷积仿真 3.9 MiB；单 CPU/单任务运行 |

源码哈希、实际命令和原始日志位置见 [128 MAC 验证报告](reports/adam128-validation.json)。

当前返回 INT32 卷积结果，尚无 requant/SiLU、DMA/AXI 控制口、UART 固件或完整 YOLO 执行。
未运行 PDS、未接入 hgb、未上板。下一步是 Tiny 的量化与其余算子、逐层调度和存储接口。
原有自研 systolic tile 及其 404 项历史 GEMM 验证保留作独立参考。

## 运行

RTL 测试需要 Python 3、Verilator 5.052（使用 JSON 展开检查）和 g++：

```bash
make lint
make test
# 可选：单独验证内存保护机制
python3 tb/check_memory_guard.py
```

当前回归默认日志位于 `build/adam128/`，本次全新构建记录保留在 `build/adam128/final/`。
构建固定 `-j1`，只使用一个 CPU，设进程地址空间上限和自身进程组 RSS 监测；默认不生成波形。
超过内存/时间阈值只终止本次子进程组，不操作 hgb/PDS。
`make tile-test` 单独执行旧矩阵 tile 回归。`make clean` 仅删除仿真构建，保留源码、权重与模型分析。

模型分析需要已有 PyTorch/torchvision 环境，额外依赖可仅装入本仓库：

```bash
git clone https://github.com/Megvii-BaseDetection/YOLOX.git build/upstream/YOLOX
git -C build/upstream/YOLOX checkout --detach 6ddff4824372906469a7fae2dc3206c7aa4bbaee
python -m pip install --target build/python-deps --no-deps loguru==0.7.3 tabulate==0.10.0 thop==0.1.1.post2209072238 opencv-python-headless==5.0.0.93 psutil==7.2.2
PYTHONPATH=build/python-deps make audit-both PYTHON=python
```

PyTorch 环境同时需要 numpy、matplotlib、tqdm；本次使用 PyTorch 2.14.0+cu126，
模型运行设备为 CPU。`make audit` 默认 Tiny，可用 `MODEL=yolox-nano` 切换。
`make audit-both` 生成两模型逐层统计及 `build/model-comparison.json`。
分析使用随机权重和零输入，统计形状及 MAC，不测精度。

预训练静态图片参考：

```bash
mkdir -p build/models
curl --fail --location https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.pth --output build/models/yolox_tiny.pth
PYTHONPATH=build/python-deps python tools/reference_detect.py \
  --source build/upstream/YOLOX --model yolox-tiny --weights build/models/yolox_tiny.pth \
  --image build/upstream/YOLOX/assets/dog.jpg --output build/dog-reference-tiny.json
```

[Tiny 来源与哈希](config/yolox-tiny.lock.json)、[模型比较](reports/model-comparison.json)、
[Tiny 检测框](reports/dog-reference-tiny.json) 和 [本轮验证](reports/selection-validation.json) 随源码保留。
[Nano 来源](config/upstream.lock.json)、[原有 RTL/Nano 验证](reports/validation.json)
和 [Nano 检测框](reports/dog-reference.json) 保留作原始基线；第三方源码、权重和原始构建日志
在忽略的 `build/` 中，不纳入提交。下载后须按 lock 核对哈希；脚本强制检查上游提交
及工作树状态，并在输出中记录实际权重和图片哈希。

## 文件

- `rtl/adam/`：当前 128 MAC 卷积后端；`rtl/systolic*` 为原有矩阵参考。
- `third_party/adamgallas/`：固定版本的上游原样源码、许可证与逐文件哈希。
- `tb/`：上游算术/RAM 对照、独立标量卷积和分块参考、流控与复位测试。
- `tools/`：RTL 回归、官方模型算子分析、预训练静态图片参考。
- `docs/ACCELERATOR_SELECTION.md`：当前模型/加速器选择、板卡容量与资源门槛。
- `docs/ADAM128.md`：128 MAC 后端实现、接口与 Verilator 验证。
- `docs/PORTING.md`：赛题解释、算子、SoC 接口与原有 tile 契约。
- `config/`、`reports/`：固定来源和本次可核对结果。
