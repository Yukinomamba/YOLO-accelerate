# 上游来源

来源：[adamgallas/fpga_accelerator_yolov3tiny](https://github.com/adamgallas/fpga_accelerator_yolov3tiny)，
固定提交 `6ba312bd220e67a987d3417bacd030db30b15770`，Apache-2.0，完整许可见 [LICENSE](LICENSE)。

`source/` 是该提交 `vivado_prj/source/` 的全部 50 个文件，加上根 LICENSE，51 个文件
逐字节匹配上游 Git blob。`manifest.json` 记录 SHA-256 和 Git blob SHA-1，
`upstream-blobs.json` 记录从 GitHub 读取的原始 blob ID。`.gitattributes` 保留其原有换行和空白。
这里不含 Vivado 生成文件、bitstream、SDK、模型权重或摄像头/显示工程。

当前主线通过 `rtl/upstream/adam_upstream.sv` 直接例化本目录的完整 `Accel_Conv`，
50 个 RTL 文件保持原样。[当前验证](../../docs/UPSTREAM.md) 已通过原 CSR/AXIS 的完整卷积流。

此前 128 MAC 参考实现的修改位于 `rtl/adam/`，不覆盖本目录：

| 上游模块 | 移植后的对应文件与变化 |
| --- | --- |
| `cal_mul_int8_x2.v`、`cal_mul_int8_x2_dsp.v` | `adam_mul_pair.sv`：两个 signed 8×8 乘法替代 27×18 打包及借位修正，保持四拍延迟 |
| `com_simple_dual_port_ram.v` | `adam_sdp_ram.sv`：增加读使能，去掉上电清零和 Xilinx 属性，保持同步 read-first 行为 |
| `module_conv_kernel_1x2*.v` | `adam_mac128.sv`：保留两输出共享输入的组织，重排为 8 输入×16 输出；kernel tap 分时执行，求和位宽完整保留 |
| 原有窗口/任务控制、18 位累加 | `adam_conv128.sv`：新 tile 取数与握手控制，1×1/3×3、stride、padding、INT32 累加；不保持原版寄存器/流接口兼容 |

128 MAC 参考实现只直接例化原版成对乘法和 RAM 作对照，另与独立整数卷积比较。
当前完整上游回归已包含原版量化、AXIS 和 CSR；DMA/SoC 接入及完整 YOLOX 调度仍未完成。
