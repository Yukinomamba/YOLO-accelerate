# 27 MHz UART 诊断上板记录

2026-10-24，分支 `fpga/npu128-uart`，本轮从 `71a5d99` 接续。
**已完成实际 FPGA 的临时 JTAG 下载、回读校验和配置状态检查；串口卷积自检待做。**
本轮没有修改 RTL、引脚或时钟约束，原 27 MHz 布线证据继续有效。
计算核独立 100 MHz 结果与完整外围的频率边界仍按 [UART128.md](UART128.md) 区分。

## 已完成的实际硬件检查

| 项目 | 实测结果 |
| --- | --- |
| JTAG 链 | 一颗 PG2L200H |
| 器件 ID | `0x00603899` |
| 下载方式 | JTAG 临时配置，`cfg_set_device_property -program 1` |
| JTAG 时钟 | 5 MHz |
| 编程及回读 | `cfg_program=1`、`cfg_verify=1`，均成功 |
| 诊断 usercode | `0x12802701` |
| 配置状态寄存器 | `0x001ffca0` |
| DONE | bit 12 = 1 |
| 错误检查 | `status & 0x1800001f = 0`，含配置 CRC、ID、认证、回读 CRC、超时及过温/局部重配错误 |
| KEY0 | 用户已确认按下并松开；尚未通过 UART 读取复位后的状态 |

此结果证明 FPGA 配置下载和回读正确，不表示板上卷积数值已经通过。
未写外部 Flash、eFuse 或密钥。断电后本临时配置消失，重新供电需再次下载。
实际日志和 SHA-256 见 [上板报告](../reports/npu128-uart-board.json)，
报告状态明确为 `JTAG_PASS_UART_PENDING`。

原生硬件工作目录：`F:\pango-project\work\npu128-uart-board-20261024a`。
`program-a/program.log` 保留全部编程、回读、usercode 和状态输出；
`program-a/program.tcl` 与 `program-receipt.json` 保留调用和进程限额。
本任务 JTAG Server 使用端口 65421；结束核对时该服务已经退出，未关闭其他用户进程。

## 已验收位流

[位流验收报告](../reports/npu128-uart-bitstream.json) 状态 PASS，实际配置如下：

| 项目 | 数值 |
| --- | --- |
| 顶层/时钟 | `npu_uart_board` / 27 MHz |
| 器件 | `PG2L200H-6IFBB676` |
| 位流大小 | 9,188,552 字节 |
| SHA-256 | `0c0e2650dae4eb0025fa02d78680cada8a0c8ca391b597b73bdc8d859c0d3c96` |
| SCBV | `High Voltage` |
| usercode | `12802701` |
| CRC | 开启 |
| 未用 IO | `NONE` |
| 加密 | 关闭 |

板卡 v1.2 手册 PDF 第 11 页（印刷页 8）确认 L3/L4/L5 由 3.3 V 供电。
SCBV 选择同时参考厂商 [PG2L200H FBB676 管脚说明](https://www.pangomicro.com/en/uploads/34165729_1729132019.pdf)
中配置电压与 SCBV 的对应关系；实际 PDS 设置和无 SCBV 关键告警均已经核对。
配置依据与手册哈希见 [uart-bitstream.json](../config/uart-bitstream.json)。

最终原生位流：

```text
F:\pango-project\work\npu128-uart-bitstream-20261024d\prj_tasks\pnr_1\generate_bitstream\npu_uart_board.sbit
```

项目内另有 `build/board-uart-27m/` 包，包含同一位流、两个报告、主机脚本和 `SHA256SUMS`。
该目录及原始 PDS 工程均为忽略产物，未提交 9 MB 二进制到 Git，换机器需重新生成或单独传递并核对哈希。

生成过程从原验收工程复制新快照，显式指定最终 `npu_uart_board_pnr.adf`：

```tcl
gen_bit_stream -force_to_run \
  -input_db_file {prj_tasks/pnr_1/place_route/npu_uart_board_pnr.adf} \
  -scbv {High Voltage} -usercode 12802701
```

`-force_to_run` 仅用于直接运行位流阶段，输入数据库、原物理报告、RTL 和所有约束都逐项核对 SHA-256。
本次没有重新综合或布线，也没有修改原 `npu128-uart-20261024a` 工程。
保护限额为 3 GiB Job、6 GiB 物理/提交余量；实际峰值 Job commit 2,341.1 MiB、耗时 107.638 秒。

生成尝试全部保留：`bitstream-20261024a` 参数互斥失败；`b` 因 PDS 意外启动依赖重跑而主动中止；
`c` 生成成功但 SCBV 未设置，拒绝用于下载；最终仅下载 `d`。原始日志和停止记录哈希写入上板报告。

## 串口目前的边界

Windows PnP 与 pyserial 均只检测到 FTDI `0403:6010` 的 COM9/COM10，以及蓝牙串口。
**未枚举到板载 CP2102，不能把 COM9/COM10 当作本顶层 UART。**
没有打开这些串口，也没有发送卷积命令。用户暂时不能更换 UART 数据线；
尚不能确定是线材、接口还是其他连接问题。当前没有出现带 CP2102 VID 的未知设备，
因此没有安装额外的系统 USB 驱动。

待一根能传数据的 USB 线接到板载 USB-UART Type-C、系统出现 CP2102 串口后，
继续执行识别和三组数值自检。pyserial 3.5 已隔离安装在原生工作目录，未修改全局 Python。
本次下载的 wheel SHA-256 为
`c4451db6ba391ca6ca299fb3ec7bae67a5c55dde170964c7a14ceefec02f2cf0`。

同一台机器可在 PowerShell 中执行（将 `COMx` 换成新出现的 CP2102 端口）：

```powershell
$env:PYTHONPATH='F:\pango-project\work\npu128-uart-board-20261024a\python-deps\site'
$uartPython='C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $uartPython -X utf8 -m serial.tools.list_ports -v
& $uartPython -X utf8 F:\pango-project\work\npu128-uart-board-20261024a\host\npu_uart.py --port COMx
& $uartPython -X utf8 F:\pango-project\work\npu128-uart-board-20261024a\host\npu_uart.py --port COMx --self-test
```

保持 FPGA 本次配置未掉电，配置后先按 KEY0。识别预期 ID `0x4e505531`、ABI `0x10000`。
`--self-test` 会软复位诊断 NPU 并替换测试数据/配置，逐值检查三组卷积；
必须保留实际串口输出，不能用现有 RTL 仿真结果代替上板数值验收。

## 复现生成和 JTAG 下载

在 WSL 用新的目标目录准备快照，再于 PowerShell 运行快照自带脚本：

```bash
python3 tools/pango/stage_bitstream.py \
  --project /mnt/f/pango-project/work/npu128-uart-20261024a \
  --implementation reports/npu128-uart-implementation.json \
  --target /mnt/f/pango-project/work/npu128-uart-bitstream-recheck
```

```powershell
& F:\pango-project\work\npu128-uart-bitstream-recheck\bitstream-input\run_bitstream.ps1 `
  -ProjectRoot F:\pango-project\work\npu128-uart-bitstream-recheck `
  -PdsHome F:\pango\PDS_2025.2-ads
```

随后运行 `tools/pango/collect_uart_bitstream.py --help`，生成新的验收报告。
JTAG 自动脚本为 `tools/pango/program_uart_board.ps1`：需要实际位流、对应 PASS 报告、
PDS 路径、新的原生运行目录，以及本任务 JTAG Server 端口。
脚本会在同一次连接内拒绝多器件链和非 `00603899` 的 ID，再进行临时下载与回读。
Windows RemoteSigned 策略不接受直接执行 UNC 上的未签名脚本时，把该脚本和
`GuardedJob.cs` 复制到新的原生目录执行；不需要更改系统执行策略。
服务启动使用 `Start-Process ... -WindowStyle Hidden`，下载器/串口选择按实际枚举结果核对。

下次接续优先完成 UART ID/ABI 和三组小卷积；之后再给 MMIO 装载控制增加流水、评估完整顶层 100 MHz。
