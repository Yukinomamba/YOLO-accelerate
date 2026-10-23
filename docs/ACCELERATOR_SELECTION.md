# YOLOX-Tiny 与 FPGA 加速器选型

本文保留候选、板卡和 128 MAC 选型时的证据。当前硬件主线已按后续要求切换为完整上游
576 路乘积数据通路；版本边界、现状和开发顺序见 [交接文档](HANDOFF.md)。下文资源预算及
128 MAC 结论属于早期评估，不能作为当前完整上游的 Pango 测量结果。

核对日期：2026-10-23。**模型采用 YOLOX-Tiny，Nano 保留为资源或延迟不达标时的备选。
用户已确定采用 adamgallas，规模为 128 MAC。** [128 MAC 后端](ADAM128.md) 已通过
Verilator；FIE 与小配置 NVDLA 的比较保留为选型记录。
原候选排序依据公开板级 CNN 证据、可核对的资源报告及本板适配成本；尚未完成紫光综合，
不代表已确定最终硬件规模。本仓库已有自研矩阵 tile 保留作独立算术参考。

按用户要求，tiny 系列按本次检索到的同名项目中 star 最高者核查：
`tiny-tpu-v2/tiny-tpu` 为 1,403，`harishsg993010/tiny-NPU` 为 283。
`jofrfu/tinyTPU` 为 583、`cameronshinn/tiny-tpu` 为 230，因此不再作为 tiny TPU 主候选。
这些是检索快照，不是性能指标。`CNN_FPGA` 已从此次选型排除。

## 板卡、存储与已有 Core

依据 `$PDS_WORK_ROOT/reference/1_Demo_document/实验例程说明篇/`
`MES2L676-200HP硬件使用手册_v1.2.pdf`，其中 `$PDS_WORK_ROOT` 指向现场 Pango 项目根。
PDF 第 10 页是器件资源表，第 14 页为 DDR，第 17–18 页为 Flash 与接线。
数据同时保存在 [board-budget.json](../config/board-budget.json)。

| 项目 | 手册数据 | 对方案的影响 |
| --- | ---: | --- |
| FPGA | PG2L200H-6IFBB676 | 以 200HP 板卡为目标；上板前核对实物 |
| LUT6 / FF | 159,800 / 319,600 | 不使用等效 LUT4 的 239,700 作 LUT6 预算分母 |
| APM | 740 个，25×18 乘法器 | DSP 余量较多，但不能按 Xilinx DSP48E2 一对一换算 |
| DRM36K | 415 块，共 14,940 Kibit，约 1.824 MiB | Tiny 权重无法全部放片上；采用 DDR 分块与片上缓存 |
| 外部 DDR3 | 两片各 512 MiB，总计 1 GiB，32 位 | 容量适合权重和特征；带宽需与 CPU 共享 |
| 板载 QSPI Flash | 两片 W25Q128JV，各 128 Mbit，总计 32 MiB | 这是外置 Flash；还要扣除 FPGA 配置、固件和分区 |

Flash 两片有独立片选并共享时钟，手册说明支持 8 bit 模式。不能直接假设第二片空闲、
两片对 CPU 呈连续 32 MiB，或配置文件只占第一片。必须检查实际配置模式、bitstream
大小和启动分区，才能确定可用模型空间。Tiny INT8 参数区可先以 **8 MiB 作为设计预算**，
其中卷积权重约 4.80 MiB；最终还取决于通道补齐、bias、scale、激活表和描述符。
第一阶段通过 UART 上传权重到 DDR，避开尚未完成的 Flash 启动路径。

只读核对的 hgb 为 `soc/p2-p3-clock-study@e088a9d`，生产 RTL 提交 `1a4f8fa`。
`docs/fpga/FPGA_ADAPTATION.md` 记录历史最终 P1 综合为 57,437 LUT、41,497 FF、36 DRM、
4 APM；P1 布局失败，当前 P1+P2+P3 组合没有新的 PDS 资源/时序结果。
本次未在现场找到对应 P1 原始报告，以上数字来自工程文档，不能当作当前物理剩余资源。

按用户提出的“Core 已占约一半 LUT”保守安排：已有系统预留 79,900 LUT6，
加速器目标上限 40,000，新 DMA/CSR/时钟适配预留 10,000，另留 29,900 的布局和增长余量。
加速器初始目标同时设为不超过 160 DRM36K、640 APM。这是开发约束，实际能否达到需综合确认；
不能把历史 P1 的 36 DRM/4 APM 当作当前整个系统的固定占用。
现有 hgb 默认 DDR 地址窗口为 512 MiB，板载 1 GiB 不会自动全部可访问。

## 两个模型的实际计算图

使用 [官方 YOLOX](https://github.com/Megvii-BaseDetection/YOLOX/tree/6ddff4824372906469a7fae2dc3206c7aa4bbaee)，
执行 CPU eval 前向并逐个统计 Conv2d。下面的存储是 INT8 投影，MAC 是实际图的卷积计数，
都不包括量化误差评测。完整结果见 [model-comparison.json](../reports/model-comparison.json)。

| 指标 | YOLOX-Nano | YOLOX-Tiny |
| --- | ---: | ---: |
| 参数总数 | 912,159 | 5,055,855 |
| INT8 卷积权重 | 896,512 B / 0.855 MiB | 5,038,272 B / 4.805 MiB |
| 320 输入卷积 MAC | 309,203,200 | 1,897,200,000 |
| 416 输入卷积 MAC | 522,553,408 | 3,206,268,000 |
| 416 最大单个卷积输出，按 INT8 | 692,224 B | 1,038,336 B |
| 卷积类型 | 普通、1×1、depthwise | 普通和 1×1，无 depthwise |
| 官方 416 COCO AP50:95 | 25.8 | 32.8 |

官方 AP 出自上游 README，不是本次复测，也不能直接用于 320 或 INT8。
Tiny 卷积权重是 Nano 的约 5.62 倍，MAC 约 6.14 倍。其普通空间卷积占 MAC 的约 78.69%，
更适合现有普通 CNN 引擎；Nano 的 depthwise 需要独立通路或有效的分组调度，
不能仅凭参数更少判断一定更好移植。Tiny 通道和检测头还需要处理非整 tile 尾部。

两者都由同一个可复用卷积核逐层运行，模型变大主要增加 DDR 占用与执行时间，
不要求按模型参数量等比例增加 LUT。最大单个特征也不是峰值活跃内存；分支、Concat、
部分和和双缓冲仍需做生命周期分配。权重导出后还要对齐真实硬件布局重新统计。

假设 100 MHz、每拍全部 MAC 有效，416 输入的纯卷积时间下界如下：

| 并行 MAC | Nano | Tiny |
| --- | ---: | ---: |
| 64 | 81.65 ms | 500.98 ms |
| 128 | 40.82 ms | 250.49 ms |
| 256 | 20.41 ms | 125.24 ms |

这不是 FPGA 实测，未计搬运、尾块、激活、软核解码与 NMS。
静态图片允许较长延迟，因此 Tiny 仍合理；先以 64/128 MAC 打通，综合余量允许时评估 256。
416 BGR UINT8 图片在 921600 baud、8N1 下仅载荷就需约 5.63 秒；权重只需启动时上传一次。

## 候选核查与排序

| 候选 | 已找到的证据 | 本次结论 |
| --- | --- | --- |
| [adamgallas/fpga_accelerator_yolov3tiny](https://github.com/adamgallas/fpga_accelerator_yolov3tiny) | Genesys ZU3EG YOLOv3-tiny 演示；公开综合报告；Apache-2.0 | 首轮候选：有可量化的卷积核资源和完整调度范例；YOLOX 调度、数值与 Pango 映射由本项目适配 |
| [hawkcl/flexible-inference-engine](https://github.com/hawkcl/flexible-inference-engine) | AX7Z100 YOLOv3-tiny 演示；VC707 RISC-V 流程与视频；MIT | 第二候选：指令式 CNN 执行较完整；需核查位宽、资源和共享 DDR 适配 |
| [NVDLA](https://github.com/nvdla/hw)、[ITRI-OpenDLA](https://github.com/SameLight/ITRI-OpenDLA) | 官方可配置核/AWS FPGA 路线；ITRI 提供 ZCU102/104 的 64 MAC RTL、bitstream、预编译模型 | 第三候选：明确保留；工具链、算子与总线成本较高，先评估 small，不能直接选择 2048 MAC 默认核 |
| [SLACK_FPGA_CNN](https://github.com/M-Lastovka/SLACK_FPGA_CNN) | SV 脉动阵列、Python 编译/验证、Vivado 项目；系统集成和 bitstream 说明仍为 TODO | 尚未找到足够板级资源/性能证据；默认 18 位定点，DSP macro、URAM 需要适配；所查树无 LICENSE |
| [tiny-tpu-v2/tiny-tpu](https://github.com/tiny-tpu-v2/tiny-tpu) | DE1-SoC MNIST 工程、Quartus fitter/STA 报告 | 有 FPGA 工程证据；验证对象是小型两层 MLP，不能据此推断 YOLO 性能；所查树无 LICENSE |
| [harishsg993010/tiny-NPU](https://github.com/harishsg993010/tiny-NPU) | 仿真、编译器；FPGA 资源表明确是估计，上板待办未勾选 | 暂不作为要求已上板高性能 CNN 的主线；未找到标准 LICENSE |
| [kagandikmen/TPU.sv](https://github.com/kagandikmen/TPU.sv) | 核、AXI/SDK 的仿真进展；MIT；实际硬件工作负载评估仍在 Next Steps | 可参考，暂不作为主线 |

公开 bitstream、报告和作者演示说明的是上游平台；本次没有在那些 FPGA 上复现。
源码快照、报告 blob SHA 和网址见 [accelerators.json](../config/accelerators.json)。

### 首轮候选：adamgallas 卷积核

其 [Vivado 综合报告](https://github.com/adamgallas/fpga_accelerator_yolov3tiny/blob/6ba312bd220e67a987d3417bacd030db30b15770/vivado_prj/base.runs/cam_Accel_Conv_0_0_synth_1/cam_Accel_Conv_0_0_utilization_synth.rpt)
针对 `cam_Accel_Conv_0_0`，器件 `xczu3egsfvc784-1`，记录 24,731 LUT、15,207 FF、
39.5 BRAM36、296 DSP48E2，无 latch、无 black box。其中 14,558 LUT 用于存储或移位。
这是单个加速器综合结果，和 README 的 23K FF 汇总口径不同。
README 的小于 50 ms、超过 250 MHz/172 GOPS 是作者原板结果声明，本次没有复测，也不外推到 Pango。

适配工作的关键在于：

- `vivado_prj/source/Accel_Conv.v` 是 64 位 AXI-Stream 数据口和 32 位 AXI-Lite 控制口，
  没有可直接读系统 DDR 的通用 DMA。需要 DDR AXI256↔AXIS64 搬运和 AXI-Lite64↔32 适配，
  保留独立 AW/W 握手、WSTRB、背压和错误响应。
- `cal_mul_int8_x2_dsp.v` 用 27×18 位打包乘法；`cal_mul_int8_x2.v` 包含负数借位修正。
  Pango 25×18 APM 不能直接承诺保持原来的双 INT8/DSP 映射。先验证两条普通 INT8 乘法的
  等价替换，再决定更紧凑的打包；保持原流水延迟。按最多约两倍乘法单元规划仅是预算，
  最终 APM/LUT 必须测量。
- 原工程大量依赖分布式 RAM 和 SRL 的推断。优先改成明确的 Pango RAM/移位缓存映射，
  对照读延迟和读写碰撞行为；直接复制 `ram_style` 属性不能保证资源不增长。
- 原工程以 YOLOv3-tiny 调度，YOLOX 的 Focus、stride-2 卷积、SiLU、SPP 5/9/13、Add、
  Concat 和检测头需重新导出与调度。已有 2×2 pooling 不等于已支持 SPP。
  不能照搬旧量化脚本后宣称达到官方精度；作者也说明已停维护、模型迁移工程量较大。

上游卷积 RTL 与许可现已固定到 `third_party/adamgallas/`，适配代码位于 `rtl/adam/`。
128 MAC 算术、缓存和卷积仿真已通过；完整 YOLOX 调度与 Pango 资源检查仍未完成。
没有复制摄像头、显示、Vivado 生成目录或 Zynq BSP。

### FIE 与 NVDLA 的关键区别

FIE 的 `AIFPGA/.../new/pkg.sv` 为 INT8 特征和权重，但 `MULT_BIT_SIZE=20`，
`UCL.sv` 包含 20 位饱和加法。因此不能直接当作通用 INT8×INT8→INT32 后端；
需要按其数值方式重新校准，或加宽并重新评估资源。
其源码 `BANK_NUM=4`、`CG_NUM=12`、`COMPUTING_GROUP_SIZE=7`，配置规模也不能只按
“几个 DSP”推算面积。原型特征/指令与权重使用不同 DDR，移植后要共享本板 DDR。
从 AIFPGA AXI 路线抽核，无需为本 Core 添加 DeepRV 的 RoCC。
README 的 99%/95% 利用率位于模拟器/AIYolo 分析中，不能标成板上 FPS；
仓库论文给出架构，但本次未找到可直接用于本板预算的完整资源与时序表。

NVDLA 的 [nv_small](https://github.com/nvdla/hw/blob/1a65f1f5b48268accaa47c95f95c2601918be095/spec/defs/nv_small.spec)
是 8×8=64 MAC，[nv_small_256](https://github.com/nvdla/hw/blob/1a65f1f5b48268accaa47c95f95c2601918be095/spec/defs/nv_small_256.spec)
是 32×8=256 MAC；两者关闭 SDP LUT 和 EW。
[nv_small_256_full](https://github.com/nvdla/hw/blob/1a65f1f5b48268accaa47c95f95c2601918be095/spec/defs/nv_small_256_full.spec)
打开这些功能，同时改变内存接口配置。SiLU/残差不能假设所有 small 配置都完整支持，
启用 LUT 也不等于 YOLOX 编译器已能正确导出该激活。
[官方 AWS FPGA 工程](https://github.com/nvdla/vp_awsfpga) 有 256_full 路线，
仍需重新适配 Pango SRAM、时钟、CSB/APB 和 AXI。

ITRI 是更具体的 FPGA 起点：公开 64 MAC、128 KiB 卷积缓存的扁平 RTL，
修改了 uint8 乘法和 FPGA 总线接口；仓库根许可证为 MIT，文件内上游声明仍需保留。
其模型转换、量化重训和 pattern 工具未公开，仅指出兼容 ONNC 的 INT8 loadable。
预编译 Tiny YOLO 不等于 YOLOX-Tiny，必须重新解决模型导出和执行队列。

tiny-tpu-v2 的串口 MNIST 报告为 6,033 ALM、5,556 寄存器、813,056 存储位、100 RAM 块、
7 DSP；50 MHz CLOCK_50 的 slow 85C setup slack 为 +7.147 ns，hold 为 +0.285 ns。
这是 `mnist_serial_classifier`→`mnist_classifier_core` 的 Q8.8、默认 TILE_WIDTH=2 两层 MLP。
ALM 不能直接换算本板 LUT6，也不能按这个 demo 的 7 DSP 预算完整 CNN。

## 选型阶段完成的内容和后续条件

选型阶段只修改 YOLO-accelerate：补齐模型选择参数、两模型计算图与容量分析、Tiny 官方权重
PC 静态图参考、候选源码与资源证据清单。hgb、上级三个文档和任何 AGENTS.md 均未修改。
没有运行 PDS、烧写 Flash、生成可交付板级 bitstream 或接入软核。

目前打包乘法替换、缓存、背压、1×1/3×3/stride-2 卷积及尾通道已通过 Verilator。
后续依次完成 BN 折叠、逐通道量化、SiLU/SPP/分支整数参考、DDR/CSR 与 CPU Cache 交接，
最后接通静态发图。
若加速器超过 40K LUT 或算子/数值改造过重，转向 FIE 的缩小配置；若更看重标准运行时与
后续通用 CNN，则重新比较 NVDLA 64/256。Nano 仅在 Tiny 实测延迟或资源确实不达标时启用。
这几个进入条件必须由测试和报告决定，不能用 README 的原板数字代替。
