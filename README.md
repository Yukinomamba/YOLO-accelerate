# YOLO-accelerate

RISC-V 控制的静态图像目标检测加速器。电脑传入图片，软核调度 FPGA 卷积计算，
再返回类别、置信度与检测框。当前以 **YOLOX-Tiny 为主、Nano 为备选**，
优先移植已验证的 FPGA 卷积核，不使用摄像头。

本仓库独立开发；不修改上级三个文档、任何 `AGENTS.md` 或 `hgb-aisystem_riscv`。
当前分支为 `research/tiny-fpga-accelerator-selection`。

## 已完成与下一步

2026-10-23：已核对上级三文档的当前状态及 NPU 规划、`紫光.pdf`、现有 SoC 接口，
重新核对 200HP 板卡的 32 MiB 外部 QSPI、1 GiB DDR、159,800 LUT6 和 740 APM。
[选型报告](docs/ACCELERATOR_SELECTION.md) 比较 Tiny/Nano 和用户提出的加速器；
首轮候选为 adamgallas 的 FPGA 卷积核，FIE 次选，小配置 NVDLA 保留。
其 27×18 打包乘法与 Pango 25×18 APM 的差异必须先验证，尚未确认 Pango 资源与时序。
[移植约束](docs/PORTING.md) 保留算子、SoC、UART 和原有 tile 的契约。

| 已完成 | 结果 |
| --- | --- |
| 官方 YOLOX-Nano CPU FP32 参考 | 上游 dog.jpg 检出 3 个目标；保存权重/图片哈希与检测框 |
| 官方 YOLOX-Tiny CPU FP32 参考 | 上游 dog.jpg 检出自行车、汽车、狗；结果见 `reports/dog-reference-tiny.json` |
| 两个官方计算图实际前向分析 | Tiny：5,055,855 参数，416 输入约 3.206G MAC，INT8 卷积权重约 4.805 MiB；Nano 约 0.523G MAC、0.855 MiB |
| INT8×INT8→INT32 脉动阵列 RTL | 1×1、2×3、4×4、8×8 四种形状，各 101 组 GEMM，共 404 组通过 |
| 协议检查 | 输入气泡、结果背压、有符号极值、K=65535、忙时命令、复位后恢复通过 |
| Verilator 严格 lint | `-Wall` 通过；未关闭警告致错 |

目前 RTL 是独立矩阵计算 tile，尚无卷积取数器、量化执行器、DMA/AXI 控制口、
UART 固件或完整 YOLO 硬件执行。未运行 PDS、未接入 hgb、未上板。
已有矩阵 tile 保留作参考；下一步先验证候选卷积核的 Pango 算术/存储适配，
再完成 YOLOX-Tiny 的 INT8 校准、算子和逐层调度。Tiny 不需要 depthwise 通路。

## 运行

RTL 测试需要 Python 3、Verilator 和支持其版本的 C++ 编译器：

```bash
make lint
make test
```

四组原始日志、命令及 RTL 哈希位于 `build/sim/`；运行器自动将 CCache 放在本仓库
`build/`。`make clean` 只删除仿真构建，保留下载的源码、权重与模型分析结果。

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

- `rtl/`：独立 PE 和脉动阵列；输入错位与握手契约见移植评估。
- `tb/`：直接三重循环 GEMM 参考，包含流控和复位验证。
- `tools/`：RTL 回归、官方模型算子分析、预训练静态图片参考。
- `docs/ACCELERATOR_SELECTION.md`：当前模型/加速器选择、板卡容量与资源门槛。
- `docs/PORTING.md`：赛题解释、算子、SoC 接口与原有 tile 契约。
- `config/`、`reports/`：固定来源和本次可核对结果。
