# 完整上游数据通路的 Pango 移植

分支 `fpga/adam-upstream-faithful` 从 `f0134a0` 建立。
`fpga/npu128-bringup` 和 `baseline/adam128-image-cosim-20261023` 保留原有实现。
当前主线直接例化固定提交 `6ba312bd220e67a987d3417bacd030db30b15770` 的 `Accel_Conv`。
全部 50 个 RTL 文件及 LICENSE 均按原清单核对 SHA-256，未修改上游代码。
封装只透传原端口和参数，没有另写地址生成器、调度状态机、乘法或量化流水。

## MAC 与数据流

阵列展开 3×3 空间位置、8 个输入通道和 8 个输出通道，共 576 个 INT8 乘法。
层次为四个 `module_conv_kernel_1x2x8`，各包含八个 `module_conv_kernel_1x2`，
各包含九个 `cal_mult_int8_x2`。每个单元的两个输出权重共享一个激活值，使用
27×18 打包乘法和借位修正；288 个打包单元由 Verilator 展开结构核对。
这是直接卷积流水，不是重新设计的脉动阵列。288 个打包单元不等于 288 个 Pango APM。

原结构为输入双缓存、零点减法、行缓存形成 3×3 窗口、四拍乘法、两拍空间加法树、
两拍通道加法树、累加缓存、量化/激活和输出缓存。寄存器边界与控制延迟均沿用原版。
18 位加法/累加溢出按模 2^18 回绕，量化前先饱和为 INT16，再乘 signed INT16 scale、
按 `15+shift` 右移并舍入，饱和到 INT8 后加输出零点。没有改为旧移植版的 INT32 数值规则。

上游的 [布线后报告](https://github.com/adamgallas/fpga_accelerator_yolov3tiny/blob/6ba312bd220e67a987d3417bacd030db30b15770/vivado_prj/base.runs/impl_1/cam_wrapper_timing_summary_routed.rpt)
记录 Xilinx 的 250 MHz 已约束时序通过。该结果不代表本次 Pango 的时序。

## 软件适配

[adam_upstream_abi.h](../software/adam_upstream_abi.h) 可由 RV32IM 编译器按 C11 检查，
不依赖浮点或 Xilinx BSP；仿真驱动直接调用其中的任务发起和数据打包函数。

| 项目 | 原版接口及软件约定 |
| --- | --- |
| CSR | 偏移 0/4/8/12 分别为控制、scale/shift、零点、权重/bias 读地址 |
| 任务 | 写 `task_valid + action`，再撤销；等待外部 `ap_done`，不是读取一个新增状态寄存器 |
| 输入 | 每个像素一拍 64 bit，八个输入通道按低到高字节排列 |
| 权重 | 每组 72 拍；输入通道 → 九个 kernel tap；每拍的八个字节是八个输出通道 |
| bias | 每拍一个 signed INT18，八拍对应八个输出通道；高位忽略 |
| 查表 | 256 拍，每拍低字节为表项；八个输出通道共享同一张表 |
| 输入银行 | 写 bank 为 `ifmbuf_sel`，计算读相反 bank；切换由软件安排 |
| 输入通道分组 | 第一组置 `first_conv` 清除前值影响，最后一组置 `last_conv` 加 bias |
| 输出通道分组 | 软件按八通道分组，尾部补零并丢弃多余输出 |
| 1×1 | 先以 3×3 中心权重承载，其余八个 tap 填零；尚未进行 1×1 利用率优化 |
| 默认行宽 | 含边界的 15、28、54、106、210、418；与原参数累计长度一致 |

默认特征缓存深度为 4096，软件必须满足 `行数 × 含边界宽度 <= 4096`，行数不超过 255。
例如 416 宽输出可按含边界宽 418 的水平条带处理；高度、halo 拼接、stride=2 输出抽样、
YOLOX Focus/Concat/Resize/SPP 等图操作由 CPU 侧软件规划。完整 YOLOX 的条带调度与精度
校准尚未接通，不能把原 128 MAC 的带框图片结果当作本路径的结果。

原权重装载器每拍移位，九拍窗口内部不能插入空拍。原输出流也未验证任意背压。
当前驱动按连续权重传输、输出始终 ready 运行。以后接入 DMA 时需要入口预缓冲和输出
FIFO 满足这些条件；单纯软件打包不能保证总线上没有停顿。输入特征流的空拍已测试。
保留这些约束并不意味着已经完成标准 AXIS 任意背压兼容性验证。

## 验证和复现

```bash
make test
make lint
```

测试通过真实 CSR 与 AXIS 端口完成装载、计算和读回，不强制内部信号。
24 帧含 30 次卷积启动，检查 186,144 个 INT8 输出和每帧 TLAST，覆盖六种原生宽度、
8/16 输入通道、两组输入缓存、1×1/3×3、非零 bias、输入空拍、signed INT8 极值、
18 位回绕、INT16/INT8 饱和、ReLU 与可编程查表。数值参考为独立标量卷积和整数舍入。
两组输入通道测试重用同一份输入/权重以验证累加与 bias 的首末组控制。
pooling、输出背压、输入/输出零点非零和完整模型精度尚未测试。

上游的位宽、隐式线网、组合非阻塞赋值等警告保留在日志；没有宣称原版严格 lint 零警告。
测试脚本拒绝新封装的 warning，分别记录构建、执行、RV32IM ABI 检查和全部源码哈希。
旧后端可单独运行 `make adam-test npu-test`，本轮没有更改或重跑旧后端。

Windows 工程保持独立，设置 `PDS_WORK_ROOT` 后使用新目录名：

```bash
python3 tools/pango/stage_upstream.py --name adam-upstream-new
```

在 Windows PowerShell 中：

```powershell
$project = Join-Path $env:PDS_WORK_ROOT 'work\adam-upstream-new'
& "$project\tools\pango\run_synthesis.ps1" -ProjectRoot $project -JobLimitGiB 2 -ReserveGiB 4
```

完整上游端口都连接到独立顶层，使用 100 MHz 测量约束，输入/输出 delay 为 0–1 ns。
没有板卡引脚、CPU/DDR 集成和布局布线。保护脚本检查其他 PDS 进程和 Windows 物理/提交余量，
只管理本次任务的进程树。默认保留 6 GiB；本次依据实际余量为第二次尝试设为 4 GiB。
原始工程保存在 `F:/pango-project/work/adam-upstream-576-20261023a`、`...20261023b`
和 `...20261023c`。1/2 GiB 两次尝试分别在约 34/340 秒后以 `Flow-0189` 内部错误退出，
任务峰值计数分别约 1025/2049 MiB。峰值计数可能包含被拒绝的分配，不能当成实际 RSS。
错误与配额边界相关，尚未确定工具内部原因，不能据此认定 RTL 错误或时序不满足。
3 GiB 尝试要求 7 GiB 物理及提交余量，预检未通过，未启动综合进程。
当前没有有效的 Pango 资源/Fmax/WNS、综合网表仿真、布局布线或上板结果。
旧 128 MAC 的 71.88 MHz 不属于这个版本。

[仿真记录](../reports/upstream-validation.json) 和
[综合尝试记录](../reports/upstream-synthesis-attempts.json) 保存命令、源码和原始证据哈希。
余量充足时，在新的工程目录运行上述综合命令。结果收集命令为：

```bash
python3 tools/pango/collect_upstream_report.py \
  --project "$PDS_WORK_ROOT/work/adam-upstream-new" --output build/upstream-synthesis.json
```
